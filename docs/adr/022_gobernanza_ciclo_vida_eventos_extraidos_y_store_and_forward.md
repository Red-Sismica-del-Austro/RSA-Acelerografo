---
id: ADR-022
titulo: Gobernanza del Ciclo de Vida de Eventos Extraídos, Resiliencia Store and Forward y Prioridad de Desalojo en Acelerógrafos
estado: Aceptado
fecha: 2026-09-17
temas: [eventos, drive, almacenamiento, retencion, resiliencia, store-and-forward, acelerografo]
entorno: acelerografo
---

# ADR-022: Gobernanza del Ciclo de Vida de Eventos Extraídos, Resiliencia Store and Forward y Prioridad de Desalojo en Acelerógrafos

## Estado

**Aceptado** | Fecha: 2026-09-17

## Contexto

En las estaciones acelerográficas de la Red Sísmica del Austro (RSA), los eventos sísmicos son extraídos como archivos MiniSEED (`.mseed`) hacia `/home/rsa/data/eventos-extraidos/` a través de dos mecanismos: inferencia neuronal continua en streaming (`gpd_stream_worker.py`) o comandos remotos bajo demanda vía MQTT (`event_extractor.py`).

Históricamente, el script periódico de almacenamiento ([`gestor_archivos_acq.py`](file:///home/rsa/git/montajes/acelerografo-DEV00/scripts/operation/drive/gestor_archivos_acq.py)) solo administraba los datos de registro continuo binario (`.dat`) y MiniSEED continuo (`.mseed`). Los eventos extraídos se delegaban a una subida inmediata y puntual mediante `subir_archivo.py --event`. Esta arquitectura presentaba dos deficiencias críticas:

1. **Acumulación infinita en disco local**: Al no existir políticas de retención temporal ni control de espacio para `eventos-extraidos/`, los archivos permanecían en la tarjeta microSD de por vida (acumulando 2.496 archivos en la estación `DEV00`).
2. **Pérdida de eventos ante cortes de red (Ausencia de Store & Forward)**: Si en el instante del sismo la estación sufría una interrupción de internet, caída del módem celular o saturación de la API de Google Drive, `subir_archivo.py` agotaba sus reintentos inmediatos y finalizaba. El archivo local no se borraba, pero **ningún proceso del sistema volvía a intentar subirlo**, dejando los datos sísmicos atrapados en la estación sin llegar a la nube a menos que mediara una intervención manual.

Se evaluó la alternativa de forzar la bandera `--delete` en la subida inmediata frente a la integración de una gobernanza completa y desacoplada dentro del gestor de archivos.

---

## Opciones Evaluadas

### Opción A: Delegación exclusiva a la bandera `--delete` inmediata en el extractor

Consiste en invocar siempre `subir_archivo.py --event <archivo> --delete` tras la extracción del sismo.

* **Ventajas**:
  - Mínimo consumo de espacio en disco (el archivo se elimina inmediatamente tras confirmarse la subida).
  - No requiere modificar `gestor_archivos_acq.py`.
* **Desventajas**:
  - **Sin reintentos asíncronos**: Si la subida falla por desconexión de red, el archivo no se elimina pero queda huérfano; ningún proceso automatizado vuelve a intentar subirlo.
  - **Imposibilidad de auditoría local**: Si el archivo se borra de inmediato, los sismólogos u operadores en campo no pueden inspeccionar localmente la traza del sismo vía SSH, SCP o panel web minutos u horas después del evento.
  - **Riesgo ante desconexión prolongada**: Si la estación permanece offline durante días con alta actividad sísmica o falsos positivos de detección, los eventos fallidos se acumulan sin límites de espacio.

### Opción B: Centralización del ciclo de vida en `gestor_archivos_acq.py` (Store & Forward + Retención Temporal + Prioridad de Desalojo)

Consiste en incorporar el tipo `event` como ciudadano de primera clase en el gestor periódico de adquisición, manteniendo la subida inmediata opcional pero otorgando al gestor la responsabilidad de reintento, retención y espacio.

* **Ventajas**:
  - **Arquitectura Store & Forward**: Todo evento pendiente o cuya subida en caliente falló es detectado automáticamente en el siguiente ciclo periódico del gestor y subido a Google Drive (`drive.carpetas.events_id`).
  - **Ventana de retención sismológica**: Permite configurar una ventana temporal controlada (ej. 7 a 30 días) donde los eventos se conservan localmente para consulta rápida antes de ser eliminados de forma desatendida.
  - **Prioridad de desalojo sismológico**: Ante saturación crítica de disco (< 5%), los eventos se protegen como datos de alto valor científico y solo se desalojan como **último recurso** tras purgar el registro continuo.
  - **Sinergia con el Principio de Registro Espejo (ADR-021)**: Al purgarse un evento caducado del disco físico, su entrada se elimina automáticamente de `uploaded_files_registry.json`.
* **Desventajas**:
  - Requiere adaptar `gestor_archivos_acq.py` y actualizar las plantillas de configuración del sistema.

---

## Decisión

Se eligió la **Opción B**.

Se implementó la gobernanza integral de `/home/rsa/data/eventos-extraidos/` dentro de `gestor_archivos_acq.py` bajo las siguientes directrices técnicas:

1. **Subida y Rescate Desatendido**: En modo `online`, el gestor audita periódicamente `eventos_extraidos/`. Si encuentra archivos `.mseed` no indexados en `archivos_exitosos.event`, los sube automáticamente a la carpeta de eventos en Google Drive con reintentos exponenciales.
2. **Retención Temporal Configurable**: Se incorporó el parámetro `politicas[modo].retener_dias.event` en `configuracion_dispositivo.json` (con soporte por defecto de 30 días y ajuste operativo a 7 días en DEV00), eliminando solo los eventos que superen dicha antigüedad y que no estén protegidos por fallos de subida.
3. **Jerarquía Estricta de Desalojo ante Espacio Crítico (< 5%)**:
   - *Prioridad 1 de desalojo*: Archivos binarios continuos `.dat` (descartables porque ya fueron convertidos a MiniSEED continuo).
   - *Prioridad 2 de desalojo*: Archivos MiniSEED continuos `.mseed` antiguos ya subidos.
   - *Prioridad 3 de desalojo (Último Recurso)*: Eventos extraídos `.mseed` antiguos ya subidos (FIFO), preservando siempre la información sísmica focal.
4. **Validación Preventiva**: Se mantiene `eliminar_archivo_con_verificacion()`, impidiendo que un evento sea borrado de disco si figura en `archivos_fallidos.event`.

---

## Consecuencias

### Consecuencias Positivas
- **Resiliencia comprobada en producción**: Durante la primera ejecución real en la estación `DEV00`, el gestor detectó y subió con éxito **9 eventos pendientes del 7 de septiembre** que nunca habían sido enviados a la nube.
- **Saneamiento masivo y liberador de espacio**: Se eliminaron de forma segura **1.546 eventos caducados** (> 7 días) que ya contaban con respaldo en Drive, conservando intactos 959 eventos recientes.
- **Registro Espejo sincronizado**: El archivo `uploaded_files_registry.json` se podó automáticamente de 2.908 a exactamente **1.371 entradas activas**, coincidiendo 1:1 con el inventario físico en disco.
- **Trazabilidad transparente**: Se añadieron métricas explícitas en el nivel `SUMMARY` (`retencion_evaluada`, `event_expirados`) y soporte transparente para simulaciones `--dry-run`.

### Consecuencias Negativas / Deuda Técnica
- Durante la ventana de retención (ej. 7 días), los eventos ocupan espacio físico en la microSD, requiriendo que la política de días se ajuste según la tasa de sismicidad y falsos positivos de la estación.

### Trabajo Futuro Derivado
- Replicar la configuración de retención de eventos (`"event": 7` o `"event": 30`) en las plantillas y estaciones en producción (`TEST`, `CHA01`) mediante `update.sh`.

---

## Referencias

- **ADR Relacionado**: [ADR-021: Sincronización Espejo del Registro de Google Drive y Síntesis de Diagnóstico](021_sincronizacion_espejo_registro_drive_y_sintesis_diagnostico.md)
- **Blueprint de Implementación**: [`docs/blueprints/2026-09-17_plan_administracion_eventos_extraidos_gestor_acq.md`](file:///home/rsa/git/montajes/acelerografo-DEV00/docs/blueprints/2026-09-17_plan_administracion_eventos_extraidos_gestor_acq.md)
- **Contexto Técnico**: [`docs/context/gestor_archivos_acq_context.md`](file:///home/rsa/git/montajes/acelerografo-DEV00/docs/context/gestor_archivos_acq_context.md)
- **Suite de Pruebas**: `scripts/operation/drive/test_gestor_eventos.py`

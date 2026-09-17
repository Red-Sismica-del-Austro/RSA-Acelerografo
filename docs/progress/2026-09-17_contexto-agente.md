# Resumen de Sesión: Optimización del Registro Drive, Síntesis de Diagnóstico y Gobernanza Integral de Eventos Extraídos (Store & Forward)

**Fecha**: 2026-09-17  
**Repositorio**: `acelerografo-DEV00`  
**Agente de IA**: Antigravity  
**Usuario**: Milton Muñoz  

---

## 🎯 Objetivo de la Sesión

Consolidar una arquitectura robusta, predecible y resiliente para el almacenamiento local y la sincronización a Google Drive en las estaciones acelerográficas de la RSA, abordando dos frentes críticos:

1. **Principio de Registro Espejo y Diagnóstico Sintético (ADR-021)**: Erradicar el crecimiento indefinido de `uploaded_files_registry.json` garantizando que el JSON represente exclusivamente el inventario de subida de los archivos físicamente presentes en disco local para deduplicación activa. Automatizar la poda periódica, habilitar saneamiento manual bajo demanda (`--purge-registry`) y sustituir el volcado masivo en `diagnostico.sh` por un reporte ejecutivo sintético.
2. **Gobernanza Integral del Ciclo de Vida de Eventos Extraídos (ADR-022)**: Incorporar `/home/rsa/data/eventos-extraidos/` dentro del gestor periódico `gestor_archivos_acq.py`. Implementar una arquitectura **Store & Forward** para rescatar eventos no subidos por cortes transitorios de red, habilitar retención temporal configurable por días, definir una jerarquía estricta de desalojo ante espacio crítico (< 5%) que priorice los eventos sobre el registro continuo, y sincronizar la purga con el Registro Espejo.

---

## 📂 Estructura del Repositorio Implementada

```text
montajes/acelerografo-DEV00/
├── config/
│   └── configuracion_dispositivo.json                                     # [MODIFICADO] Adición de politicas[modo].retener_dias.event (7 días en DEV00)
├── docs/
│   ├── adr/
│   │   ├── 021_sincronizacion_espejo_registro_drive_y_sintesis_diagnostico.md # [NUEVO] ADR formalizando el principio de Registro Espejo
│   │   └── 022_gobernanza_ciclo_vida_eventos_extraidos_y_store_and_forward.md # [NUEVO] ADR gobernanza de eventos, Store & Forward y desalojo
│   ├── blueprints/
│   │   ├── 2026-09-17_plan_optimizacion_registro_drive_diagnostico.md         # [NUEVO] Blueprint optimización de registro y diagnóstico
│   │   └── 2026-09-17_plan_administracion_eventos_extraidos_gestor_acq.md     # [NUEVO] Blueprint de gobernanza de eventos en gestor_archivos_acq
│   ├── context/
│   │   ├── ayuda_context.md                                                   # [MODIFICADO] Banderas --purge-registry y --raw
│   │   ├── diagnostico_context.md                                             # [MODIFICADO] Salida ejecutiva de 25 líneas y bandera --raw
│   │   ├── drive_status_manager_context.md                                    # [NUEVO] Contexto técnico y arquitectura de drive_status_manager
│   │   └── gestor_archivos_acq_context.md                                     # [MODIFICADO] Ciclo de vida completo (continuo + eventos extraídos)
│   └── progress/
│       ├── 2026-09-15_contexto-agente.md
│       └── 2026-09-17_contexto-agente.md                                      # [ACTUALIZADO] Documento de transición técnica consolidado
└── scripts/
    ├── operation/
    │   └── drive/
    │       ├── drive_status_manager.py                                        # [MODIFICADO] Validación os.path.isdir, métricas y resumen diagnóstico
    │       ├── gestor_archivos_acq.py                                         # [MODIFICADO] Gobernanza de eventos, Store & Forward, poda espejo y flags
    │       ├── test_drive_status_manager.py                                   # [NUEVO] Suite unitaria (7/7 pruebas aprobadas)
    │       └── test_gestor_eventos.py                                         # [NUEVO] Suite unitaria de eventos y Store & Forward (5/5 aprobadas)
    └── task/
        ├── ayuda.sh                                                           # [MODIFICADO] Documentación de opciones --raw y --purge-registry
        └── diagnostico.sh                                                     # [MODIFICADO] Resumen sintético vía Python y soporte flag --raw
```

*(En el repositorio institucional federado `rsa/RSA-Metodologias/` se incorporaron `decisiones/021_...md` y `decisiones/022_...md`, con actualización de sus índices `decisiones/index.md` e `indice/indice_tematico.md`).*

---

## ⚙️ Configuración del Entorno Virtual (`.venv`)

El entorno operativo reside en la Raspberry Pi 3B+ bajo:
`/home/rsa/projects/acelerografo/.venv/` (Python 3.9+).

* **Cero Dependencias Externas Nuevas**:
  - Tanto los módulos productivos (`drive_status_manager.py`, `gestor_archivos_acq.py`) como las suites de prueba (`test_drive_status_manager.py`, `test_gestor_eventos.py`) utilizan exclusivamente la biblioteca estándar de Python (`os`, `json`, `time`, `datetime`, `argparse`, `unittest`, `tempfile`, `fcntl`, `shutil`).
  - `diagnostico.sh` invoca `$VENV_PYTHON` (`$PROJECT_LOCAL_ROOT/.venv/bin/python3`) de forma embebida para ejecutar de manera aislada y atómica `drive_status_manager.obtener_resumen_diagnostico()`, con fallback nativo en Bash (`head -n 25`) en caso de anomalía.

---

## 🛠️ Modificaciones de Código y Refactorización

### 1. Robustecimiento de `drive_status_manager.py` y Suite de Tests (ADR-021)
* **Validación Preventiva de Directorios**: Se implementó una verificación con `os.path.isdir(directorio)` en `limpiar_archivos_inexistentes()`. Si un volumen está desmontado, se omite su poda para prevenir que una desconexión transitoria vacíe el registro.
* **Métricas Granulares**: Retorno detallado de entradas podadas (`exitosos_removidos`, `fallidos_removidos`, desglose por tipo `mseed`, `continuous`, `event`).
* **Resumen Diagnóstico Sintético**: Función `obtener_resumen_diagnostico()` que provee métricas de balance, inventario físico vs indexado, y últimos archivos procesados.
* **Suite de Pruebas Unitarias**: Se creó `scripts/operation/drive/test_drive_status_manager.py` (7/7 pruebas superadas en producción).

### 2. Síntesis de Reporte en `diagnostico.sh` y Ayuda CLI (ADR-021)
* **Eliminación de Saturación de Terminal**: Se reemplazó el `cat` masivo del JSON (miles de líneas) por el resumen ejecutivo de ~25 líneas.
* **Soporte `--raw`**: Se añadió la bandera `-r` / `--raw` a `diagnostico drive` y `diagnostico all` para permitir auditoría del JSON crudo si el operador lo requiere.
* **Actualización en `ayuda.sh`**: Documentación interactiva de las nuevas opciones CLI.

### 3. Poda Periódica y Comando `--purge-registry` en `gestor_archivos_acq.py` (ADR-021)
* **Poda Automática**: Invocación al término del ciclo de almacenamiento para eliminar claves huérfanas correspondientes a archivos físicos borrados.
* **Comando bajo Demanda**: Flag `--purge-registry` con soporte `--dry-run` para previsualizar o forzar la sincronización del registro JSON en cualquier momento.

### 4. Gobernanza Integral de Eventos Extraídos en `gestor_archivos_acq.py` (ADR-022)
* **Arquitectura Store & Forward (Rescate Desatendido)**: En modo `online`, el gestor audita periódicamente `eventos_extraidos/`. Si encuentra archivos `.mseed` no presentes en `archivos_exitosos.event`, los sube automáticamente a Google Drive con reintentos exponenciales.
* **Retención Temporal Configurable**: Incorporación de `politicas[modo].retener_dias.event` en `configuracion_dispositivo.json` (fijado a 7 días en `DEV00`). Elimina archivos con antigüedad mayor a los días estipulados, siempre que hayan sido subidos con éxito o no estén marcados como fallidos.
* **Jerarquía Estricta de Desalojo ante Espacio Crítico (< 5%)**:
  1. *Prioridad 1 (Descartable)*: Archivos binarios `.dat` (ya convertidos a MiniSEED continuo).
  2. *Prioridad 2*: MiniSEED continuos `.mseed` antiguos ya subidos.
  3. *Prioridad 3 (Último Recurso)*: Eventos extraídos `.mseed` antiguos ya subidos (FIFO), preservando al máximo la información sismológica de alta relevancia.
* **Protección Preventiva**: Integración con `eliminar_archivo_con_verificacion()`, impidiendo que un evento sea borrado si figura en `archivos_fallidos.event`.
* **Soporte `--dry-run` y Trazabilidad `SUMMARY`**: Métricas explícitas en consola y logs (`retencion_evaluada`, `event_expirados`, `upload_resumen`).

### 5. Suite Unitaria de Eventos (`test_gestor_eventos.py`)
* Se desarrolló una suite completa con 5 pruebas automatizadas cubriendo:
  1. `test_descubrimiento_y_subida_eventos_pendientes`: Store & Forward funcional.
  2. `test_retencion_dias_eventos`: Purgado de caducados y conservación de recientes.
  3. `test_proteccion_eventos_fallidos`: Prohibición de borrado si la subida falló.
  4. `test_desalojo_jerarquico_espacio_critico`: Eventos desalojados como último recurso tras `.dat` y `.mseed`.
  5. `test_dry_run_eventos`: Simulación estricta sin mutaciones en disco ni JSON.
* **Resultado en Producción**: 5/5 pruebas aprobadas exitosamente (`OK`).

---

## 📊 Validación en Vivo en la Estación DEV00

Durante la ejecución real de validación en la estación de producción `DEV00` se registraron los siguientes resultados cuantitativos:

1. **Store & Forward en Acción**: Se detectaron **9 eventos sísmicos pendientes del 7 de septiembre** que nunca habían sido enviados a Google Drive debido a un corte previo de conectividad. El gestor los subió con éxito absoluto (`upload_resumen=9/9`).
2. **Saneamiento Masivo de Almacenamiento**:
   - Total eventos iniciales en disco: 2.505 archivos.
   - Eventos caducados purgados (> 7 días): **1.546 archivos**.
   - Eventos conservados (< 7 días): **959 archivos**.
3. **Poda Automática del Registro Espejo**:
   - Entradas iniciales en `uploaded_files_registry.json`: 2.908 entradas.
   - Claves físicas huérfanas podadas: **1.537 entradas**.
   - Entradas finales activas en registro: **1.371 entradas**, coincidiendo 1:1 con el inventario físico en `/home/rsa/data/`.

---

## 📋 Pasos Sugeridos para el Siguiente Agente

1. **Replicación de Configuración en Plantillas Institucionales**:
   - En `RSA-Acelerografo/config/configuracion_dispositivo.json.template` (o repo maestro), asegurar que `politicas.online.retener_dias` y `politicas.offline.retener_dias` incluyan `"event": 30` (o valor por defecto institucional) para nuevas instalaciones.

2. **Despliegue y Saneamiento en Estación `TEST`**:
   - Al actualizar `TEST` (que acumula >4.700 entradas de meses anteriores cuyos archivos físicos ya no existen):
     - Ejecutar: `python3 scripts/operation/drive/gestor_archivos_acq.py --purge-registry --dry-run` para previsualizar los huérfanos detectados (~4.000 esperados).
     - Ejecutar: `python3 scripts/operation/drive/gestor_archivos_acq.py --purge-registry` para purgar el JSON.
     - Verificar con `diagnostico drive` que el tamaño del registro descienda a ~749 entradas y 0 huérfanos.

3. **Despliegue en Estación Operativa `CHA01`**:
   - Incorporar la clave `"event": 7` en `configuracion_dispositivo.json` de `CHA01` y verificar su ciclo de subida de eventos tras el próximo despliegue.

4. **Monitoreo Continuo de Telemetría**:
   - Monitorear los tópicos MQTT de telemetría (`rsa/seismic/smart/DEV00/status/drive`) para verificar que el reporte periódico de `drive_watchdog.py` mantenga métricas consistentes con el registro saneado.

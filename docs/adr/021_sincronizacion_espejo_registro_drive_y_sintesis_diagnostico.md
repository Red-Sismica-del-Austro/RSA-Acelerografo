---
id: ADR-021
titulo: Sincronización Espejo del Registro de Google Drive con el Almacenamiento Local y Síntesis de Diagnóstico
estado: Aceptado
fecha: 2026-09-17
temas: [drive, almacenamiento, saneamiento, sincronizacion, diagnostico, json, resiliencia, acelerografo]
entorno: acelerografo
---

# ADR-021: Sincronización Espejo del Registro de Google Drive con el Almacenamiento Local y Síntesis de Diagnóstico

## Estado

**Aceptado** | Fecha: 2026-09-17

---

## Contexto

El sistema de gestión de archivos y sincronización con Google Drive (`gestor_archivos_acq.py`, `subir_archivo.py`) utiliza un registro JSON persistente (`uploaded_files_registry.json`) para evitar la re-subida de archivos que ya fueron transferidos a la nube. Durante la operación prolongada y pruebas en estaciones como `DEV00` y `TEST`, se identificó una deficiencia estructural en el ciclo de vida de este registro:

1. **Crecimiento Sin Cota (*Append-Only*)**: Cada subida exitosa agregaba una entrada mediante `marcar_como_exitoso()`. Sin embargo, cuando los archivos físicos eran purgados de las particiones de almacenamiento (`/home/rsa/data/mseed/`, `/home/rsa/data/registro-continuo/`) por políticas de retención temporal o por espacio mínimo en disco, sus claves nunca se eliminaban del JSON.
2. **Desfase Histórico e Impacto en Hardware Embebido**: En estaciones con meses de actividad como `TEST`, el archivo JSON acumuló más de 4.700 entradas (con archivos desde febrero de 2026 e identificadores pasados como `DEV00`, `DEV01` y `TEST`), cuando en disco físico residían únicamente 749 archivos MiniSEED activos. En una Raspberry Pi 3B+ con almacenamiento en tarjeta microSD, serializar y deserializar periódicamente archivos JSON de miles de líneas genera sobrecarga innecesaria de I/O, CPU y consumo de memoria en cada ciclo del gestor y del watchdog (`drive_watchdog.py`).
3. **Persistencia de Falsos Fallidos**: Registros de errores de subida transitorios de meses pasados permanecían indefinidamente en `archivos_fallidos`, ensuciando el inventario de la estación.
4. **Colapso de la Herramienta de Diagnóstico (`diagnostico.sh`)**: La rutina `diagnostico_drive()` ejecutaba un `cat` ciego de `uploaded_files_registry.json`, volcando miles de líneas no estructuradas que saturaban la terminal del operador, consumían ancho de banda SSH y desbordaban el contexto de tokens en auditorías asistidas por agentes IA.
5. **Función de Saneamiento Huérfana**: En `drive_status_manager.py` ya existía la función `limpiar_archivos_inexistentes()`, pero ningún proceso del sistema la invocaba periódicamente, y carecía de validación ante directorios ausentes o desmontados.

---

## Opciones Evaluadas

### Opción A: Rotación Temporal o de Tamaño del Registro (Estilo Logrotate)
Rotar `uploaded_files_registry.json` cuando alcance un tamaño máximo o cada $N$ días, manteniendo copias comprimidas (`.1`, `.2.gz`).
- **Ventajas**: Fácil de configurar en el sistema operativo.
- **Desventajas**: **Inadmisible operacionalmente**. Si el archivo se rota mientras un archivo MiniSEED aún reside en disco esperando su ventana de retención (ej. 30 días), el gestor perdería el registro de subida y volvería a subirlo a Google Drive, duplicando datos y consumiendo ancho de banda celular.

### Opción B: Base de Datos Local SQLite
Sustituir el archivo JSON por una base de datos SQLite con índices y estados por archivo.
- **Ventajas**: Consultas atómicas y mayor capacidad de indexación histórica.
- **Desventajas**: Complejidad innecesaria, dependencias adicionales de compilación/runtime en C/Python y sobrecarga de escritura en tarjetas microSD ante cortes abruptos de energía. El propósito local de la estación es deduplicar únicamente lo que existe en disco, no almacenar un historial infinito de la nube.

### Opción C: Sincronización Espejo con Almacenamiento Físico, Poda Periódica con Salvaguarda y Síntesis en Diagnóstico (Elegida)
Establecer el principio arquitectónico de que **el registro JSON debe ser un espejo exacto del disco físico**, podando automáticamente las claves de archivos eliminados, blindando la poda ante volúmenes desmontados y sintetizando la inspección en `diagnostico.sh`.
- **Ventajas**:
  - El tamaño del JSON permanece estrictamente acotado a la cantidad de archivos activos en disco (~cientos en lugar de decenas de miles).
  - Cero duplicaciones en Google Drive: mientras un archivo exista físicamente, su registro se preserva; una vez borrado, no hay riesgo físico de re-subida.
  - Eliminación automática de entradas huérfanas en `archivos_fallidos`.
  - Reporte de diagnóstico ultracompacto (~25 líneas) y legible para humanos y LLMs.
  - Preserva la arquitectura sin dependencias adicionales (JSON estándar).
- **Desventajas**:
  - Si un archivo borrado de disco es restaurado manualmente con el mismo nombre exacto, el gestor lo tratará como nuevo y lo subirá a Drive (lo cual es deseable en contingencias de recuperación de datos).

---

## Decisión

Se adoptó la **Opción C**, implementando cinco mecanismos coordinados:

### 1. Modelo de Sincronización Espejo
El registro `uploaded_files_registry.json` actúa exclusivamente como caché de deduplicación acotada al inventario de archivos locales. No cumple rol de base de datos histórica.

### 2. Poda Automática en Ciclo de Vida (`gestor_archivos_acq.py`)
Al culminar las políticas de retención temporal y espacio en disco, el gestor invoca automáticamente `limpiar_archivos_inexistentes()`. Si hubo poda, emite un resumen estructurado:
```text
[SUMMARY] | registry_cleanup=success | exitosos_purgados=X | fallidos_purgados=Y
```
Si el registro ya está alineado con el disco, emite: `[SUMMARY] | registry_cleanup=nominal | huerfanos=0`.

### 3. Salvaguarda de Integridad ante Volúmenes Desmontados
En `drive_status_manager.py`, se incorporó la validación obligatoria:
```python
if not directorio or not os.path.isdir(directorio):
    continue
```
Si una partición de datos o almacenamiento externo no está montada temporalmente, la poda de esa categoría se omite por seguridad, evitando que la falta temporal de montaje vacíe erróneamente el registro.

### 4. Opción de Poda Directa e Inventario Bajo Demanda (`--purge-registry`)
Se implementó en `gestor_archivos_acq.py` la opción `--purge-registry` (con soporte para `--dry-run`), permitiendo sincronizar el JSON en menos de un segundo tras borrados manuales o limpiezas de emergencia, mostrando en consola el inventario completo y el desglose de archivos presentes vs. huérfanos.

### 5. Síntesis Ejecutiva en Diagnóstico (`diagnostico.sh`)
Se reemplazó el volcado masivo `cat` en `diagnostico_drive()` por una rutina que consume `drive_status_manager.obtener_resumen_diagnostico()`, emitiendo una síntesis ejecutiva de ~25 líneas con:
- Totales de archivos registrados y estado de salud.
- Métricas por categoría (`mseed`, `continuous`, `event`, etc.).
- Últimos 5 archivos subidos por categoría con marca temporal.
- Confirmación explícita de incidentes o `✓ Sin archivos fallidos retenidos`.
- Parámetro opcional `--raw` (`diagnostico drive --raw`) para acceder al JSON íntegro si un operador lo requiere expresamente.

---

## Consecuencias

### Positivas
- **Rendimiento y Durabilidad del Hardware**: El archivo JSON deja de crecer indefinidamente; las operaciones de lectura y escritura son casi instantáneas y minimizan el desgaste de la tarjeta microSD.
- **Trazabilidad y Limpieza**: Se eliminan automáticamente registros huérfanos antiguos de estaciones pasadas (`DEV00`, `DEV01`, `TEST`) al alinearse con la partición actual.
- **Eficiencia en Diagnóstico y Asistencia IA**: `diagnostico_report.log` se reduce de miles de líneas a solo 170 líneas totales, permitiendo un diagnóstico rápido y sin desbordamiento de tokens.
- **Tolerancia a Borrados Manuales**: Si un operador borra archivos manualmente, el sistema se auto-sincroniza en el siguiente ciclo o al invocar `--purge-registry`.

### Negativas / Deuda Técnica Mitigada
- **Archivos de Eventos sin Retención Temporal**: Se constató que `gestor_archivos_acq.py` aplica retención sobre `mseed` y `continuous`, pero no sobre `eventos-extraidos`. Los eventos permanecen en disco y por ende en el JSON hasta que se implemente una política formal de retención para eventos extraídos.

---

## Referencias

- Sesión de origen: Sesión 2026-09-17 (Saneamiento de Drive y Diagnóstico).
- Plan de implementación: `docs/blueprints/2026-09-17_plan_optimizacion_registro_drive_diagnostico.md`.
- Contextos técnicos:
  - `docs/context/drive_status_manager_context.md`
  - `docs/context/gestor_archivos_acq_context.md`
  - `docs/context/diagnostico_context.md`
  - `docs/context/ayuda_context.md`

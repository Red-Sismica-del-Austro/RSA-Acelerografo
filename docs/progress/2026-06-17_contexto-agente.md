---
## Contexto de Sesión — Acelerógrafo DEV00 / Sistema Ring Buffer

**Directorio de trabajo exclusivo**: `montajes/acelerografo-DEV00`
**Fecha de última actualización**: 2026-06-17

---

## Estado de Implementación

### ✅ Fase 1 Completada — `core/frame_decoder.py`
- **Tests**: `scripts/operation/core/test_frame_decoder.py` → **27/27 pasados**
- Decodificación 20-bit, timestamps, `build_test_frame()` para tests.
- Hallazgo crítico: `clock_source` siempre es `0` desde disco/pipe (bug firmware dsPIC).
- Dual extracción de fecha: desde trama (`usar_fecha_filename=False`) o desde nombre de archivo (`True`).

### ✅ Fase 2 Completada — `streaming/ring_buffer_store.py`
- **Tests**: `scripts/operation/streaming/test_ring_buffer_store.py` → **19/19 pasados**
- Almacén rotativo de tramas `.bin` en `/home/rsa/data/ring-buffer/`.
- API: `write_frame(raw, ts)`, `query_raw(start, end)`, `query(start, end)`, `close()`.
- Rotación cada 300 s; retención FIFO al superar 500 MB. Thread-safe con `Lock`.

### ✅ Fase 3 Completada — `streaming/stream_processor.py`
- **Tests**: `scripts/operation/streaming/test_stream_processor.py` → **18/18 pasados**
- Daemon que lee `/tmp/my_pipe` con `O_RDWR | O_NONBLOCK` y alimenta `RingBufferStore`.
- Ver detalles completos en la sección siguiente.

### 🔲 Fase 4 Pendiente — Integración MQTT en `event_extractor.py`
- Ver plan de implementación para la especificación completa.

---

## Fase 3: Detalles de Implementación Relevantes para la Fase 4

### Comportamiento del pipe (decisión confirmada)

El programa C `registro_continuo_4.5.0.c` escribe al pipe con `O_WRONLY | O_NONBLOCK` y cierra en cada trama. El `StreamProcessor` lo abre con `O_RDWR | O_NONBLOCK`:
- **O_RDWR**: evita el EOF al no haber escritor (Opción B confirmada).
- **O_NONBLOCK**: evita que `os.read()` bloquee; levanta `BlockingIOError` cuando no hay datos, permitiendo que `stop()` funcione sin demora.

### Acumulador de lecturas parciales

El daemon mantiene un `bytearray` interno que acumula chunks hasta completar exactamente 2506 bytes antes de procesar cada trama. Esto es transparente para el resto del sistema.

### Tramas inválidas

Las tramas con timestamp inválido (hora>23, min>59, seg>59) se descartan con `WARNING` en log y se contabilizan en `frames_invalidos`. No interrumpen el bucle.

### Estadísticas expuestas por `StreamProcessor`

| Atributo | Descripción |
|----------|-------------|
| `frames_procesados` | Tramas escritas exitosamente al ring buffer |
| `frames_invalidos` | Tramas descartadas por timestamp inválido |
| `frames_error` | Tramas con error de escritura |

### Nota sobre `usar_fecha_filename` en el daemon

En `stream_processor.py`, el pipe no tiene nombre de archivo asociado, por lo que `usar_fecha_filename` no puede aplicarse directamente a las tramas leídas del pipe. El `RingBufferStore` sí usa `usar_fecha_filename=True` al **reconstruir el índice** desde los archivos `.bin` en disco (mitiga el bug de fecha del dsPIC). Al escribir tramas desde el pipe, el timestamp se extrae de la trama misma (bytes 2503-2505 de la hora, que sí son confiables).

---

## Hallazgos de Despliegue en Producción y Permisos

Durante las pruebas reales del demonio en la Raspberry Pi, se detectaron y corrigieron dos limitaciones importantes de despliegue:

### 1. Permisos del Named Pipe (`/tmp/my_pipe`)
- **Problema:** El programa de adquisición `registro_continuo` corre como `root`, lo que hace que `/tmp/my_pipe` se cree con permisos heredados restrictivos por la `umask` de `root` (ej. `0600` o `0644`). Esto hacía que `stream_processor.py` (que corre bajo el usuario `rsa`) fallara con `PermissionError` al intentar abrir el pipe en modo `os.O_RDWR` para su lectura.
- **Solución:** Se añadió una llamada explícita a `chmod(PIPE_NAME, 0666)` en el código C de `registro_continuo_4.5.0.c` después de crear/verificar el named pipe. Esto garantiza de raíz que el pipe sea accesible en lectura y escritura para cualquier usuario del sistema (incluido `rsa`).
- **Manejo en Python:** `stream_processor.py` intercepta `PermissionError` y registra una advertencia explícita en los logs indicando cómo solucionarlo manualmente (`sudo chmod 666 /tmp/my_pipe`) si llegase a fallar en otros entornos.

### 2. Automatización del Despliegue con Supervisor
- **Supervisor:** Se configuró el servicio daemon en Supervisor mediante la plantilla [[stream_processor.conf](file:///home/rsa/git/montajes/acelerografo-DEV00/scripts/task/stream_processor.conf)]. Corre bajo el usuario `rsa`, tiene políticas de reinicio automático y escribe logs en `$PROJECT_LOCAL_ROOT/log-files/supervisor_stream_processor.log` y `.err`.
- **Script de Actualización:** Se modificó [[update.sh](file:///home/rsa/git/montajes/acelerografo-DEV00/scripts/setup/update.sh)] para crear y mantener sincronizados los directorios `scripts/core/` y `scripts/streaming/` en producción, además de procesar y recargar la configuración del demonio de Supervisor de forma totalmente transparente al ejecutar la opción de actualización estándar.

---

## Fase 4: Especificación de la Integración MQTT


La Fase 4 modifica **únicamente** `scripts/operation/mqtt/event_extractor.py`.

### Estado actual de `event_extractor.py`

El módulo ya existe y está en producción. Orquesta:
1. `extract_segment.py` (via venv) → genera `.mseed` desde archivos en disco.
2. `subir_archivo.py` (via `sys.executable`) → sube a Google Drive.

La función principal es `extraer_y_subir_evento(start, duration, upload, delete_after_upload, logger)` y retorna un `dict` con `status`, `output_file`, `uploaded`, `phase`, `message`.

### Qué debe agregar la Fase 4

Añadir una **nueva fuente de datos**: el ring buffer en disco. El comportamiento esperado según el plan:

1. Cuando llegue un comando MQTT `extract_event`, el orquestador debe intentar primero extraer datos del **ring buffer** (vía `RingBufferStore.query_raw()`), y solo si el rango no está disponible en el buffer, caer al método tradicional (`extract_segment.py`).

2. La respuesta MQTT debe incluir el campo `source` indicando de dónde vino el dato:
   - `"ring_buffer"` → datos extraídos del ring buffer (memoria/disco reciente).
   - `"mseed_archive"` → datos extraídos de los archivos `.mseed` en disco.

### Decisión de diseño confirmada

| Decisión | Valor |
|----------|-------|
| Campo `source` en respuesta MQTT | `"ring_buffer"` o `"mseed_archive"` |
| Prioridad de extracción | Ring buffer primero; archivos `.mseed` como fallback |
| Ruta del ring buffer | `/home/rsa/data/ring-buffer/` |

### Cómo instanciar `RingBufferStore` desde `event_extractor.py`

```python
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from streaming.ring_buffer_store import RingBufferStore
from core.frame_decoder import FRAME_SIZE

store = RingBufferStore(
    directorio="/home/rsa/data/ring-buffer/",
    max_size_mb=500,
    archivo_duracion_s=300,
    usar_fecha_filename=True,   # Usa nombre del archivo para la fecha (mitiga bug dsPIC)
)
raw_frames = store.query_raw(start_dt, end_dt)  # Lista de bytes crudos de 2506 bytes
store.close()
```

> ⚠️ El `event_extractor.py` solo consulta el ring buffer (lectura). **No** debe instanciar `StreamProcessor` ni escribir en el buffer. El daemon `stream_processor.py` es el único escritor.

### Flujo de datos esperado en Fase 4

```
Comando MQTT extract_event
    │
    ▼
event_extractor.extraer_y_subir_evento()
    │
    ├─ 1. RingBufferStore.query_raw(start, end)
    │       ├─ Datos disponibles → convertir a .mseed vía binary_to_mseed
    │       │   source = "ring_buffer"
    │       └─ Sin datos → fallback
    │
    ├─ 2. Fallback: extract_segment.py (subprocess, venv)
    │       source = "mseed_archive"
    │
    └─ 3. subir_archivo.py (subprocess, sys.executable) [si upload=True]
```

### Conversión de tramas crudas a miniSEED

Las tramas del ring buffer son binario crudo compatible con `binary_to_mseed.py`. La manera más limpia de convertirlas es escribirlas a un archivo `.bin` temporal y llamar a `binary_to_mseed.py --file <tmp.bin>` como subproceso, igual que ya hace el sistema con los archivos `.dat`. Alternativamente, puede escribirse una función interna usando ObsPy si se desea evitar el subproceso; consultar `docs/context/binary_to_mseed_context.md` para los detalles de conversión.

---

## Estructura del Proyecto (estado actual)

```
scripts/operation/
├── core/
│   ├── __init__.py               ✅
│   ├── frame_decoder.py          ✅
│   └── test_frame_decoder.py     ✅
├── streaming/
│   ├── __init__.py               ✅
│   ├── ring_buffer_store.py      ✅
│   ├── test_ring_buffer_store.py ✅
│   ├── stream_processor.py       ✅  ← Fase 3 completada
│   └── test_stream_processor.py  ✅
├── mqtt/
│   ├── mqtt_coordinator.py       ✅  (sin cambios en Fase 4)
│   ├── event_extractor.py        🔲  ← MODIFICAR en Fase 4
│   └── test_event_extractor.py   ✅  (actualizar tests)
├── mseed/
│   ├── binary_to_mseed.py        ✅  (sin cambios)
│   └── extract_segment.py        ✅  (sin cambios)
└── structured_logger.py          ✅  (sin cambios)
```

---

## Documentación Técnica de Referencia

- **Ring Buffer (Fase 3)**: `docs/context/stream_processor_context.md`
- **MQTT y extracción**: `docs/context/mqtt_coordinator_context.md`
- **Extracción de segmentos**: `docs/context/extract_segment_context.md`
- **Conversión miniSEED**: `docs/context/binary_to_mseed_context.md`
- **Restricción SSHFS**: No ejecutar comandos autónomos en rutas bajo `montajes/**`. Delegar al usuario con el comando exacto.
- **Commits**: No ejecutar commits. Mostrar el texto en formato `tipo: descripción` (minúsculas).

---

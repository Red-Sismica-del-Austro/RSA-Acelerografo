# Contexto Técnico: stream_processor.py

**Archivo:** `scripts/operation/streaming/stream_processor.py`  
**Módulo:** `streaming.stream_processor`  
**Fase:** 3 del Plan de Implementación Ring Buffer  
**Fecha de creación:** 2026-06-17

---

## Propósito

Daemon que lee tramas de 2506 bytes desde el named pipe `/tmp/my_pipe` y las almacena en el `RingBufferStore` de forma continua. Actúa como puente entre el programa C `registro_continuo_4.5.0.c` (productor) y el ring buffer en disco (consumidor).

---

## Dependencias

| Módulo | Función |
|--------|---------|
| `streaming.ring_buffer_store.RingBufferStore` | Almacén rotativo en disco |
| `core.frame_decoder.decode_timestamp` | Validación del timestamp de cada trama |
| `core.frame_decoder.FRAME_SIZE` | Constante: 2506 bytes por trama |

No tiene dependencias externas adicionales más allá de la biblioteca estándar de Python.

---

## Comportamiento del Named Pipe

El programa C abre el pipe con `O_WRONLY | O_NONBLOCK` y cierra el fd tras cada trama. Para evitar el ciclo EOF/SIGPIPE que esto genera en el lector, el `StreamProcessor` abre el pipe con **`os.O_RDWR`** ("Opción B"):

- El proceso mismo mantiene el extremo de escritura abierto.
- El fd nunca recibe EOF aunque el escritor C cierre.
- No es necesario reabrir el pipe entre tramas.

---

## Flujo de Procesamiento

```
registro_continuo.c
    │ escribe 2506 bytes (O_WRONLY | O_NONBLOCK)
    ▼
/tmp/my_pipe  ←──────── StreamProcessor._fd (O_RDWR)
    │
    ▼
_acumulador (bytearray)  ← maneja lecturas parciales
    │ cuando len >= FRAME_SIZE
    ▼
_procesar_trama(raw_frame)
    ├── decode_timestamp() → ValueError → descarta + warning
    └── ring_store.write_frame(raw_frame, timestamp) → archivo .bin
```

---

## Clase Principal: `StreamProcessor`

### Constructor

```python
StreamProcessor(
    pipe_path="/tmp/my_pipe",          # Ruta al FIFO
    buffer_dir="/home/rsa/data/ring-buffer/",
    max_size_mb=500,
    archivo_duracion_s=300,
    usar_fecha_filename=True,          # Mitiga bug de fecha del dsPIC
    dry_run=False,                     # Si True: cuenta tramas sin escribir
    logger=None,
)
```

### Métodos públicos

| Método | Descripción |
|--------|-------------|
| `run()` | Inicia el daemon. Bloquea hasta SIGTERM/SIGINT o error fatal. |
| `stop()` | Solicita parada ordenada. Thread-safe. |

### Atributos de estadísticas (solo lectura)

| Atributo | Descripción |
|----------|-------------|
| `frames_procesados` | Tramas escritas exitosamente al ring buffer |
| `frames_invalidos` | Tramas descartadas por timestamp inválido |
| `frames_error` | Tramas con error de escritura al ring buffer |

---

## Manejo de Señales

| Señal | Comportamiento |
|-------|---------------|
| `SIGTERM` | Llama `stop()` → cierre limpio (ring buffer + pipe) |
| `SIGINT` | Ídem que SIGTERM |

---

## Lecturas Parciales (Acumulador)

`os.read()` puede retornar menos bytes que `FRAME_SIZE` en una sola llamada. El `StreamProcessor` mantiene un `bytearray` interno que acumula chunks hasta completar exactamente 2506 bytes antes de procesar una trama.

---

## Modo `--dry-run`

En modo `dry_run=True`, el processor:
- Lee del pipe normalmente.
- Valida el timestamp de cada trama.
- **No** instancia ni escribe al `RingBufferStore`.
- Log de cada trama válida a nivel `DEBUG`.

Útil para verificar que el pipe recibe datos sin afectar el ring buffer de producción.

---

## Punto de Entrada CLI

```bash
# Modo normal (producción):
$PROJECT_LOCAL_ROOT/.venv/bin/python3 \
    scripts/operation/streaming/stream_processor.py

# Con parámetros explícitos:
python3 stream_processor.py \
    --pipe /tmp/my_pipe \
    --buffer-dir /home/rsa/data/ring-buffer/ \
    --max-size-mb 500 \
    --duracion-archivo 300

# Diagnóstico (sin escribir al disco):
python3 stream_processor.py --dry-run --verbose
```

---

## Configuración de Log

| Parámetro | Valor |
|-----------|-------|
| Archivo | `$PROJECT_LOCAL_ROOT/log-files/stream_processor.log` |
| Fallback | `/tmp/rsa-stream_processor.log` |
| Rotación | 5 MB, máx. 3 backups |

### Tags de log

| Tag | Nivel | Descripción |
|-----|-------|-------------|
| `[STREAM_START]` | INFO | Inicio del daemon |
| `[STREAM_LOOP]` | INFO | Inicio/fin del bucle de lectura |
| `[STREAM_PROGRESS]` | INFO | Resumen cada 300 tramas (~5 min) |
| `[STREAM_TIMEOUT]` | WARNING | Sin datos por >10 segundos |
| `[STREAM_SIGNAL]` | INFO | Señal SIGTERM/SIGINT recibida |
| `[STREAM_EXIT]` | INFO | Estadísticas finales al cierre |
| `[PIPE_OPEN]` | INFO | Pipe abierto con éxito |
| `[PIPE_CLOSE]` | INFO | Pipe cerrado |
| `[PIPE_READ_ERROR]` | ERROR | Error de lectura del pipe |
| `[FRAME_INVALID]` | WARNING | Trama descartada por timestamp inválido |
| `[FRAME_WRITE_ERROR]` | ERROR | Error escribiendo al ring buffer |
| `[RING_CLOSE]` | INFO | Ring buffer cerrado limpiamente |
| `[DRY_RUN]` | DEBUG | Trama válida en modo dry_run |

---

## Tests

**Archivo:** `scripts/operation/streaming/test_stream_processor.py`

```bash
cd /home/rsa/git/montajes/acelerografo-DEV00
python3 scripts/operation/streaming/test_stream_processor.py
```

### Grupos de tests

| Grupo | Tests |
|-------|-------|
| Inicialización y argumentos | 2 |
| Apertura del pipe | 2 |
| Procesamiento de tramas individuales | 3 |
| Acumulación de lecturas parciales | 2 |
| Flujo completo con FIFO real (dry_run) | 3 |
| Flujo completo con RingBufferStore real | 1 |
| Señales y cierre limpio | 3 |
| Estadísticas | 2 |

**Total: 18 tests**

---

## Integración con el Sistema

### Relación con otras fases

```
Fase 1: frame_decoder.py    ←── StreamProcessor usa decode_timestamp()
Fase 2: ring_buffer_store.py ←── StreamProcessor usa write_frame()
Fase 3: stream_processor.py  ← ESTE MÓDULO
Fase 4: event_extractor.py   ──→ usará ring_buffer_store.query_raw()
```

### Uso en producción

El daemon debe iniciarse vía `Supervisor` o un script de sistema en la Raspberry Pi. El flujo de despliegue sigue el procedimiento estándar del proyecto:

1. `git pull` en el repositorio
2. `bash menu.sh` → Opción 3 (Actualizar)
3. Reiniciar el servicio stream_processor si estaba corriendo

> ⚠️ **Restricción SSHFS**: No ejecutar el daemon directamente desde la ruta `montajes/`. Los comandos deben ejecutarse en la Raspberry Pi dentro de `$PROJECT_LOCAL_ROOT`.

# Resumen de Sesión: Implementación del Worker de Inferencia GPD en Tiempo Real (Fase 3)

**Fecha**: 2026-07-02  
**Repositorio**: `acelerografo-DEV00`  
**Agente de IA**: Antigravity  
**Usuario**: Milton  

---

## 🎯 Objetivo de la Sesión

El objetivo de la sesión fue implementar la **Fase 3 del Plan de Inferencia GPD en Tiempo Real**: el daemon `gpd_stream_worker.py`, que consume tramas desde la memoria compartida (`/dev/shm/`), las resamplea, acumula un buffer deslizante de 8 segundos, ejecuta el modelo TFLite con stride de 1 s y publica detecciones de fases P/S vía MQTT. Se acompañó la implementación con su suite de tests unitarios (29 tests, todos en verde), la actualización del template de configuración JSON, el contexto técnico del componente, y el ADR-010 documentando las decisiones de diseño.

---

## 📂 Estructura del Repositorio Implementada

Archivos creados y modificados durante la sesión:

```text
montajes/acelerografo-DEV00/
├── configuration/
│   └── configuracion_dispositivo.json.template  (MODIFICADO — sección streaming.gpd añadida)
├── docs/
│   ├── adr/
│   │   └── 010_pipeline_inferencia_gpd_streaming_stride_buffer_cooldown.md  (COPIADO MANUALMENTE por el usuario)
│   ├── context/
│   │   └── gpd_stream_worker_context.md  (NUEVO)
│   └── progress/
│       └── 2026-07-02_contexto-agente.md  (NUEVO — este archivo)
└── scripts/
    └── operation/
        └── streaming/
            ├── gpd_stream_worker.py      (NUEVO — Fase 3)
            └── test_gpd_stream_worker.py (NUEVO — 29 tests en verde)
```

Y en el repositorio externo `RSA-Metodologias`:

```text
rsa/RSA-Metodologias/
├── decisiones/
│   └── 010_pipeline_inferencia_gpd_streaming_stride_buffer_cooldown.md  (NUEVO)
└── indice/
    └── indice_tematico.md  (MODIFICADO — entrada gpd_stream_worker_context.md, ADR-010 y sesión 2026-07-02)
```

---

## ⚙️ Configuración del Entorno Virtual (`.venv`)

- **Ubicación en producción**: `/home/rsa/projects/acelerografo-rsa/.venv/`
- **Dependencias requeridas por la Fase 3** (ya presentes en `requirements.txt`):
  - `tflite-runtime`: carga e invoca el modelo `gpd.tflite`
  - `paho-mqtt`: publica detecciones en el broker MQTT
  - `numpy`: operaciones con el buffer circular y tensores
  - `scipy`: downsampling polifásico y filtrado (ya en uso desde la Fase 2)
- **Importaciones condicionales**: `tflite_runtime` y `paho-mqtt` se importan con `try/except`; el worker continúa en modo degradado si no están disponibles (útil para tests unitarios sin el runtime).

---

## 🛠️ Modificaciones de Código y Refactorización

### 1. Nuevo: `streaming/gpd_stream_worker.py` (726 líneas)

**Pipeline completo de inferencia en tiempo real**:

```
SharedMemoryReader (polling seq_number)
    → resample_frame() 250 Hz → 100 Hz  → (100, 3) float64
    → deque(maxlen=8)  [buffer de 8 tramas = 800 muestras = 8 s]
    → prepare_window(800 muestras)      → filtro Butterworth 3-20 Hz
                                         + extracción central [200:600]
                                         + normalización per-channel
                                        → (1, 400, 3) float32
    → TFLite invoke()                   → (3,) [noise, P, S]
    → evaluar umbral + cooldown
    → publish MQTT <station_id>/events/detected  QoS=1
```

**Decisiones de diseño críticas implementadas**:

| Parámetro | Valor | Fuente |
|-----------|-------|--------|
| Stride de inferencia | 1 s (1 inferencia/trama) | Configurable / defecto fijo |
| Buffer de señal | 800 muestras = 8 s (Opción A con padding) | Fijo en el código |
| Extracción ventana central | `[200:600]` de las 800 muestras | `SignalPreprocessor.prepare_window()` |
| `umbral_p` | 0.95 | `configuracion_dispositivo.json` — `streaming.gpd.umbral_p` |
| `umbral_s` | 0.95 | `configuracion_dispositivo.json` — `streaming.gpd.umbral_s` |
| `cooldown_s` | 30 s | `configuracion_dispositivo.json` — `streaming.gpd.cooldown_s` |
| Modelo TFLite | `models/gpd.tflite` | `configuracion_dispositivo.json` — `streaming.gpd.modelo_ruta` |
| Hilos TFLite | 2 | `configuracion_dispositivo.json` — `streaming.gpd.tflite_threads` (opcional) |
| Retry SHM arranque | Backoff exponencial 0.5→8 s, máx. 30 s | Constante `_DEFAULT_SHM_RETRY_MAX` |
| Poll sleep sin trama | 10 ms | Constante `_DEFAULT_POLL_SLEEP_S` |
| Stats periódicas | cada 100 inferencias | Constante `_DEFAULT_STATS_INTERVAL` |

**Comportamiento ante fallos**:
- Si `stream_processor` no ha arrancado al iniciar el worker: retry con backoff exponencial. Tras 30 s de timeout, el worker termina limpiamente sin propagar excepción al exterior (lo que permite que Supervisor lo reinicie con `startretries`).
- Si el SHM desaparece en mitad del bucle (reinicio de `stream_processor`): warning + re-apertura con retry.
- Si el broker MQTT no está disponible: las detecciones se loguean localmente (`[GPD_DETECTION_LOG]`) y el worker continúa.

**Payload MQTT publicado** en `<station_id>/events/detected` (QoS=1):
```json
{
    "type": "P",
    "probability": 0.9723,
    "timestamp": "2026-07-02T15:30:00.000Z",
    "window_start": "2026-07-02T15:29:58.000Z",
    "window_end": "2026-07-02T15:30:02.000Z",
    "station_id": "DEV00",
    "model": "gpd.tflite",
    "source": "streaming"
}
```

> **NOTA CRÍTICA para la Fase 4**: El campo `timestamp` es el **centro de la ventana de inferencia de 4 s** (no el momento de publicación). Se calcula como `timestamp_trama_mas_reciente - 2.0 s`. El `mqtt_coordinator` debe usar este campo para calcular `start = timestamp - ventana_pre_evento_s`.

**Tags de log estructurado** (`[GPD_INIT]`, `[GPD_LOAD]`, `[GPD_SHM_OK]`, `[GPD_SHM_WAIT]`, `[GPD_SHM_FAIL]`, `[GPD_START]`, `[GPD_BUF]`, `[GPD_INFER]`, `[GPD_STATS]`, `[GPD_DETECTION]`, `[GPD_COOLDOWN]`, `[GPD_MQTT_PUB]`, `[GPD_STATS_FINAL]`, `[GPD_SIGNAL]`, `[GPD_STOP]`).

**Entry point como script**:
```
python3 gpd_stream_worker.py [--config <ruta>] [--station <id>] [--log-dir <dir>]
```
Lee la sección `streaming.gpd` del JSON de configuración. Propaga `station_id` y parámetros MQTT (`broker`, `port`) desde las secciones hermanas del JSON.

### 2. Nuevo: `streaming/test_gpd_stream_worker.py` (29 tests — todos en verde)

Suite organizada en 7 clases:

| Clase | Tests | Qué verifica |
|-------|-------|-------------|
| `TestSignalPreprocessorIntegration` | 4 | Resample, buffer (800, 3), `prepare_window` shape y normalización |
| `TestGPDInferencia` | 3 | Shape `(3,)`, rango `[0,1]`, error sin intérprete |
| `TestCooldown` | 6 | Primera detección, cooldown activo, expiración, umbral no alcanzado, prioridad P/S, contadores |
| `TestPayloadDeteccion` | 6 | Campos requeridos, `station_id`, `model`, `source`, ISO 8601, JSON serializable |
| `TestBufferCircular` | 3 | maxlen=8, shape (800,3), buffer incompleto no infiere |
| `TestArranqueParada` | 4 | `stop()`, estado inicial, buffer vacío, `run()` sin SHM termina limpiamente |
| `TestPublicacionMQTT` | 2 | Tópico correcto, sin MQTT no lanza excepción |

Bug corregido durante la sesión: el `RuntimeError` de `_abrir_shm_con_retry()` en el arranque inicial no estaba capturado en `run()`. Se captura ahora explícitamente, permitiendo que el worker siempre termine sin propagar excepciones al exterior.

### 3. Modificado: `configuration/configuracion_dispositivo.json.template`

Se añadió la sección `streaming.gpd` con todos los parámetros configurables:

```json
"gpd": {
    "habilitado": true,
    "modelo_ruta": "models/gpd.tflite",
    "umbral_p": 0.95,
    "umbral_s": 0.95,
    "cooldown_s": 30,
    "ventana_pre_evento_s": 60,
    "ventana_post_evento_s": 60,
    "auto_extract": true,
    "auto_upload": true,
    "filtro": {
        "habilitado": true,
        "freq_min_hz": 3.0,
        "freq_max_hz": 20.0
    }
}
```

> **Acción pendiente para el usuario**: Copiar estos campos al archivo de producción en el dispositivo: `/home/rsa/projects/acelerografo/configuracion/configuracion_dispositivo.json`

### 4. Nuevo: `docs/context/gpd_stream_worker_context.md`

Contexto técnico completo del worker, incluyendo diagramas Mermaid del pipeline y de la secuencia de arranque, tabla de configuraciones, tabla de métodos y sus responsabilidades, formato del payload MQTT y limitaciones conocidas.

### 5. Nuevo: `docs/adr/010_pipeline_inferencia_gpd_streaming_stride_buffer_cooldown.md`

ADR-010 copiado manualmente por el usuario desde `rsa/RSA-Metodologias/decisiones/`. Documenta las cuatro decisiones de diseño de la Fase 3: stride de inferencia (1 s), buffer de padding (8 s, Opción A), umbrales configurables (0.95) y cooldown anti-spam configurable (30 s).

---

## 📋 Pasos Sugeridos para el Siguiente Agente

El siguiente agente debe continuar con la **Fase 4: Extracción Automática por Detección GPD**. Lee primero:
- El plan de implementación: `docs/blueprints/2026-06-18_plan_inferencia_gpd_tiempo_real.md` (sección Fase 4, líneas 663-801)
- El contexto del coordinador MQTT: `docs/context/mqtt_coordinator_context.md`
- El contexto del extractor de eventos: `docs/context/event_extractor_context.md`

### Fase 4: Modificar `mqtt/mqtt_coordinator.py`

1. **Suscripción a detecciones propias**: Agregar `events_local` a las suscripciones en `configuracion_mqtt.json.template`. El coordinador ya tiene una suscripción wildcard `+/events/detected`, pero su handler en `on_message()` excluye actualmente las detecciones propias (`config["id"] not in topic`).

2. **Nueva rama en `on_message()`**: Añadir una condición que capture el tópico `<station_id>/events/detected` cuando el `station_id` coincide con el propio dispositivo:
   ```python
   elif "/events/detected" in topic and config["id"] in topic:
       _manejar_deteccion_gpd_local(client, userdata, payload)
   ```

3. **Nueva función `_manejar_deteccion_gpd_local()`**:
   - Validar el payload: debe tener `type`, `timestamp` y `probability`.
   - Calcular ventana de extracción:
     - `start = datetime.fromisoformat(payload["timestamp"]) - timedelta(seconds=config["ventana_pre_evento_s"])`
     - `duration = config["ventana_pre_evento_s"] + config["ventana_post_evento_s"]`
   - Verificar `auto_extract` en la config GPD. Si es `false`, solo loguear.
   - Invocar `extraer_y_subir_evento()` **en un hilo separado** (igual que `_cmd_extract_event`).
   - Publicar resultado en `cmd/extract_event/res` con `request_id = f"gpd-auto-{payload['timestamp']}"`.

4. **Parámetros de extracción**: Se leen de `streaming.gpd` del JSON del dispositivo:
   - `ventana_pre_evento_s` (default: 60)
   - `ventana_post_evento_s` (default: 60)
   - `auto_extract` (default: true)
   - `auto_upload` (default: true)

5. **Tests**: Crear `mqtt/test_mqtt_coordinator_gpd.py` (o ampliar `test_mqtt_coordinator.py`) con:
   - `test_auto_extract_trigger`: detección local → se invoca `extraer_y_subir_evento()` con parámetros correctos.
   - `test_auto_extract_disabled`: con `auto_extract=false`, no se extrae.
   - `test_payload_invalido`: payload sin `timestamp` o sin `type` → log warning, sin extracción.

### Fase 5 (para después de la Fase 4)

- Agregar la configuración de Supervisor en `scripts/task/gpd_worker.conf`.
- Integrar el registro en `scripts/setup/update.sh` para copiar `gpd_worker.conf` y el modelo.
- Conectar `StructuredLogger` al worker GPD: los métodos `gpd_load()`, `gpd_inference()`, `gpd_detection()` y `gpd_cooldown()` ya están definidos en `structured_logger.py`, pero el worker aún usa `logging.Logger` estándar.

### Acciones manuales pendientes para el usuario (restricción SSHFS)

- Copiar la sección `streaming.gpd` al JSON de producción en el dispositivo.
- Copiar el modelo `gpd.tflite` al directorio `models/` del proyecto en producción.
- Verificar que `tflite-runtime` y `paho-mqtt` estén instalados en el `.venv` de producción.
- Ejecutar los tests en producción: `python3 -m pytest test_gpd_stream_worker.py -v`

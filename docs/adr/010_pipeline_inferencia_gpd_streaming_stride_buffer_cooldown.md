---
id: ADR-010
titulo: pipeline_inferencia_gpd_streaming_stride_buffer_cooldown
estado: Aceptado
fecha: 2026-07-02
temas: [gpd, inferencia, streaming, tflite, deteccion_sismica, mqtt]
entorno: acelerografo-DEV00
---

# ADR-010: Parámetros del Pipeline de Inferencia GPD en Streaming

## Estado

**Aceptado** | Fecha: 2026-07-02

## Contexto

La Fase 3 del plan de inferencia GPD en tiempo real requirió tomar cuatro decisiones
de diseño interrelacionadas que definen el comportamiento del daemon `gpd_stream_worker.py`
en la Raspberry Pi 3B+ de producción:

1. **Stride de inferencia**: con qué frecuencia ejecutar el modelo TFLite.
2. **Estrategia del buffer de señal**: cómo acumular y filtrar datos para evitar artefactos.
3. **Umbrales de detección**: qué probabilidad mínima debe superar el modelo para disparar una alerta.
4. **Cooldown anti-spam**: cuánto tiempo suprimir detecciones repetidas del mismo evento.

El contexto hardware es restrictivo: la RPi 3B+ dispone de 1 GB de RAM y 4 núcleos ARM
a 1.2 GHz sin unidad de punto flotante dedicada. El modelo `gpd.tflite` tarda ~50 ms por
inferencia con 2 hilos. El stream de datos llega a 1 trama/segundo (250 muestras crudas = 1 s).

---

## Decisión 1: Stride de Inferencia

### Opciones Evaluadas

#### Opción A: Stride de 0.1 s (10 inferencias/segundo)
- **Ventajas:** Máxima resolución temporal; detecta el onset de la onda P con precisión < 100 ms.
- **Desventajas:** Requiere interpolar entre tramas para generar muestras intermedias. Con ~50 ms de inferencia, genera 10 × 50 ms = 500 ms de CPU/s solo en TFLite, saturando el núcleo. Incompatible con la restricción de < 15% CPU en RPi.

#### Opción B: Stride de 1 segundo (1 inferencia/segundo) ✅ Seleccionada
- **Ventajas:** Se alinea naturalmente con la tasa de llegada de tramas (1 trama/s). No requiere interpolación. Consumo de CPU < 5% (50 ms/1000 ms). Suficiente para detección sísmica (los terremotos duran > 1 s).
- **Desventajas:** Resolución temporal de ±1 s en el timestamp de detección (mitigado por el cálculo del centro de ventana en el payload MQTT).

#### Opción C: Stride de 0.5 s (2 inferencias/segundo)
- **Ventajas:** Compromiso entre resolución y consumo.
- **Desventajas:** Requiere acumulación parcial de tramas (50 muestras intermedias). Mayor complejidad sin beneficio operativo significativo para detección de eventos regionales.

### Decisión

Se eligió la **Opción B** (stride de 1 segundo). El stride coincide con la periodicidad
natural del pipe de datos, simplifica el código y mantiene el consumo de CPU dentro del
presupuesto de la RPi 3B+.

---

## Decisión 2: Estrategia del Buffer de Señal (Padding para Filtrado)

### Contexto específico

El filtro Butterworth pasabanda (3-20 Hz, orden 4, `sosfiltfilt`) introduce transitorios
en los extremos de cualquier ventana de señal finita. Aplicar el filtro directamente sobre
una ventana de 4 s (400 muestras a 100 Hz) contamina el onset de la onda que se quiere detectar.

### Opciones Evaluadas

#### Opción A: Buffer de 8 s con extracción central ✅ Seleccionada
- Se acumulan 800 muestras (8 s) en un `deque(maxlen=8)`.
- Se filtra el bloque completo y se extraen las 400 muestras centrales (segundos 2-6).
- Los transitorios de borde quedan en los 2 s iniciales y los 2 s finales, fuera de la ventana de inferencia.
- **Ventajas:** Eliminación completa de artefactos de borde; no aumenta la latencia observable (el buffer se llena en los primeros 8 s de arranque).
- **Desventajas:** Requiere 2× la RAM del buffer de inferencia (~19 KB adicionales, despreciable).

#### Opción B: Sin filtrado en streaming
- Se pasa la señal cruda directamente al modelo TFLite.
- **Ventajas:** Simplicidad máxima, sin costo de CPU para filtrado.
- **Desventajas:** El modelo GPD fue entrenado con señales filtradas en 1-45 Hz. Sin filtrado, las frecuencias de red eléctrica (60 Hz, aunque atenuadas) y el ruido DC pueden degradar la precisión del clasificador.

#### Opción C: Filtrado sobre el buffer acumulado de 4 s
- Filtrar las 400 muestras directamente en cada ciclo.
- **Ventajas:** Reduce la RAM de buffer a la mitad.
- **Desventajas:** Introduce artefactos de borde en la ventana de inferencia. Probabilidad de falsos negativos en eventos con onset en los extremos de la ventana.

### Decisión

Se eligió la **Opción A** (buffer de 8 s con extracción central). Es la misma estrategia
documentada en el [signal_preprocessor_context.md](https://github.com/RedSismicaAustro/RSA-Acelerografo/blob/main/docs/context/signal_preprocessor_context.md)
y está alineada con la función `prepare_window()` del `SignalPreprocessor`.

---

## Decisión 3: Umbrales de Probabilidad de Detección

### Opciones Evaluadas

#### Opción A: Umbral fijo de 0.95 para P y S
- Equivalente al umbral del script batch de referencia (`gpd_tflite_inference_chunked.py`).
- **Ventajas:** Minimiza falsos positivos (extracciones innecesarias de 120 s de datos).
- **Desventajas:** Puede perder eventos pequeños (M < 2.0) a mayor distancia epicentral.

#### Opción B: Umbral diferenciado (umbral_p = 0.80, umbral_s = 0.95)
- **Ventajas:** Mayor sensibilidad a la onda P (más ruidosa en acelerógrafos).
- **Desventajas:** Más falsos positivos en el tópico `events/detected`, afectando el `mqtt_coordinator`.

#### Opción C: Totalmente configurable desde JSON ✅ Seleccionada
- `umbral_p` y `umbral_s` se leen de `streaming.gpd` en `configuracion_dispositivo.json`.
- Valores iniciales: `umbral_p = 0.95`, `umbral_s = 0.95` (equivalente a la Opción A).
- **Ventajas:** Permite ajustar los umbrales sin redeployar código, adaptándose a la
  sismicidad local del sitio de instalación.
- **Desventajas:** Requiere disciplina operativa para no bajar los umbrales excesivamente.

### Decisión

Se eligió la **Opción C** con valores iniciales de 0.95 para ambas fases. La configurabilidad
desde JSON permite calibración en producción sin modificar código, lo que es esencial para
una red de monitoreo en desarrollo activo.

---

## Decisión 4: Cooldown Anti-Spam entre Detecciones

### Contexto específico

Un terremoto moderado puede sostener probabilidades P/S > 0.95 durante 5-15 s consecutivos,
generando hasta 15 mensajes MQTT por evento. Cada mensaje dispararía una extracción automática
de 120 s de datos en la Fase 4, saturando el ring buffer y Google Drive.

### Opciones Evaluadas

#### Opción A: Cooldown fijo de 30 segundos ✅ Seleccionada
- **Ventajas:** Garantiza como máximo 2 detecciones/minuto. Cubre eventos de hasta 30 s de duración. Valor conservador bien establecido en sistemas de alerta temprana.
- **Desventajas:** Eventos de duración inusualmente larga (> 30 s de señal fuerte, e.g. M > 6.5) podrían generar una segunda detección espuria. Aceptable dado el contexto regional del Austro ecuatoriano.

#### Opción B: Cooldown configurable desde JSON ✅ También seleccionada
- Valor por defecto: 30 s, ajustable desde `streaming.gpd.cooldown_s`.
- **Ventajas:** Mismas que la Opción A, con flexibilidad para ajuste post-despliegue.
- **Desventajas:** Igual que la Opción A.

### Decisión

Se implementó **cooldown configurable desde JSON** con valor por defecto de 30 segundos.
Consistente con la filosofía de las Decisiones 3 (umbrales configurables).

> [!NOTE]
> El cooldown no persiste entre reinicios del daemon. Si Supervisor reinicia `gpd_stream_worker`,
> el temporizador de cooldown se reinicia a 0. En la práctica, Supervisor solo reinicia el
> worker si este crashea, lo cual es improbable durante un evento sísmico activo.

---

## Consecuencias

- **Positivas:**
  - El pipeline completo opera con < 5% de CPU en la RPi 3B+ (stride 1 s, 2 hilos TFLite).
  - Los umbrales y cooldown configurables permiten calibración sin redeployar.
  - El buffer de 8 s elimina artefactos de borde sin penalizar la latencia de detección.
  - El payload MQTT incluye `window_start`/`window_end` e`timestamp` del centro de ventana,
    lo que simplifica el cálculo de ventanas de extracción en la Fase 4.

- **Negativas / Deuda técnica:**
  - La latencia mínima de primera detección es de **8 s** desde el arranque del worker
    (tiempo de llenado del buffer). En producción continua esto es irrelevante, pero debe
    documentarse para diagnósticos post-evento.
  - El cooldown no persiste entre reinicios (ver nota anterior).
  - Los umbrales iniciales de 0.95 pueden ser demasiado conservadores para sismos locales
    de baja magnitud. Se recomienda revisar tras las primeras semanas en producción.

- **Trabajo futuro derivado:**
  - **Fase 4**: El `mqtt_coordinator` debe suscribirse a `<station_id>/events/detected`
    y usar `timestamp`, `ventana_pre_evento_s` y `ventana_post_evento_s` del payload y la
    configuración para invocar `extraer_y_subir_evento()`.
  - **Fase 5**: Conectar `StructuredLogger` al worker para emitir los métodos `gpd_load`,
    `gpd_inference`, `gpd_detection` y `gpd_cooldown` ya definidos en `structured_logger.py`.
  - Evaluar si un cooldown de 60 s sería más apropiado para eventos regionales con coda larga.

## Referencias

- Contexto técnico: [gpd_stream_worker_context.md](https://github.com/RedSismicaAustro/RSA-Acelerografo/blob/main/docs/context/gpd_stream_worker_context.md)
- Contexto relacionado: [signal_preprocessor_context.md](https://github.com/RedSismicaAustro/RSA-Acelerografo/blob/main/docs/context/signal_preprocessor_context.md)
- ADR relacionado: [ADR-009: Memoria Compartida Seqlock IPC Streaming](./009_memoria_compartida_seqlock_ipc_streaming.md)
- Plan de implementación: [docs/blueprints/2026-06-18_plan_inferencia_gpd_tiempo_real.md](https://github.com/RedSismicaAustro/RSA-Acelerografo/blob/main/docs/blueprints/2026-06-18_plan_inferencia_gpd_tiempo_real.md)

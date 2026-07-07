---
id: ADR-011
titulo: bifurcacion_online_offline_pipeline_gpd_postdeteccion
estado: Aceptado
fecha: 2026-07-07
temas: [gpd, deteccion_sismica, mqtt, streaming, fase4, arquitectura]
entorno: acelerografo-DEV00
---

# ADR-011: Bifurcación online/offline para el pipeline GPD post-detección

## Estado

**Aceptado** | Fecha: 2026-07-07

---

## Contexto

El worker de inferencia GPD (`gpd_stream_worker.py`) detecta fases sísmicas P/S en tiempo real. Una vez confirmada una detección, el sistema debe:

1. **Registrar el evento** para trazabilidad histórica.
2. **Extraer el segmento de señal** (ventana pre/post del evento) en formato MiniSEED.
3. **Sincronizar** la detección y extracción entre los distintos componentes del sistema.

El problema central es que el acelerógrafo opera en **dos contextos de conectividad radicalmente distintos**:

- **Online**: El dispositivo tiene acceso a internet (Tailscale VPN activa). El broker MQTT es alcanzable. Existe validación regional cruzando detecciones de otras estaciones.
- **Offline**: Sin acceso a internet (campo, corte de red). No hay broker MQTT. El dispositivo debe operar de forma completamente autónoma.

Diseñar un pipeline único que funcione en ambos contextos sin degradarse en ninguno de ellos requiere una **decisión explícita sobre dónde vive la lógica de extracción** y cómo se coordinan los dos procesos involucrados (`gpd_stream_worker` y `mqtt_coordinator`).

**Restricciones adicionales:**
- Ambos procesos corren en la misma Raspberry Pi 3B+ (recursos limitados).
- La extracción desde el ring buffer es una operación bloqueante de varios segundos.
- El loop MQTT no debe bloquearse bajo ninguna circunstancia.
- El registro del evento debe ser atómico y tolerante a fallos de proceso.

---

## Opciones Evaluadas

### Opción A: Coordinación exclusiva vía MQTT (solo online)

El worker siempre publica la detección en MQTT. El `mqtt_coordinator` es el único responsable de disparar la extracción.

- **Ventajas:**
  - Separación de responsabilidades clara: el worker detecta, el coordinador actúa.
  - Validación regional posible antes de extraer (evita falsas extracciones).
  - Un solo punto de control del pipeline de extracción.
- **Desventajas:**
  - **Fallo total en modo offline**: sin broker MQTT, el sistema no extrae nada aunque detecte eventos.
  - Crea una dependencia fuerte entre detección y conectividad de red.
  - No cumple el requisito de operación autónoma en campo.

### Opción B: Extracción directa siempre desde el worker (sin MQTT)

El worker detecta y extrae directamente en un hilo separado, ignorando el broker MQTT para la extracción.

- **Ventajas:**
  - Completamente autónomo, funciona sin red.
  - Lógica simple y auto-contenida en el worker.
- **Desventajas:**
  - **Imposible validación regional**: no hay mecanismo para correlacionar con otras estaciones antes de extraer.
  - El worker acumula responsabilidades (inferencia + extracción + gestión de archivos), violando el principio de responsabilidad única.
  - En modo online, la extracción ocurre independientemente de si el coordinador también la disparó → potencial duplicación de archivos MiniSEED.

### Opción C: Bifurcación por `modo_adquisicion` (ELEGIDA)

El sistema lee un flag de configuración (`dispositivo.modo_adquisicion`) y bifurca el comportamiento post-detección:

- **Online** → El worker registra en CSV (`confirmado=False`) y publica la detección en MQTT. El `mqtt_coordinator` recibe la detección (suscrito a `{id}/events/detected`), lanza la extracción en hilo separado, y actualiza el CSV (`confirmado=True`).
- **Offline** → El worker registra en CSV (`confirmado=False`) y lanza la extracción directamente en un hilo daemon. Al completar, actualiza el CSV (`confirmado=True`) sin pasar por MQTT.

- **Ventajas:**
  - Opera correctamente en ambos contextos con la misma base de código.
  - El CSV mensual (`EventLogger`) actúa como estado compartido thread-safe, garantizando trazabilidad en ambos modos.
  - En modo online se preserva la oportunidad de validación regional (el coordinador puede imponer lógica adicional antes de extraer).
  - La extracción siempre ocurre en hilos separados (daemon), nunca bloquea el bucle de inferencia ni el loop MQTT.
  - Si `event_extractor` no está disponible (ImportError), el modo offline degrada graciosamente con un warning, sin crash.
- **Desventajas:**
  - Mayor complejidad en el worker (importación condicional de `event_extractor`).
  - El CSV es un estado compartido entre dos procesos: requiere serialización mediante `threading.Lock`.
  - Condición de carrera improbable pero posible: el coordinador podría intentar `actualizar_confirmacion()` antes de que el worker complete `registrar_deteccion()`. Mitigado con fallback en el coordinador.

---

## Decisión

Se eligió la **Opción C (Bifurcación por `modo_adquisicion`)** porque es la única que satisface simultáneamente los requisitos de operación autónoma en campo y validación regional cuando hay conectividad.

La condición de carrera identificada es estadísticamente improbable (el worker escribe en CSV sincrónicamente antes de publicar en MQTT, y el coordinador tarda varios segundos en extraer), pero se implementó un fallback explícito en `_run_gpd_extraction_pipeline()`: si `actualizar_confirmacion()` retorna `False`, se llama directamente a `registrar_deteccion(confirmado=True)` para no perder el registro del evento.

---

## Consecuencias

**Positivas:**
- El sistema es operacionalmente resiliente: funciona en campo sin red y en red con validación regional.
- El CSV mensual es la fuente de verdad del estado de todas las detecciones, independientemente del modo.
- El flag `modo_adquisicion` es el único punto de configuración para cambiar el comportamiento: un cambio en `configuracion_dispositivo.json` es suficiente para alternar modos sin redeployar código.

**Negativas / Deuda técnica:**
- En modo offline, la validación regional no ocurre. Las extracciones son unilaterales.
- La búsqueda en `actualizar_confirmacion()` es O(n) lineal sobre el CSV del mes. Con un cooldown de 30 s, el volumen mensual es bajo (< 3000 filas), pero si se reduce el cooldown o se añaden más estaciones, podría requerir indexación.
- El `mqtt_coordinator` ahora tiene una dependencia implícita en `configuracion_dispositivo.json` (para leer `modo_adquisicion` y los parámetros GPD). Si este archivo no existe en el dispositivo, opera con defaults seguros pero sin conocimiento del modo configurado.

**Trabajo futuro derivado:**
- Fase 5: Conectar `gpd_stream_worker` con `StructuredLogger` en lugar de `logging.Logger` estándar, para usar los métodos semánticos GPD (`gpd_detection`, `gpd_load`, etc.) ya definidos.
- Considerar una base de datos SQLite ligera como reemplazo del CSV si el volumen de detecciones aumenta significativamente.
- Implementar un mecanismo de sincronización de CSVs cuando el dispositivo pasa de offline a online (reconciliación de registros no confirmados).

---

## Referencias

- Blueprint de arquitectura: `montajes/acelerografo-DEV00/docs/blueprints/2026-07-06_arquitectura_flujo_gpd_online_offline.md`
- Plan de implementación: `montajes/acelerografo-DEV00/docs/blueprints/2026-07-06_plan_implementacion_fase4_gpd.md`
- Sesión de origen: `montajes/acelerografo-DEV00/docs/progress/2026-07-07_contexto-agente.md`
- Contexto técnico worker: `montajes/acelerografo-DEV00/docs/context/gpd_stream_worker_context.md`
- Contexto técnico coordinador: `montajes/acelerografo-DEV00/docs/context/mqtt_coordinator_context.md`
- Contexto técnico logger CSV: `montajes/acelerografo-DEV00/docs/context/event_logger_context.md`
- ADR relacionada: `decisiones/010_pipeline_inferencia_gpd_streaming_stride_buffer_cooldown.md`

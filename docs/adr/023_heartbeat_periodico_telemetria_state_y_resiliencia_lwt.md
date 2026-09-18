---
id: ADR-023
titulo: Latido Periódico (Heartbeat) de Telemetría State con Preservación de Sesión y Resiliencia ante Desconexiones MQTT
estado: Aceptado
fecha: 2026-09-18
temas: [mqtt, telemetria, lwt, heartbeat, resiliencia, acelerografo, observabilidad]
entorno: acelerografo
---

# ADR-023: Latido Periódico (Heartbeat) de Telemetría State con Preservación de Sesión y Resiliencia ante Desconexiones MQTT

## Estado

**Aceptado** | Fecha: 2026-09-18

## Contexto

En las estaciones acelerográficas de la RSA, la supervisión del estado operacional en tiempo real se canaliza a través del tópico MQTT `rsa/seismic/smart/{id}/telemetry/state` con QoS 1 y bandera `retain=True`. Para detectar caídas intempestivas del enlace de red o fallas de alimentación en las estaciones de campo, el cliente Paho-MQTT en `mqtt_coordinator.py` configura un mensaje de última voluntad (**LWT - Last Will and Testament**) con el payload `{"status": "offline"}` y `retain=True`.

Sin embargo, durante la operación continua en campo se evidenció una anomalía crítica de observabilidad: ante parpadeos de red, jitter o reconexiones transitorias, el broker MQTT ejecuta una toma de control de sesión (*session takeover*) para cerrar el socket TCP huérfano previo. De acuerdo al estándar MQTT (v3.1.1 / v5.0), este cierre no gracioso dispara el LWT configurado para la sesión anterior (`offline` retenido). Si este evento es procesado por el broker de manera casi simultánea o milisegundos después del paquete entrante `online` enviado en el callback `on_connect()`, el broker fija `"offline"` como el último mensaje retenido.

Dado que la arquitectura original contemplaba la emisión de `telemetry/state` como un evento puramente reactivo mono-disparo (al conectar, al desconectar y un único refresco a las 00:00 UTC), la plataforma central de monitoreo quedaba reportando que la estación estaba `"offline"` durante horas (hasta 24 horas), a pesar de que la estación continuaba adquiriendo datos sísmicos y transmitiendo regularmente su salud de hardware (`telemetry/health`) y los tres tópicos de watchdog (`status/acquisition`, `status/sensor`, `status/drive`) cada 300 segundos.

## Opciones Evaluadas

### Opción A: Heartbeat Periódico (300 s) con Preservación del Timestamp de Sesión (`last_state_change`) [SELECCIONADA]
Incorporar la retransmisión periódica de `telemetry/state` (`"online"`, QoS 1, `retain=True`) en el bucle principal de `mqtt_coordinator.py` cada 300 segundos, sincronizada con la ráfaga de telemetría de salud y watchdogs. En cada latido, se reutiliza el timestamp exacto del inicio de la sesión activa (`last_state_change`), complementado con la priorización inmediata de `publicar_state("online")` en `on_connect()` antes de la ráfaga de suscripciones.
- **Ventajas:**
  - Erradica de forma definitiva los falsos estados `"offline"`: cualquier colisión de LWT se autocorrige en un tiempo máximo de 5 minutos (300 s).
  - Preserva la semántica de tiempo de actividad ininterrumpido (*uptime*), permitiendo a la plataforma central saber cuándo inició la conexión continua actual.
  - Mantiene el mensaje retenido fresco en el broker MQTT ante reinicios del broker.
  - Sobrecarga de red prácticamente nula (1 paquete cada 5 minutos).
- **Desventajas:**
  - El timestamp del payload no avanza cada 5 minutos (refleja el inicio de la sesión online actual, no la hora del latido).

### Opción B: Heartbeat Periódico con Timestamp Actual Dinámico (`now_ts`)
Similar a la Opción A, pero actualizando el timestamp del payload con la hora UTC actual en cada ciclo de 300 s.
- **Ventajas:**
  - Autocorrige el LWT en máx. 300 s.
  - Evidencia directa de la última confirmación de vida segundo a segundo.
- **Desventajas:**
  - Destruye la trazabilidad del inicio de la sesión online (uptime), dificultando auditorías de estabilidad de enlace y reseteando visualmente la duración de conexión en dashboards.

### Opción C: Reordenamiento Exclusivo en `on_connect()` con Retardo Preventivo
Modificar únicamente el callback `on_connect()` para emitir `online` antes de suscribirse a los tópicos, o introduciendo una pausa arbitraria (`sleep`).
- **Ventajas:**
  - No altera el bucle periódico de telemetría.
- **Desventajas:**
  - No proporciona autorrecuperación: si la colisión de LWT ocurre por retrasos en el broker o si la red vuelve a tambalearse, la estación permanece `"offline"` hasta las 00:00 UTC. Mantiene la fragilidad del diseño mono-disparo.

## Decisión

Se eligió la **Opción A** porque proporciona una solución resiliente y determinista de autorrecuperación ante condiciones de carrera en el broker sin sacrificar la semántica de tiempo de actividad de la sesión.

Específicamente:
1. **Priorización en `on_connect()`**: Al recibir confirmación de conexión (`rc == 0`), se actualiza `userdata["is_connected"] = True`, se fija `userdata["last_state_change"] = now_ts` y se publica inmediatamente `telemetry/state` con `"online"`, antes de la ráfaga de suscripciones a los 5 tópicos de comandos y eventos.
2. **Latido Periódico Cada 300 Segundos**: En el loop principal de `mqtt_coordinator.py`, acoplado al intervalo `HEALTH_INTERVAL = 300`, si el cliente está conectado (`client.is_connected()`), se re-publica `telemetry/state` con `"online"`, QoS 1, `retain=True` y `timestamp_override=userdata["last_state_change"]`.
3. **Manejo de Desconexión**: En `on_disconnect()`, se actualiza `userdata["is_connected"] = False`, impidiendo emisiones espurias de latido mientras se restablece el enlace.

## Consecuencias

### Consecuencias Positivas
- **Eliminación de Falsas Alarmas**: La plataforma de monitoreo no mantendrá reportes erróneos de fuera de servicio; cualquier desfase de retención se repara automáticamente en menos de 5 minutos.
- **Observabilidad Consistente**: Se alinea la cadencia de refresco del estado general con los tópicos de salud (`telemetry/health`) y diagnóstico (`status/*`).
- **Preservación de Uptime**: Los sistemas aguas arriba (Grafana, bases de datos o dashboards) conservan la marca de tiempo original del establecimiento del enlace para calcular métricas de disponibilidad de red.
- **Cero Dependencias Adicionales**: Implementado exclusivamente con la biblioteca `paho-mqtt` nativa del entorno virtual.

### Consecuencias Negativas o Deuda Técnica
- Durante un corte genuino de red, el broker publicará el LWT `"offline"`. Al regresar el enlace, si se produjera una carrera de brokers, el falso `"offline"` podría subsistir durante un intervalo de hasta 300 segundos antes del latido corrector. Este comportamiento es admisible y se encuentra dentro de los umbrales de tolerancia de la RSA.

## Referencias

- Diagnóstico técnico de origen: [`docs/analysis/2026-09-18_diagnostico_falsos_offline_telemetry_state.md`](../analysis/2026-09-18_diagnostico_falsos_offline_telemetry_state.md)
- Plan de implementación: [`docs/blueprints/2026-09-18_plan_heartbeat_telemetry_state.md`](../blueprints/2026-09-18_plan_heartbeat_telemetry_state.md)
- Contexto técnico relacionado: [`docs/context/mqtt_coordinator_context.md`](../context/mqtt_coordinator_context.md)
- Código fuente: [`scripts/operation/mqtt/mqtt_coordinator.py`](../../scripts/operation/mqtt/mqtt_coordinator.py)

---
proyecto: acelerografo-DEV00
tipo: diagnostico_tecnico
resolucion: en_proceso
temas: [mqtt, telemetria, lwt, heartbeat, resiliencia, monitoreo]
fecha: 2026-09-18
---

# Diagnóstico Técnico: Falsos Estados "Offline" por Pérdida de Transmisión de `telemetry/state` tras Reconexiones MQTT

**Fecha**: 2026-09-18  
**Proyecto / Repositorio**: `acelerografo-DEV00`  
**Componente(s) afectado(s)**: `scripts/operation/mqtt/mqtt_coordinator.py`  
**Estado**: Mitigado localmente  
**Severidad**: Alta (afecta la observabilidad operacional de la estación en la plataforma de monitoreo central)  

---

## 1. Resumen Ejecutivo

Durante la operación continua de la estación acelerográfica `DEV00`, se ha detectado una anomalía crítica de observabilidad: tras eventos de reconexión de red o microcortes de conectividad con el broker MQTT, la plataforma central de monitoreo reporta que la estación se encuentra `"offline"`. Sin embargo, la estación continúa operativa en campo, adquiriendo datos sísmicos, escribiendo en el Ring Buffer, procesando detecciones y transmitiendo periódicamente tanto las métricas de hardware (`telemetry/health`) como el estado de sus tres subsistemas de watchdog (`status/acquisition`, `status/sensor`, `status/drive`).

El diagnóstico identifica que el problema radica en el desacoplamiento entre el ciclo de vida del estado operacional (`telemetry/state`) y los ciclos de telemetría continua (cada 300 segundos). El mensaje `"online"` opera actualmente bajo un esquema **mono-disparo reactivo** ejecutado exclusivamente al recibir el callback `on_connect` y un único refresco diario a las 00:00 UTC. Ante una desconexión no graciosa, el broker MQTT dispara el mensaje de última voluntad (**LWT - Last Will and Testament**) fijando `"offline"` con bandera `retain=True`. Cuando el cliente se reconecta, una condición de carrera de toma de sesión en el broker (*session takeover*) o la saturación del socket en el callback provoca que el LWT sobrescriba o anule el mensaje `"online"`. Al carecer de retransmisión periódica (*heartbeat*), el broker retiene el estado `"offline"` hasta por 24 horas, induciendo a error al operador central.

Se evalúan alternativas de mitigación y se implementa la **Opción A**: convertir la publicación de `"online"` en un **latido periódico sincronizado cada 300 segundos** dentro del bucle principal de telemetría de `mqtt_coordinator.py`, reutilizando el timestamp de sesión activa `last_state_change`.

---

## 2. Estado Actual

| Componente / Subsistema | Estado Operativo | Impacto Observado |
|---|---|---|
| **Daemon `mqtt_coordinator.py`** | ✅ Operativo | Ejecutándose activamente en Raspberry Pi (supervisado por Supervisor). |
| **Canal `telemetry/health`** | ✅ Operativo | Publicando métricas de CPU, RAM, disco y temperatura cada 300 s. |
| **Canales `status/*` (Watchdogs)** | ✅ Operativo | Publicando `acquisition`, `sensor` y `drive` cada 300 s con `retain=True`. |
| **Canal `telemetry/state`** | ✅ Mitigado | Incorporado latido periódico de 300 s con `retain=True` y timestamp de sesión. |
| **Plataforma de Monitoreo** | 🔄 En Validación | Lista para validación en vivo tras reinicio de Supervisor. |

---

## 3. Evidencia y Análisis

### 3.1. Inspección del Callback de Conexión (`on_connect`)

En [`scripts/operation/mqtt/mqtt_coordinator.py`](file:///home/rsa/git/montajes/acelerografo-DEV00/scripts/operation/mqtt/mqtt_coordinator.py#L543-L586):

```python
def on_connect(client, userdata, flags, rc, properties=None):
    logger = userdata["logger"]
    config = userdata["config"]
    
    if rc == 0:
        logger.mqtt_connect(config["broker"]["address"], "ok")
        
        # 1. Ráfaga síncrona de suscripciones
        for sub_key in config["subscriptions"]:
            topic = resolver_topico(config, sub_key)
            client.subscribe(topic, qos=config["qos"].get("commands", 1))
            logger.mqtt_subscribe(topic, 1)
        
        # 2. Publicación diferida de boot (solo primer arranque)
        ...
        
        # 3. Publicación mono-disparo de 'online'
        now_ts = timestamp_iso()
        msg_info = publicar_state(client, config, "online", logger, timestamp_override=now_ts)
        
        if msg_info.rc == mqtt.MQTT_ERR_SUCCESS:
            logger.info(f"[CONNECT_SENT] Publish 'online' encolado (mid={msg_info.mid}). Delegando a Paho-MQTT.")
            guardar_estado("online", now_ts, userdata["state_file_path"], logger)
            userdata["last_state_change"] = now_ts
            userdata["is_disconnected_logged"] = False
```

### 3.2. Configuración LWT y Tópico Retenido

En [`scripts/operation/mqtt/mqtt_coordinator.py`](file:///home/rsa/git/montajes/acelerografo-DEV00/scripts/operation/mqtt/mqtt_coordinator.py#L848-L852):
```python
lwt_topic = resolver_topico(config, "telemetry_state")
lwt_payload = json.dumps({"status": "offline", "timestamp": timestamp_iso()})
client.will_set(lwt_topic, lwt_payload, qos=1, retain=True)
```
Y en [`configuration/configuracion_mqtt.json.template`](file:///home/rsa/git/montajes/acelerografo-DEV00/configuration/configuracion_mqtt.json.template#L34):
```json
"retain": {
    "telemetry_state": true,
    ...
}
```

### 3.3. Bucle Principal y Cadencia de Telemetría

En [`scripts/operation/mqtt/mqtt_coordinator.py`](file:///home/rsa/git/montajes/acelerografo-DEV00/scripts/operation/mqtt/mqtt_coordinator.py#L950-L970):
```python
while True:
    now = time.time()
    
    if now - last_health >= HEALTH_INTERVAL:  # HEALTH_INTERVAL = 300 segundos
        publicar_health(client, config, logger)
        publicar_acquisition_status(client, config, watchdog, logger)
        publicar_sensor_status(client, config, sensor_watchdog, logger)
        publicar_drive_status(client, config, drive_watchdog, logger)
        last_health = now
    
    # Re-publicación diaria a las 00:00
    now_dt = datetime.now(timezone.utc)
    if now_dt.day != last_day and now_dt.hour >= DAILY_REPUBLISH_HOUR:
        last_change = userdata.get("last_state_change")
        if last_change:
            logger.info(f"[DAILY_SYNC] Re-publicando estado online (vía {last_change})")
            publicar_state(client, config, "online", logger, timestamp_override=last_change)
        last_day = now_dt.day
    
    time.sleep(1)
```

**Observación clave**: Todos los canales de salud y watchdog se emitían fielmente cada 300 segundos. El canal `telemetry/state`, sin embargo, **no formaba parte de este ciclo periódico**, dependiendo exclusivamente de que el paquete emitido en `on_connect` triunfara sin colisión y sobreviviera en el broker.

---

## 4. Hallazgos y Causa Raíz

### Hallazgo 1: Condición de Carrera en el Broker MQTT por "Session Takeover" y LWT
* **Descripción técnica**: Cuando se produce un parpadeo de red (jitter, microcorte de radioenlace, pérdida transitoria de señal celular/WiFi), la conexión TCP previa del cliente queda como un socket semi-abierto (*half-open socket*) en el broker.
* **Causa**: Al recuperarse la conectividad física, el cliente Paho-MQTT reconecta inmediatamente enviando un nuevo paquete `CONNECT` con el mismo `client_id`. De acuerdo al estándar MQTT (sección 3.1.4 de MQTT v3.1.1 / MQTT v5.0), cuando el broker recibe una conexión con un `client_id` ya conectado, procede a cerrar la conexión TCP anterior (*session takeover*). Al cerrarse la conexión anterior sin que mediara un paquete `DISCONNECT` limpio, **el broker dispara el Will Message (LWT) configurado para la sesión previa**:
  `rsa/seismic/smart/{id}/telemetry/state` → `{"status": "offline"}` con `retain=True`.
* **Mecanismo de activación**: Si el broker procesa la desconexión del socket anterior casi al mismo tiempo que el nuevo `PUBLISH` de `"online"` enviado en `on_connect`, o si la ráfaga de `SUBSCRIBE` retrasa el `PUBLISH` `"online"`, el broker puede ejecutar:
  1. `CONNECT` (nueva sesión aceptada).
  2. `PUBLISH` `"online"` (mensaje retenido = online).
  3. Cierre del socket huérfano viejo → **Disparo del LWT `"offline"`** (mensaje retenido = offline).
  El estado final retenido en el broker resulta ser `"offline"`, a pesar de que el cliente nuevo está conectado exitosamente.

### Hallazgo 2: Asincronía de `client.publish` y Descarte por Red Inestable
* **Descripción técnica**: En `on_connect()`, la llamada a `publicar_state()` ejecuta `client.publish(...)` y verifica únicamente `msg_info.rc == mqtt.MQTT_ERR_SUCCESS`.
* **Causa**: En la biblioteca Paho-MQTT, un código de retorno `0` en `publish()` únicamente certifica que el paquete MQTT ha sido colocado en la cola de memoria saliente interna (`_out_messages`). No garantiza que el paquete haya salido físicamente por el socket ni que el broker haya respondido con el `PUBACK` (QoS 1).
* **Mecanismo de activación**: Si la reconexión es inestable y el socket sufre una nueva desconexión inmediata durante el intercambio, Paho descarta o resetea colas salientes dependientes de la sesión, perdiéndose el mensaje `"online"`.

### Hallazgo 3: Arquitectura Mono-Disparo sin Mecanismo de Heartbeat de Recuperación
* **Descripción técnica**: El diseño original asumió que el estado `"online"` solo debía emitirse en eventos discretos de conexión, confiando ciegamente en el bit `retain=True` del broker.
* **Causa**: No existía ningún mecanismo activo de refresco periódico durante la operación normal de la estación; únicamente un refresco una vez al día a las 00:00 UTC.
* **Impacto**: Si la emisión de `online` fallaba o era sobreescrita por el LWT tras una reconexión a las 01:15 AM, la estación permanecía marcada en la base de datos y tablero central como `"offline"` durante **22 horas y 45 minutos**, aun cuando estuviera transmitiendo gigabytes de datos sísmicos y telemetría de salud de manera ininterrumpida.

---

## 5. Evaluación de Riesgo

| # | Escenario de Riesgo | Probabilidad | Impacto | Mitigación Requerida |
|---|---|---|---|---|
| **R1** | Falsas alarmas operativas y despacho innecesario de personal a campo creyendo que la estación está fuera de servicio. | Alta | Alto | Heartbeat periódico de estado que sobreescriba en máximo 5 min cualquier anomalía de retención. |
| **R2** | Desalineación entre tableros de control (tablero general leyendo `telemetry/state` vs panel de salud leyendo `telemetry/health`). | Alta | Medio | Unificar la cadencia de emisión de ambos tópicos a 300 s. |
| **R3** | Saturación del broker por exceso de publicaciones retenidas si el intervalo fuera demasiado corto. | Baja | Bajo | Mantener el intervalo en 300 s (1 mensaje cada 5 minutos), lo que representa un tráfico despreciable para cualquier broker MQTT. |

---

## 6. Opciones y Decisiones

### Decisión 1: Estrategia de Refresco Periódico de `telemetry/state`

| Opción | Descripción | Ventajas | Desventajas |
|---|---|---|---|
| **A. Heartbeat 300 s con timestamp de último cambio (`last_state_change`) [SELECCIONADA]** | Publicar `"online"` en el loop principal cada 300 s junto a `telemetry/health`, manteniendo en el JSON el timestamp exacto en que la estación se conectó (`boot`/reconexión). | • Preserva la semántica de "cuándo comenzó la sesión online" para cálculo de uptime.<br>• Resuelve la carrera con el LWT en máx. 300 s.<br>• Mantiene el mensaje retenido fresco en el broker. | El timestamp de payload no avanza cada 5 minutos (refleja el inicio de la sesión actual, no el latido). |
| **B. Heartbeat 300 s con timestamp actual (`now_ts`)** | Publicar `"online"` en el loop principal cada 300 s con `timestamp = datetime.now(utc)`. | • Claridad absoluta de que la estación está viva al segundo actual.<br>• Limpia de inmediato cualquier residuo de LWT.<br>• Fácilmente interpretable por cualquier dashboard como latido vivo. | Modifica la semántica de `timestamp` (indica última confirmación de vida en lugar de hora de inicio de conexión). |
| **C. Inversión de orden en `on_connect` + Delay preventivo** | En `on_connect`, publicar `"online"` *antes* de las suscripciones, o añadir un `sleep(0.5)` antes de publicar. | • Intenta esquivar la carrera inmediata en el broker. | No ofrece autorrecuperación si la red vuelve a fallar. Mantiene la vulnerabilidad sistémica mono-disparo. |

> **Decisión Adoptada**: Se seleccionó la **Opción A** por recomendación del usuario, ya que mantiene información relevante de tiempo de actividad ininterrumpido (*uptime*) de la conexión actual y refresca de forma infalible el mensaje retenido en el broker cada 5 minutos.

---

## 7. Mitigaciones Aplicadas

* **Fase 1 completada**: En [`scripts/operation/mqtt/mqtt_coordinator.py`](file:///home/rsa/git/montajes/acelerografo-DEV00/scripts/operation/mqtt/mqtt_coordinator.py):
  1. Rastreo explícito de `userdata["is_connected"]` en `on_connect()` y `on_disconnect()`.
  2. Priorización de `publicar_state("online")` inmediatamente tras autenticación antes de suscribirse a los tópicos de comandos y eventos.
  3. Integración del latido periódico en `main()` cada 300 segundos condicionado a `client.is_connected()`.
* **Fase 2 completada**: En [`scripts/operation/mqtt/test_mqtt_coordinator_integration.py`](file:///home/rsa/git/montajes/acelerografo-DEV00/scripts/operation/mqtt/test_mqtt_coordinator_integration.py):
  1. Tres nuevos tests unitarios verificando QoS 1, `retain=True`, preservación de timestamp de sesión y descarte si está desconectado.
  2. Validación ejecutada exitosamente: **10/10 tests pasados**.

---

## 8. Backlog de Mejoras (Plan de Contingencia y Robustecimiento)

1. **[Mejora 1: Heartbeat Periódico en Loop Principal]**: ✅ Implementado en Fase 1.
2. **[Mejora 2: Priorización de Publicación en `on_connect`]**: ✅ Implementado en Fase 1.
3. **[Mejora 3: Actualización de Documentación de Contexto]**: ✅ Implementado en Fase 3 (`docs/context/mqtt_coordinator_context.md`).

---

## 9. Dependencias y Prerrequisitos

| Prerrequisito | Estado | Acción Requerida |
|---|---|---|
| Python 3.9+ en `.venv` | ✅ Disponible | No requiere librerías adicionales. |
| Broker MQTT (Mosquitto/EMQX) | ✅ Operativo | Soporta `retain=True` y QoS 1 sin cambios de configuración de broker. |
| Permisos de Supervisor en DEV00 | ✅ Disponible | Requiere `sudo supervisorctl restart mqtt_coordinator` tras aplicar cambios. |

---

## 10. Plan de Validación

| # | Checkpoint | Criterio de Éxito | Estado |
|---|---|---|---|
| **CP-1** | Validación sintáctica local | `python3 -m py_compile scripts/mqtt/mqtt_coordinator.py` sin errores. | ✅ Aprobado |
| **CP-2** | Ejecución de suite unitaria/integración | `test_mqtt_coordinator_integration.py` aprueba 10/10 tests. | ✅ Aprobado |
| **CP-3** | Despliegue en Supervisor | Reiniciar daemon con `sudo supervisorctl restart mqtt_coordinator`. | ⏳ Pendiente Fase 4 |
| **CP-4** | Verificación en logs en vivo | Confirmar en `mqtt_coordinator.log` la emisión periódica de `[HEARTBEAT_STATE]`. | ⏳ Pendiente Fase 4 |

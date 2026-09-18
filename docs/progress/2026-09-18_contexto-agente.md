# Resumen de Sesión: Latido Periódico (Heartbeat) para `telemetry/state`, Resiliencia LWT y Erradicación de Falsos Estados Offline

**Fecha**: 2026-09-18  
**Repositorio**: `acelerografo-DEV00`  
**Agente de IA**: Antigravity  
**Usuario**: Milton Muñoz  

---

## 🎯 Objetivo de la Sesión

Investigar, diagnosticar y resolver de raíz la anomalía de desincronización en el canal MQTT `telemetry/state` que causaba falsos positivos de estado `"offline"` persistentes en la plataforma central de monitoreo tras eventos de reconexión de red. Formalizar el análisis mediante un diagnóstico técnico (`diagnostico_tecnico.md`), estructurar un plan de contingencia e implementación (`planning_guide.md`), ejecutar la solución técnica mediante un latido periódico (*heartbeat*) de 300 segundos preservando la semántica de tiempo de actividad (*uptime*) de la sesión (Opción A), expandir la suite de pruebas automatizadas a 10 tests, formalizar el **ADR-023** en el repositorio institucional federado y validar el comportamiento en vivo en la estación acelerográfica `DEV00`.

---

## 📂 Estructura del Repositorio Implementada

```text
montajes/acelerografo-DEV00/
├── docs/
│   ├── adr/
│   │   ├── 022_gobernanza_ciclo_vida_eventos_extraidos_y_store_and_forward.md
│   │   └── 023_heartbeat_periodico_telemetria_state_y_resiliencia_lwt.md     # [NUEVO] ADR formalizando el heartbeat de 300 s y mitigación LWT
│   ├── analysis/
│   │   ├── 2026-09-01_diagnostico_automatizacion_despliegue.md
│   │   ├── 2026-09-01_diagnostico_parada_adquisicion_cha01.md
│   │   └── 2026-09-18_diagnostico_falsos_offline_telemetry_state.md          # [NUEVO] Diagnóstico formal de causas raíz en reconexiones MQTT
│   ├── blueprints/
│   │   ├── 2026-09-17_plan_administracion_eventos_extraidos_gestor_acq.md
│   │   └── 2026-09-18_plan_heartbeat_telemetry_state.md                      # [NUEVO] Plan de implementación de 4 fases (Opción A)
│   ├── context/
│   │   └── mqtt_coordinator_context.md                                       # [MODIFICADO] Documentación de cadencia híbrida (conexión + heartbeat 300s)
│   └── progress/
│       ├── 2026-09-17_contexto-agente.md
│       └── 2026-09-18_contexto-agente.md                                     # [NUEVO] Documento de transición técnica de la sesión actual
└── scripts/
    └── operation/
        └── mqtt/
            ├── mqtt_coordinator.py                                           # [MODIFICADO] Priorización en on_connect, tracking is_connected y heartbeat 300s
            └── test_mqtt_coordinator_integration.py                          # [MODIFICADO] Expansión con 3 tests de state/heartbeat (10/10 OK)
```

*(En el repositorio institucional federado `rsa/RSA-Metodologias/` se incorporó `decisiones/023_heartbeat_periodico_telemetria_state_y_resiliencia_lwt.md`, con actualización de sus índices en `decisiones/index.md` e `indice/indice_tematico.md`).*

---

## ⚙️ Configuración del Entorno Virtual (`.venv`)

El entorno operativo se ubica en la Raspberry Pi 3B+ bajo:
`/home/rsa/projects/acelerografo/.venv/` (Python 3.9+).

* **Cero Dependencias Externas Nuevas**:
  - Toda la solución se implementó utilizando exclusivamente la biblioteca estándar de Python y `paho-mqtt`, la cual ya forma parte del entorno base de la estación.
  - La suite de pruebas de integración [`scripts/operation/mqtt/test_mqtt_coordinator_integration.py`](file:///home/rsa/git/montajes/acelerografo-DEV00/scripts/operation/mqtt/test_mqtt_coordinator_integration.py) opera mediante mocks aislados (`unittest.mock`), sin requerir conexión física activa a un broker para validar la lógica del coordinador.

---

## 🛠️ Modificaciones de Código y Refactorización

### 1. Diagnóstico de Causa Raíz (ADR-023)
Se identificaron tres factores causales de la anomalía de falsos estados "offline":
1. **Condición de carrera por Session Takeover en el Broker MQTT**: Al reconectar el cliente con el mismo `client_id`, el broker cierra la conexión TCP previa y dispara el Will Message (LWT) configurado (`telemetry/state` -> `offline`, `retain=True`). Si el procesamiento de cierre del socket huérfano ocurre simultáneamente o tras el paquete entrante `online` de `on_connect()`, el broker fija `"offline"` como estado retenido.
2. **Asincronía y Descarte en Buffer de Salida**: `publicar_state()` utiliza `client.publish()`, cuyo `rc == 0` solo garantiza encolamiento en memoria interna de Paho, pudiendo perderse ante reconexiones inestables sucesivas.
3. **Diseño Mono-Disparo sin Autorrecuperación**: El estado `"online"` solo se emitía en el apretón de manos inicial y a las 00:00 UTC. Si la reconexión sufría la carrera del LWT, la estación quedaba bloqueada visualmente en `"offline"` hasta por 24 horas.

### 2. Priorización Inmediata en `on_connect()`
En [`scripts/operation/mqtt/mqtt_coordinator.py`](file:///home/rsa/git/montajes/acelerografo-DEV00/scripts/operation/mqtt/mqtt_coordinator.py):
* Al validar `rc == 0`, se actualiza de forma determinista `userdata["is_connected"] = True`.
* Se captura `now_ts = timestamp_iso()` y se asigna a `userdata["last_state_change"] = now_ts`.
* Se emite `publicar_state(client, config, "online", logger, timestamp_override=now_ts)` **inmediatamente**, *antes* de procesar el bucle de suscripciones a los 5 tópicos, cerrando la ventana de tiempo para posibles carreras con el broker.

### 3. Rastreo de Desconexión en `on_disconnect()`
* Al dispararse el callback de desconexión del broker, se actualiza `userdata["is_connected"] = False`, impidiendo que el bucle principal intente emitir latidos cuando el socket no se encuentra disponible.

### 4. Latido Periódico de 300 s (Heartbeat - Opción A)
En el bucle principal `while True` de `main()`:
* Integrado en la ráfaga periódica de 5 minutos junto a `publicar_health()`, `publicar_acquisition_status()`, `publicar_sensor_status()` y `publicar_drive_status()`.
* Condicionado a `client.is_connected() or userdata.get("is_connected", False)`.
* Re-publica `telemetry/state` con `"online"`, QoS 1 y `retain=True` reutilizando el timestamp fijado en `userdata["last_state_change"]`. Esto sobreescribe cualquier residuo de LWT en un plazo máximo de 5 minutos manteniendo intacta la información del inicio de la sesión activa (*uptime*).

### 5. Suite de Pruebas Automatizadas
En [`scripts/operation/mqtt/test_mqtt_coordinator_integration.py`](file:///home/rsa/git/montajes/acelerografo-DEV00/scripts/operation/mqtt/test_mqtt_coordinator_integration.py):
* Añadidos 3 nuevos tests:
  1. `test_publicacion_state_online_qos_y_retain`: Valida parámetros MQTT y estructura del payload JSON.
  2. `test_heartbeat_state_preserva_timestamp_ultimo_cambio`: Certifica que el latido preserve el timestamp original de sesión.
  3. `test_heartbeat_state_no_publica_si_desconectado`: Certifica la no emisión cuando el cliente está desconectado.
* **Resultado de Ejecución en Raspberry Pi**: **10/10 tests pasados exitosamente (`Todo OK ✅`)**.

---

## 📊 Validación en Vivo en la Estación DEV00

Tras aplicar los cambios y ejecutar `sudo supervisorctl restart mqtt_coordinator`:
* El proceso se reinició y conectó limpiamente al broker MQTT (`174.138.41.251`).
* Se emitió y encoló de forma prioritaria el estado `'online'` inicial (`mid=4`).
* Las suscripciones a los 5 tópicos se completaron con éxito.
* Se ejecutó el latido corrector inmediatamente al inicializar los watchdogs:
  `[HEARTBEAT_STATE] Refrescando telemetry_state (online desde 2026-09-18T17:20:44Z)`.
* Todos los subsistemas operan de forma nominal: latencia de adquisición `0.7s`, aceleraciones triaxiales estables, reloj `RPi` sincronizado y sincronización Google Drive con 0 pendientes y 14.2% de disco libre.

---

## 📋 Pasos Sugeridos para el Siguiente Agente

1. **Replicación en Estaciones en Campo (`TEST`, `CHA01`)**:
   - Integrar los cambios de `mqtt_coordinator.py` y el test suite en las demás estaciones acelerográficas de la flota mediante el script de actualización remota o despliegue OTA (`update.sh`).
2. **Supervisión de la Plataforma de Monitoreo Central**:
   - Confirmar en el tablero central de visualización (Grafana / Dashboard sísmico) que la estación `DEV00` mantenga su estado `"online"` de forma ininterrumpida incluso ante microcortes forzados de enlace.
3. **Monitoreo Continuo de Telemetría**:
   - Verificar la estabilidad de los logs en `$PROJECT_LOCAL_ROOT/log-files/mqtt_coordinator.log` observando las entradas recurrentes `[HEARTBEAT_STATE]` cada 300 segundos.

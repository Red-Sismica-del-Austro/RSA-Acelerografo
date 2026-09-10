# Resumen de Sesión: Telemetría Especializada, Cadencia Unificada a 5 Minutos y Resiliencia en Estaciones

**Fecha**: 2026-09-10  
**Repositorio**: `acelerografo-DEV00`  
**Agente de IA**: Antigravity  
**Usuario**: Milton Muñoz  

---

## 🎯 Objetivo de la Sesión

Diseñar y planificar la arquitectura de telemetría de campo para las estaciones acelerográficas de la RSA, orientada a alimentar el nuevo modelo de observabilidad centralizada:
1. Diseñar el módulo auditor de integridad del sensor (`SensorWatchdog`) que evalúe periódicamente que las aceleraciones triaxiales en reposo ($A_x, A_y \approx 0$, $A_z \approx 9.81\text{ m/s}^2$) y la sincronización de reloj sean válidas.
2. Diseñar el módulo auditor de Google Drive (`DriveWatchdog`) que reporte archivos pendientes y protegidos por fallo.
3. Unificar la cadencia de evaluación y publicación MQTT de Adquisición y Sensor a **5 minutos (300 s)**, acoplada directamente al ciclo de `telemetry/health` en `mqtt_coordinator.py`, evitando saturar el canal de comunicaciones y habilitando un comando de contingencia de parada remota de seguridad.

---

## 📂 Estructura del Repositorio Implementada

```text
montajes/acelerografo-DEV00/
├── docs/
│   ├── blueprints/
│   │   ├── 2026-09-02_plan_resiliencia_pipeline_adquisicion.md
│   │   └── 2026-09-10_plan_implementacion_telemetria_sensor_adquisicion_drive.md # [NUEVO] Blueprint de Estaciones
│   └── progress/
│       ├── 2026-09-03_contexto-agente.md
│       └── 2026-09-10_contexto-agente.md                                          # [NUEVO] Transición técnica
├── scripts/
│   └── operation/
│       ├── acelerografo/
│       │   └── comprobar_registro_wrapper.py                                      # Wrapper base para lecturas C
│       └── mqtt/
│           ├── acquisition_watchdog.py                                            # Auditor de Ring Buffer (existente)
│           ├── drive_watchdog.py                                                  # [POR CREAR] Auditor de Drive y espacio
│           ├── sensor_watchdog.py                                                 # [POR CREAR] Auditor de aceleraciones triaxiales
│           ├── test_sensor_watchdog.py                                            # [POR CREAR] Tests unitarios
│           ├── test_drive_watchdog.py                                             # [POR CREAR] Tests unitarios
│           └── mqtt_coordinator.py                                                # [POR MODIFICAR] Unificación a 300s
```

---

## ⚙️ Decisiones Técnicas y Arquitectura Consolidada

### 1. Unificación de Cadencia a 5 Minutos (300 s)
* Para evitar la dispersión de timers y ráfagas constantes en enlaces móviles de campo:
  - `HEALTH_INTERVAL = 300` y `ACQUISITION_CHECK_INTERVAL = 300`.
  - Cada 5 minutos exactos, `mqtt_coordinator.py` evalúa y publica de forma sincronizada:
    1. `telemetry/health` (métrica de hardware del host).
    2. `status/acquisition` (Ring Buffer `age_seconds` y estado).
    3. `status/sensor` (Aceleraciones triaxiales y reloj).
    4. `status/drive` (Conteo de archivos pendientes y protegidos en Drive).
* Las publicaciones de estado se emiten con **QoS 1** y flag **`retain = true`** para garantizar persistencia en el broker Mosquitto.

### 2. Módulo de Integridad Física del Acelerómetro (`SensorWatchdog`)
* Invoca a `comprobar_registro_wrapper.py` con timeout defensivo de 12 s.
* Valida tolerancias físicas:
  - $|A_x| \le 0.5\text{ m/s}^2$
  - $|A_y| \le 0.5\text{ m/s}^2$
  - $|A_z - 9.81| \le 0.8\text{ m/s}^2$
  - `clock_source` no nulo ni en estado `E3`.
* Si detecta anomalía, clasifica como `status: "error"` con `reason: "accelerometer_anomaly"`.

### 3. Protocolo de Remediabilidad y Parada de Seguridad Remota
* Se identificó que mientras una parada de adquisición es remediable remotamente (reinicio de servicio), una falla en el sensor es **física e irreparable de forma remota**.
* Para evitar que un sensor roto llene el disco de ruido inservible o dispare falsas alarmas que contaminen el Correlador Regional Central, se diseñó el comando MQTT:
  - `rsa/seismic/smart/{id}/cmd/stop_acquisition_safety`
  - Permite que el operador central ordene la detención ordenada de `rsa-acelerografo.service`.

### 4. Módulo de Google Drive (`DriveWatchdog`)
* Audita `$PROJECT_LOCAL_ROOT/log-files/drive_status.json` y el directorio `/home/rsa/data/mseed/`.
* Reporta `pending_mseed` y `failed_uploads_protected`, clasificando como advertencia si hay archivos acumulados.

---

## 🛠️ Artefactos y Documentación Generada

1. **Plan de Implementación en Estaciones**: [`docs/blueprints/2026-09-10_plan_implementacion_telemetria_sensor_adquisicion_drive.md`](../blueprints/2026-09-10_plan_implementacion_telemetria_sensor_adquisicion_drive.md)
   - Contiene la arquitectura detallada, el código completo propuesto para `sensor_watchdog.py` y `drive_watchdog.py`, la refactorización de `mqtt_coordinator.py` y el protocolo de pruebas con `mosquitto_sub`.

---

## 📋 Pasos Sugeridos para el Siguiente Agente

1. **Crear Módulos y Tests en `scripts/operation/mqtt/`**:
   - Implementar `sensor_watchdog.py` y `test_sensor_watchdog.py`.
   - Implementar `drive_watchdog.py` y `test_drive_watchdog.py`.
   - Ejecutar los tests unitarios bajo `.venv`.
2. **Refactorizar `mqtt_coordinator.py`**:
   - Ajustar `ACQUISITION_CHECK_INTERVAL = 300`.
   - Integrar `publicar_sensor_status()` y `publicar_drive_status()`.
   - Registrar el comando `cmd/stop_acquisition_safety` en el despachador.
3. **Actualizar Plantilla de Configuración**:
   - Agregar los tópicos en `configuration/configuracion_dispositivo.json.template` y actualizar `update.sh`.
4. **Validación en Estación de Desarrollo (`DEV0`)**:
   - Reiniciar el servicio bajo Supervisor (`sudo supervisorctl restart mqtt_coordinator`) y verificar con `mosquitto_sub` que las 4 telemetrías se emitan limpiamente cada 5 minutos sin ráfagas intermedias.

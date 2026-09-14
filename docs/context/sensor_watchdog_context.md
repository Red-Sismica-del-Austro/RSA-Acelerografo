---
proyecto: acelerografo-DEV00
tipo: contexto_tecnico
archivo: scripts/operation/mqtt/sensor_watchdog.py
temas: [mqtt, watchdog, sensor, aceleracion, reloj, telemetria, resiliencia]
generado: 2026-09-14
---
# sensor_watchdog.py — Contexto para Agentes IA

> Auditor de integridad física del acelerómetro y sincronización de reloj que ejecuta periódicamente el diagnóstico en reposo y emite alertas estructuradas en MQTT ante anomalías mecánicas o de sincronización.

**Ruta**: `scripts/operation/mqtt/sensor_watchdog.py`  
**LOC**: ~160 | **Lenguaje**: Python 3 | **Dependencias**: stdlib (`subprocess`, `json`, `os`, `sys`, `datetime`, `logging`)  
**Proceso**: Instanciado y ejecutado cada 300 segundos (5 minutos) dentro de `mqtt_coordinator.py` bajo Supervisor.

---

## Arquitectura

```mermaid
graph TD
    subgraph "Hardware y Firmware"
        SENS["Acelerómetro Triaxial MEMS / dsPIC"]
        C_BIN["comprobar_registro (Binario C)"]
    end

    subgraph "Capa de Operación"
        WRAP["comprobar_registro_wrapper.py<br/>($PROJECT_LOCAL_ROOT/scripts/acelerografo/)"]
        SW["SensorWatchdog<br/>(scripts/mqtt/sensor_watchdog.py)"]
        MC["mqtt_coordinator.py<br/>(Ciclo 300 s)"]
    end

    subgraph "Broker MQTT"
        TOPIC["rsa/seismic/smart/{id}/status/sensor<br/>(QoS 1, Retain true)"]
    end

    SENS -->|Lectura SPI| C_BIN
    C_BIN -->|Texto plano| WRAP
    WRAP -->|JSON estructurado (stdout)| SW
    SW -->|Validación física reposo + reloj| SW
    SW -->|Payload clasificado| MC
    MC -->|Publicación sincronizada| TOPIC
```

---

## Umbrales Nominales y Criterios Físicos

| Métrica / Parámetro | Rango Nominal Aceptado | Criterio de Error (`status: error`) |
|---|---|---|
| Eje X ($A_x$) | $|A_x| \le 0.5\text{ m/s}^2$ | $|A_x| > 0.5\text{ m/s}^2$ (`ax_out_of_range`) |
| Eje Y ($A_y$) | $|A_y| \le 0.5\text{ m/s}^2$ | $|A_y| > 0.5\text{ m/s}^2$ (`ay_out_of_range`) |
| Eje Z ($A_z$) | $|A_z - 9.81| \le 0.8\text{ m/s}^2$ (rango [9.01, 10.61]) | Fuera de rango (ej. $0\text{ m/s}^2$ desconectado o saturación) |
| Fuente de Reloj | `"GPS"` o `"RPi"` | Código `"E3"` o prefijo de error (`clock_src_err`) |
| Error de Reloj | `null` | String con detalle `E3/GPS: ...` (`clock_err`) |

---

## Clasificación de Estados y Payloads JSON

### 1. Estado Nominal (`status: "ok"`)
Emitido cuando las 3 aceleraciones están en reposo nominal y el reloj no reporta error:

```json
{
  "status": "ok",
  "ax": 0.4414,
  "ay": 0.1484,
  "az": 9.5807,
  "clock_source": "RPi",
  "clock_error": null,
  "reason": "nominal",
  "station_id": "DEV0",
  "timestamp": "2026-09-14T18:03:58Z"
}
```

### 2. Estado de Anomalía Física o Reloj (`status: "error"`)
Emitido cuando un eje excede la tolerancia o el reloj pierde sincronía crítica:

```json
{
  "status": "error",
  "ax": 0.01,
  "ay": 0.02,
  "az": 0.0,
  "clock_source": "GPS",
  "clock_error": "az_out_of_range(0.000)",
  "reason": "accelerometer_anomaly",
  "station_id": "DEV0",
  "timestamp": "2026-09-14T18:03:58Z"
}
```

### 3. Error de Ejecución / Entorno (`status: "error"`)
Emitido si el wrapper no existe, falla la ejecución o se agota el timeout:

```json
{
  "status": "error",
  "ax": null,
  "ay": null,
  "az": null,
  "clock_source": null,
  "clock_error": "wrapper_not_found",
  "reason": "wrapper_not_found",
  "station_id": "DEV0",
  "timestamp": "2026-09-14T18:03:58Z"
}
```

---

## Componentes Clave

| Elemento | Tipo | Descripción |
|---|---|---|
| `SensorWatchdog` | Clase | Evaluador principal de integridad triaxial y reloj. |
| `__init__(wrapper_path)` | Constructor | Resuelve `wrapper_path` buscando estrictamente en `$PROJECT_LOCAL_ROOT/scripts/acelerografo/comprobar_registro_wrapper.py`. |
| `evaluar_integridad(station_id)` | Método | Ejecuta el wrapper vía subproceso con timeout de 12 s, analiza el JSON retornado, valida los rangos físicos y construye el payload estructurado. |

---

## Manejo Defensivo y Tolerancia a Fallos

1. **Aislamiento de Rutas**: Busca el wrapper exclusivamente a través de la variable de entorno `$PROJECT_LOCAL_ROOT` o por deducción relativa desde `scripts/`, sin consultar el repositorio Git ni utilizar rutas absolutas hardcodeadas.
2. **Protección contra Bloqueos**: La invocación de `subprocess.run` cuenta con un timeout estricto de 12 segundos para prevenir que el daemon `mqtt_coordinator` quede colgado ante bloqueos del bus SPI.
3. **Propagación de Entorno**: Inyecta y asegura la variable `PROJECT_LOCAL_ROOT` en el entorno del subproceso para garantizar que el wrapper localice el binario C compilado.

---

## Tests Unitarios

**Archivo**: `scripts/operation/mqtt/test_sensor_watchdog.py`

```bash
cd /home/rsa/projects/acelerografo
.venv/bin/python3 scripts/mqtt/test_sensor_watchdog.py
```
* Cobertura: 9 pruebas unitarias que validan lectura nominal, anomalía en eje vertical Z, anomalía en ejes horizontales X/Y, fallas de reloj, wrapper no encontrado, returncode no cero, timeouts, valores nulos y errores en salida JSON.

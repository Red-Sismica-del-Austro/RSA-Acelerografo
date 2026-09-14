---
id: ADR-020
titulo: Telemetría Especializada, Cadencia Unificada a 5 Minutos y Parada Remota de Contingencia en Estaciones Acelerográficas
estado: Aceptado
fecha: 2026-09-14
temas: [mqtt, telemetria, watchdog, sensor, drive, resiliencia, contingencia, acelerografo]
entorno: acelerografo
---

# ADR-020: Telemetría Especializada, Cadencia Unificada a 5 Minutos y Parada Remota de Contingencia en Estaciones Acelerográficas

## Estado

**Aceptado** | Fecha: 2026-09-14

---

## Contexto

Con la adopción del modelo jerárquico de observabilidad centralizada en la Red Sísmica del Austro (ADR-019), las estaciones de campo (`acelerografo-DEV00`) requerían evolucionar su arquitectura de telemetría y contingencia debido a varios problemas operativos:

1. **Dispersión de Intervalos y Consumo de Datos Móviles**: El watchdog del Ring Buffer (`acquisition_watchdog.py`) publicaba cada 60 segundos, mientras la telemetría de hardware (`telemetry/health`) lo hacía cada 300 segundos. Esta asimetría generaba tráfico continuo en enlaces celulares 3G/4G con planes de datos limitados.
2. **Ceguera ante Fallas Físicas del Acelerómetro**: El sistema únicamente vigilaba el flujo de bytes hacia el Ring Buffer. Si el sensor acelerométrico MEMS sufría desprendimiento mecánico, saturación o daño electrónico (reportando ceros o ruido estático pero generando tramas binarias íntegras), el pipeline lo consideraba nominal, ocultando la avería al operador.
3. **Imposibilidad de Remediación Remota ante Daño Físico**: A diferencia de una caída de software (remediable reiniciando el servicio), un fallo físico en el sensor es irreparable de forma remota. Permitir que una estación dañada continúe adquiriendo inunda el disco con terabytes de ruido inservible y contamina el Correlador Regional Central con disparos espurios.
4. **Falta de Visibilidad en Sincronización Google Drive**: No existía monitoreo continuo de archivos MiniSEED acumulados en disco ni detección de archivos protegidos por reintentos fallidos de subida.
5. **Acoplamiento de Entorno y Rutas**: Ciertos scripts dependían implícitamente de rutas del repositorio Git en lugar de ejecutarse de forma autosuficiente desde el directorio de producción (`$PROJECT_LOCAL_ROOT`).

---

## Opciones Evaluadas

### Opción A: Hilos Independientes con Timers Heterogéneos en `mqtt_coordinator.py`
Mantener un hilo o timer por cada auditor con su propia cadencia (ej. adquisición 60s, sensor 120s, hardware 300s, drive 600s).
- **Ventajas**: Menor latencia de reporte en anomalías de adquisición rápida.
- **Desventajas**: Ráfagas constantes e impredecibles en el canal móvil; desincronización de marcas de tiempo en el servidor; aumento del consumo de batería y datos móviles; alta complejidad para correlacionar diagnósticos simultáneos en Grafana.

### Opción B: Ejecución Externa vía Crontab
Invocar auditores independientes desde el cron del sistema y publicar vía `mosquitto_pub` por CLI.
- **Ventajas**: Desacopla la lógica del proceso `mqtt_coordinator.py`.
- **Desventajas**: Pérdida de conexión MQTT persistente (abrir y cerrar sockets SSL/TCP cada 5 minutos consume más ancho de banda); no permite integración con el despachador de comandos reactivos ni control de LWT unificado.

### Opción C: Cadencia Unificada a 300 s, Despacho en Ráfaga Sincronizada y Comando de Parada de Seguridad (Elegida)
Centralizar los tres auditores (`AcquisitionWatchdog`, `SensorWatchdog`, `DriveWatchdog`) dentro del bucle principal de `mqtt_coordinator.py` sincronizados a 300 segundos (5 minutos), con banderas `QoS 1` y `retain = true`, habilitando el comando remoto de contingencia `stop_acquisition_safety`.
- **Ventajas**:
  - Máxima eficiencia en enlaces celulares: 1 sola ráfaga de publicación cada 5 minutos con todas las telemetrías coincidiendo al mismo segundo exacto.
  - Retención MQTT garantizada: Cualquier suscriptor o el servidor Telegraf recibe el último estado inmediatamente al conectarse sin esperar al siguiente ciclo.
  - Diagnóstico físico en reposo ($|A_x|, |A_y| \le 0.5$, $|A_z - 9.81| \le 0.8\text{ m/s}^2$) y de reloj antes de que los datos afecten el análisis sismológico.
  - Protección del almacenamiento y correlación central mediante parada de emergencia controlada con `sudo systemctl stop rsa-acelerografo.service`.
  - Aislamiento estricto bajo `$PROJECT_LOCAL_ROOT/scripts/` eliminando dependencias de Git en producción.
- **Desventajas**:
  - Detección de caída de adquisición con una ventana de hasta 5 minutos (ampliamente suficiente para redes acelerográficas regionales).

---

## Decisión

Se eligió la **Opción C** implementando cinco pilares de arquitectura:

### 1. Unificación de Cadencia a 5 Minutos (300 s)
En `mqtt_coordinator.py` se fijaron `HEALTH_INTERVAL = 300` y `ACQUISITION_CHECK_INTERVAL = 300`. En cada ciclo se evalúan y publican de forma síncrona:
- `telemetry/health` (hardware host).
- `status/acquisition` (Ring Buffer `age_seconds`, `qos=1, retain=True`).
- `status/sensor` (aceleraciones triaxiales y reloj, `qos=1, retain=True`).
- `status/drive` (pendientes MiniSEED, protegidos y espacio libre, `qos=1, retain=True`).

### 2. Módulo de Integridad Física del Sensor (`SensorWatchdog`)
Invoca como subproceso aislado a `comprobar_registro_wrapper.py` (con timeout estricto de 12 s) ubicado exclusivamente en `$PROJECT_LOCAL_ROOT/scripts/acelerografo/`. Valida:
- Reposo horizontal: $|A_x| \le 0.5\text{ m/s}^2$ y $|A_y| \le 0.5\text{ m/s}^2$.
- Gravedad vertical: $|A_z - 9.81| \le 0.8\text{ m/s}^2$ (rango nominal [9.01, 10.61]).
- Sincronía de reloj: fuente `"GPS"` o `"RPi"`, marcando anomalía ante códigos `"E3"`.

### 3. Protocolo de Parada Remota de Seguridad (`cmd/stop_acquisition_safety`)
Registrado en `CommandDispatcher`. Al recibir `rsa/seismic/smart/{id}/cmd/stop_acquisition_safety`:
1. Ejecuta `sudo systemctl stop rsa-acelerografo.service`.
2. Publica respuesta inmediata en `cmd/stop_acquisition_safety/res` con acuse `completed` o `error`.
3. Detiene la generación de tramas para evitar saturar el disco o disparar detecciones falsas con sensores averiados.

### 4. Auditoría de Google Drive y Espacio en Disco (`DriveWatchdog`)
Inspecciona de forma dual los formatos de registro de subida (`drive_status.json` y `uploaded_files_registry.json`), alertando ante acumulación de archivos (`pending_mseed > 3`) o fallos repetidos retenidos (`failed_uploads_protected > 0`), reportando el porcentaje de disco libre derivado de `shutil.disk_usage`.

### 5. Despliegue Limpio y Aislamiento de Entorno
Actualizado `update.sh` para sincronizar `scripts/operation/acelerografo/` hacia `$PROJECT_LOCAL_ROOT/scripts/acelerografo/`, garantizando que `comprobar_registro_wrapper.py` exista en producción sin requerir acceso al árbol de Git en runtime.

---

## Consecuencias

### Positivas
- **Ahorro drástico de datos móviles**: Reducción de más del 75% en ráfagas de red al unificar las publicaciones a un único tick cada 5 minutos.
- **Detección temprana de anomalías físicas**: Identificación inmediata de sensores descalibrados o desconectados antes de que contaminen catálogos sísmicos.
- **Acción remota protectora**: Capacidad de apagar remotamente la adquisición continua ante fallas no recuperables sin requerir acceso interactivo SSH.
- **Interoperabilidad completa con TIG**: Alimentación directa y homogénea para Telegraf y el motor jerárquico de alertas en Grafana (ADR-019).

### Negativas / Deuda Técnica
- Requiere permisos de `sudoers` sin contraseña para `systemctl stop rsa-acelerografo.service` bajo el usuario `rsa`.
- El comando `stop_acquisition_safety` es unidireccional por seguridad; para reiniciar la adquisición se requiere intervención explícita del operador (comando SSH o nuevo comando remoto de arranque).

---

## Referencias

- ADR relacionado: `019_modelo_jerarquico_alertas_y_visualizacion_grafana.md`
- Contextos técnicos:
  - [`docs/context/sensor_watchdog_context.md`](../context/sensor_watchdog_context.md)
  - [`docs/context/drive_watchdog_context.md`](../context/drive_watchdog_context.md)
  - [`docs/context/mqtt_coordinator_context.md`](../context/mqtt_coordinator_context.md)
- Blueprint de implementación:
  - [`docs/blueprints/2026-09-10_plan_implementacion_telemetria_sensor_adquisicion_drive.md`](../blueprints/2026-09-10_plan_implementacion_telemetria_sensor_adquisicion_drive.md)

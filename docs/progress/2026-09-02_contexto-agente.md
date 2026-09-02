# Resumen de Sesión: Plan de Resiliencia del Pipeline de Adquisición Post-Incidente CHA01

**Fecha**: 2026-09-02  
**Repositorio**: `acelerografo-DEV00`  
**Agente de IA**: Antigravity  
**Usuario**: Milton Muñoz  

---

## 🎯 Objetivo de la Sesión

Diseñar, implementar y certificar en hardware de producción las 4 fases del **Plan de Resiliencia del Pipeline de Adquisición** derivado del diagnóstico del incidente en CHA01 ([`2026-09-01_diagnostico_parada_adquisicion_cha01.md`](../analysis/2026-09-01_diagnostico_parada_adquisicion_cha01.md)). El objetivo central consistió en inmunizar la estación ante caídas del proceso en C (`registro_continuo`), desfasajes de hardware en el bus SPI por reinicios sin reset previo del dsPIC33, bloqueos en el FIFO `/tmp/my_pipe` y ausencia de telemetría de latencia en la red MQTT central.

---

## 📂 Estructura del Repositorio Implementada

```text
montajes/acelerografo-DEV00/
├── configuration/
│   └── configuracion_mqtt.json.template       # [MODIFICADO] Tópico y retención status_acquisition
├── docs/
│   ├── adr/
│   │   └── 018_resiliencia_pipeline_adquisicion_acelerografo.md  # [NUEVO] ADR formal en 4 capas
│   ├── blueprints/
│   │   └── 2026-09-02_plan_resiliencia_pipeline_adquisicion.md   # [NUEVO] Plan detallado y protocolo operativo
│   ├── context/
│   │   ├── acquisition_watchdog_context.md     # [NUEVO] Contexto técnico del watchdog de latencia
│   │   ├── mqtt_coordinator_context.md        # [MODIFICADO] Telemetría status/acquisition
│   │   ├── registro_continuo_context.md       # [MODIFICADO] Gobernanza systemd y reset_master
│   │   └── stream_processor_context.md        # [MODIFICADO] Reintentos con backoff exponencial
│   └── progress/
│       └── 2026-09-02_contexto-agente.md      # [NUEVO] Documento de transición técnica
├── scripts/
│   ├── operation/
│   │   ├── mqtt/
│   │   │   ├── acquisition_watchdog.py        # [NUEVO] Monitor periódico de frescura del Ring Buffer
│   │   │   ├── mqtt_coordinator.py            # [MODIFICADO] Integración de watchdog e intervalo 60s
│   │   │   └── test_acquisition_watchdog.py   # [NUEVO] Suite de 5 tests unitarios
│   │   └── streaming/
│   │       ├── stream_processor.py            # [MODIFICADO] _abrir_pipe_con_retry() con backoff
│   │       └── test_stream_processor.py       # [MODIFICADO] 20 tests unitarios aprobados
│   ├── setup/
│   │   ├── deploy.sh                          # [MODIFICADO] Instalación de rsa-acelerografo.service
│   │   └── update.sh                          # [MODIFICADO] update_systemd_service y sincronización
│   └── task/
│       ├── crontab.txt                        # [MODIFICADO] Eliminación de @reboot conflictivos
│       ├── registrocontinuo.sh                # [MODIFICADO] Gobernanza delegada a systemd
│       └── rsa-acelerografo.service.template  # [NUEVO] Plantilla systemd con Restart=always y reset_master
```

---

## ⚙️ Configuración del Entorno y Estado Operacional

- **Entorno de Adquisición**: Raspberry Pi 3B+ corriendo Linux Debian Bullseye (32-bit), entorno virtual en `/home/rsa/projects/acelerografo/.venv`.
- **Servicios Gobernados**:
  - `rsa-acelerografo.service` (Systemd / root): Proceso binario en C `registro_continuo_4.5.0` a 250 Hz sobre bus SPI.
  - Daemons de Supervisor (`stream_processor`, `gpd_stream_worker`, `mqtt_coordinator`, `config_server`) corriendo bajo usuario sin privilegios `rsa`.
- **IPC Validado**:
  - Named pipe `/tmp/my_pipe` (permisos `0666` incondicionales, apertura `O_RDWR | O_NONBLOCK`).
  - Memoria compartida `/dev/shm/rsa_current_frame` (protocolo Seqlock de 3024 bytes).
  - Ring Buffer en `/home/rsa/data/ring-buffer/` (archivos rotativos `ring_*.bin` de 5 min).

---

## 🛠️ Modificaciones de Código y Refactorización

### 1. Fase 1: Servicio Systemd Resiliente y Reseteo dsPIC33
- Se creó `rsa-acelerografo.service.template` con:
  - `Restart=always`, `RestartSec=5`, `StartLimitIntervalSec=300`, `StartLimitBurst=10`.
  - `ExecStartPre=/bin/rm -f /tmp/my_pipe`
  - `ExecStartPre={{PROJECT_LOCAL_ROOT}}/scripts/acelerografo/ejecutables/reset_master` (pulso en bajo a MCLR para resetear el dsPIC antes de iniciar SPI).
  - `ExecStopPost=/bin/rm -f /tmp/my_pipe`
- Se actualizaron `scripts/setup/deploy.sh` y `scripts/setup/update.sh` (función `update_systemd_service`).
- Se depuró `scripts/task/crontab.txt` eliminando `@reboot sleep 30 && resetmaster` y `@reboot sleep 180 && registrocontinuo start`.
- Se refactorizó `scripts/task/registrocontinuo.sh` delegando en `systemctl {start|stop|restart|status}`.

### 2. Fase 2: Defensa de Permisos del FIFO en C
- Verificación formal de que `chmod(PIPE_NAME, 0666)` se encuentra implementado en la línea 194 de `registro_continuo_4.5.0.c`.

### 3. Fase 3: Reintentos Resilientes en `stream_processor.py`
- Se reemplazó la apertura fail-fast por `_abrir_pipe_con_retry()`:
  - Backoff exponencial (`0.5s`, `1.0s`, `2.0s`, `4.0s`, `8.0s` techo) con timeout configurable `DEFAULT_PIPE_RETRY_MAX_S = 120`.
  - Manejo robusto de `FileNotFoundError` y `PermissionError`.
  - En `run()`, captura limpia de `RuntimeError` para salida controlada sin crashear en Supervisor.
- Se actualizaron los tests unitarios en `test_stream_processor.py` alcanzando 20/20 tests aprobados.

### 4. Fase 4: Watchdog de Latencia en `mqtt_coordinator.py`
- Se creó `scripts/operation/mqtt/acquisition_watchdog.py` (`AcquisitionWatchdog`) que audita en orden inverso el Ring Buffer y calcula `age_seconds`.
- Se integró un timer de 60 s en el bucle de `mqtt_coordinator.py` publicando en `{org}/{app}/{cap}/{id}/status/acquisition`:
  - `status: "ok"` cuando `age_seconds <= 300 s`.
  - `status: "warning"`, `reason: "stale_data"` cuando `age_seconds > 300 s`.
- Se añadió el comando bajo demanda `get_acquisition_status` en `CommandDispatcher`.
- Se añadieron 5 tests unitarios en `test_acquisition_watchdog.py` (5/5 tests aprobados).

---

## 🧪 Validaciones Empíricas en Estación (`ACEL-DEVP-UNIV-01`)

1. **Batería de Estrés de Fase 1**:
   - Caída súbita (`kill -9`): Auto-reinicio verificado en $\le 5$ s con regeneración de `.dat` activo.
   - FIFO corrupto (`chmod 000`): `ExecStartPre` purgó el pipe y restauró permisos `prw-rw-rw-` (`0666`).
   - Ráfagas sucesivas (3 caídas en 20 s): 100% recuperadas sin alcanzar `StartLimitBurst`.
   - Rotación y subida: `registrocontinuo restart` convirtió a MiniSEED y subió a Google Drive (`upload_resumen=1/1 | success`).
2. **Resiliencia de Fase 3**:
   - `stream_processor` reiniciado sin FIFO activo: esperó pacientemente 24 s aplicando backoff exponencial (`[PIPE_WAIT]`) y se auto-conectó de inmediato (`[PIPE_OPEN]`) al ejecutar `registrocontinuo start`.
3. **Telemetría en Vivo de Fase 4**:
   - Logs de producción reportando `[ACQUISITION_OK] Adquisición nominal: age=1.2s`.
   - Broker MQTT verificado vía MQTT Explorer recibiendo el JSON con `age_seconds: 1.6s`.

---

## 📋 Pasos Sugeridos para el Siguiente Agente

1. **Despliegue Global en Estaciones de Campo**:
   - Conectar vía SSH a las 5 estaciones acelerográficas restantes de la red RSA (incluyendo CHA01).
   - Realizar `git pull` en `/home/rsa/git/RSA-Acelerografo` y ejecutar `./menu.sh` (opción 3) para desplegar el servicio systemd, los scripts de streaming y el watchdog MQTT.
2. **Ingesta Central en Servidor TIG**:
   - Verificar que Telegraf en el servidor central esté suscrito a `rsa/seismic/smart/+/status/acquisition` e indexe `age_seconds` y `status` en InfluxDB.
   - Configurar paneles de alerta en Grafana ante métricas `age_seconds > 300` o `status == "warning"`.
3. **Diagnóstico de Automatización de Despliegues**:
   - Abordar el backlog del documento [`2026-09-01_diagnostico_automatizacion_despliegue.md`](../analysis/2026-09-01_diagnostico_automatizacion_despliegue.md) para la segregación definitiva de ramas `main`/`develop` y actualización OTA automatizada vía comando MQTT broadcast.

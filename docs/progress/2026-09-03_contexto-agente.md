# Resumen de Sesión: Auto-habilitación de Systemd en Boot y Espera Dinámica de Sincronización NTP

**Fecha**: 2026-09-03  
**Repositorio**: `acelerografo-DEV00`  
**Agente de IA**: Antigravity  
**Usuario**: Milton Muñoz  

---

## 🎯 Objetivo de la Sesión

Diagnosticar y resolver dos anomalías operativas observadas tras el reinicio en caliente (`sudo reboot`) de la estación de desarrollo `ACEL-DEVP-UNIV-01`:
1. **Falta de Auto-arranque en Boot**: El servicio `rsa-acelerografo.service` permanecía en estado `disabled` tras actualizaciones mediante `update.sh` (Opción 3 de `menu.sh`), impidiendo que Systemd lo iniciara automáticamente al encender la Raspberry Pi.
2. **Arranque Prematuro sin Sincronización NTP**: `registro_continuo` iniciaba en apenas 1-2 segundos tras el arranque, antes de que el demonio `ntpd` completara la negociación con los servidores remotos, generando un `WARNING` en los logs y arriesgando saltos temporales bruscos en los archivos `.dat` y el Ring Buffer.

---

## 📂 Estructura del Repositorio Implementada

```text
montajes/acelerografo-DEV00/
├── docs/
│   ├── context/
│   │   ├── registro_continuo_context.md       # [MODIFICADO] Integración de wait_for_ntp y auto-enable
│   │   └── wait_for_ntp_context.md            # [NUEVO] Contexto técnico del helper de sincronización
│   └── progress/
│       └── 2026-09-03_contexto-agente.md      # [NUEVO] Documento de transición técnica
├── scripts/
│   ├── setup/
│   │   └── update.sh                          # [MODIFICADO] Auto-enable incondicional de systemd
│   └── task/
│       ├── rsa-acelerografo.service.template  # [MODIFICADO] ExecStartPre=/usr/local/bin/wait_for_ntp 120
│       └── wait_for_ntp.sh                    # [NUEVO] Helper de espera activa con timeout 120s
```

---

## ⚙️ Configuración del Entorno y Estado Operacional

- **Hardware**: Raspberry Pi 3B+ en estación `ACEL-DEVP-UNIV-01` con conexión SSHFS en tiempo real.
- **Servicio Systemd**: `rsa-acelerografo.service` gobernando el binario en C `registro_continuo_4.5.0` con permisos de root para bus SPI.
- **Estado de Habilitación**: `systemctl is-enabled rsa-acelerografo.service` verificado en estado `enabled`.
- **Reloj del Sistema**: Sincronización gobernada por `ntpd` / `ntpstat` y auditada antes de la apertura de archivos.

---

## 🛠️ Modificaciones de Código y Refactorización

### 1. Script Helper de Sincronización (`scripts/task/wait_for_ntp.sh`)
- Se creó un script en Bash que realiza un sondeo cada 2 segundos a `ntpstat` (con fallbacks a `timedatectl` y `chronyc`).
- **Respuesta Instantánea**: En cuanto el reloj se sincroniza (típicamente entre 50 y 90 segundos tras encendido en frío), el script retorna `exit 0` inmediatamente, liberando el arranque de la adquisición.
- **Resiliencia Offline**: Si la estación está en campo sin enlace de red, al vencer el timeout configurable de **120 segundos**, emite una advertencia y retorna `exit 0`, asegurando que la adquisición arranque sin bloquear el servicio de Systemd.

### 2. Plantilla de Servicio Systemd (`scripts/task/rsa-acelerografo.service.template`)
- Se integró la directiva: `ExecStartPre=/usr/local/bin/wait_for_ntp 120`.
- Se especificó `After=network.target local-fs.target`.

### 3. Automatización de Actualización (`scripts/setup/update.sh`)
- Se modificó la función `update_systemd_service`:
  - Se añadió `sudo systemctl enable rsa-acelerografo.service` al copiar la nueva plantilla.
  - Se añadió una verificación incondicional: si el servicio se detecta en estado `disabled`, `update.sh` ejecuta `enable` automáticamente.

---

## 🧪 Validaciones Empíricas en Estación (`ACEL-DEVP-UNIV-01`)

1. **Despliegue con `menu.sh` (Opción 3)**:
   - Salida confirmada: `Actualizando: /usr/local/bin/wait_for_ntp` y `Actualizando servicio systemd: rsa-acelerografo.service`.
   - `systemctl is-enabled` retornó `enabled`.
2. **Reinicio en Frío (`sudo reboot`)**:
   - Shutdown a las `17:00:05` $\rightarrow$ Login disponible a las `17:00:18` (13 s).
   - `wait_for_ntp` retuvo la ejecución durante ~93 segundos mientras `ntpd` negociaba con los servidores.
   - `registro_continuo` arrancó a las **`17:01:53`** registrando:
     `INFO - Sincronizacion NTP: Si` (eliminando completamente el `WARNING`).
   - El archivo `DEV0_260903-170154.dat` y la hora transmitida al dsPIC33 nacieron con hora atómica exacta.
3. **Métrica de Rendimiento**:
   - Frente al viejo método del crontab (`sleep 180` fijo $\rightarrow$ ~193 s totales), el nuevo método dinámico arrancó en **108 segundos**, logrando un **ahorro neto de 85 segundos (44% más rápido)** y garantizando la integridad de datos desde el segundo 0.

---

## 📋 Pasos Sugeridos para el Siguiente Agente

1. **Retomar Diagnóstico en el Stack TIG (`RSA-Intern-TIG-MQTT`)**:
   - Cambiar el directorio de trabajo al repositorio del servidor Ubuntu (`montajes/server-ubuntu/rsa/RSA-Intern-TIG-MQTT`).
   - Ejecutar la skill `planning_guide` para generar el blueprint de implementación a partir del diagnóstico [`2026-09-02_diagnostico_ingesta_telemetria_status_acquisition.md`](file:///home/rsa/git/montajes/server-ubuntu/rsa/RSA-Intern-TIG-MQTT/docs/analysis/2026-09-02_diagnostico_ingesta_telemetria_status_acquisition.md).
   - Configurar el consumidor `inputs.mqtt_consumer` en `telegraf.conf` para persistir la métrica `station_acquisition` en InfluxDB y crear el panel de semáforo en Grafana.
2. **Despliegue en la Flota de Campo**:
   - Realizar la actualización en las demás estaciones acelerográficas de la red (especialmente CHA01) ejecutando `menu.sh` opción 3 para extender la auto-habilitación y la sincronización `wait_for_ntp`.

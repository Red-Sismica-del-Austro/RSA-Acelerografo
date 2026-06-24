---
id: ADR-003
titulo: wifi_ap_aislamiento_firewall
estado: Aceptado
fecha: 2026-06-04
temas: [wifi, seguridad, redes]
entorno: [acelerografo]
---

# ADR-003: Punto de Acceso WiFi con Aislamiento de Firewall

## Estado

**Aceptado** | Fecha: 2026-06-04

## Contexto

Para configurar el acelerógrafo en el campo a través del panel web de administración desde un dispositivo móvil, es necesario configurar la Raspberry Pi como un Punto de Acceso (AP) WiFi temporal y seguro usando la interfaz `wlan0`. 

Sin embargo, las estaciones de monitoreo están conectadas de forma permanente a internet o a las intranets de las universidades mediante cable de red a través de la interfaz Ethernet (`eth0`). Si el servidor Flask escucha en todas las interfaces de red (`0.0.0.0`) para que el móvil pueda acceder desde la red inalámbrica `wlan0`, el panel de administración web (puerto `5000`) también se vuelve visible y vulnerable desde la red externa a través de `eth0`. 

Dado que en esta fase de despliegue el panel web de configuración no cuenta con autenticación HTTP (Basic Auth o JWT) y depende enteramente del aislamiento físico, es un requisito crítico de seguridad bloquear cualquier acceso no autorizado por el cable de red.

## Opciones Evaluadas

### Opción A: Configurar Flask para escuchar en la IP inalámbrica y Basic Auth
Hacer que Flask escuche específicamente en la IP estática asignada al AP WiFi (`192.168.4.1`) e implementar Basic Auth en el código Python de Flask.
- **Ventajas:**
  - Evita escuchar en `eth0` de forma nativa por diseño en la capa de transporte del software.
  - Mayor seguridad de acceso mediante credenciales de usuario.
- **Desventajas:**
  - Si el AP WiFi se desactiva en el laboratorio para pruebas, el daemon Flask fallará al arrancar debido a que la IP `192.168.4.1` no existirá en la interfaz `wlan0` (Flask no soporta bindings dinámicos nativamente sin reinicios del daemon).
  - Bloquea la flexibilidad de depurar localmente en la RPi a través del host localhost `127.0.0.1`.

### Opción B: Escuchar en 0.0.0.0 y aislar con reglas dinámicas de firewall (iptables)
Permitir que Flask escuche en todas las interfaces (`0.0.0.0:5000`) y usar el script de control `/usr/local/bin/wifiap` para inyectar una regla de firewall en `iptables` que rechace todo el tráfico entrante al puerto 5000 por la interfaz `eth0` mientras el AP esté encendido.
- **Ventajas:**
  - Permite que Flask funcione de forma continua y flexible (permite el acceso local `127.0.0.1` para túneles SSH y depuración, y el acceso por `192.168.4.1` al conectar el móvil).
  - Aísla la interfaz de red Ethernet `eth0` a nivel de kernel de Linux de forma sumamente robusta mediante `iptables`.
  - La seguridad se gestiona de forma centralizada por el script de control de red del sistema.
- **Desventajas:**
  - Dependencia de herramientas de sistema (`iptables` y `sudo`).
  - Si el script `wifiap` termina abruptamente con un error antes de desactivarse, la regla de firewall podría quedar en el sistema (lo cual es seguro pero requiere limpieza).

## Decisión

Se eligió la **Opción B (0.0.0.0 con iptables dinámico)**.

Esta opción permite conservar la flexibilidad de acceso del panel web para tareas de mantenimiento remotas (vía túnel SSH apuntando a localhost `127.0.0.1:5000`), al mismo tiempo que garantiza que, cuando el AP WiFi está activo para la configuración inalámbrica local en campo, el puerto `5000` de Flask quede completamente invisible para escaneos y conexiones externas provenientes del cable Ethernet (`eth0`). El script de control de red `/usr/local/bin/wifiap` asume la responsabilidad de aplicar la regla de firewall al activar el AP (`wifiap enable`) y removerla al apagarlo (`wifiap disable`).

## Consecuencias

- **Aislamiento Robusto:** Mitigación de riesgos de accesos no autorizados a la API de configuración desde redes institucionales externas cableadas.
- **Flexibilidad de Mantenimiento:** Los daemons Flask y Supervisor no requieren reinicios complejos de host y conservan el soporte para túneles SSH.
- **Requisito de Privilegios:** Se requiere acceso root a través de un perfil de sudoers restrictivo (`/etc/sudoers.d/rsa-wifiap`) para que el usuario web `rsa` pueda manipular el AP y aplicar reglas de `iptables`.

## Decisiones Adicionales (Sesión de Depuración - Tarde 2026-06-04)

### 1. SSID Fijo vs Dinámico
- **Contexto:** Inicialmente se planteó estructurar el SSID del WiFi AP de manera dinámica usando el identificador de la estación (`ACEL-{{ESTACION_ID}}-CONFIG`). Sin embargo, dado que el `estacion_id` se puede modificar desde el panel web de configuración, si un técnico cambia este parámetro estando conectado vía WiFi, la comunicación se cortaría abruptamente al cambiar el SSID dinámico en caliente.
- **Decisión:** Se definió utilizar un SSID estático fijo (`ACEL-CONFIG`) en la configuración maestra. El script de hidratación reemplaza el marcador y genera la plantilla de `hostapd` usando este valor estático.
- **Consecuencia:** Mayor estabilidad en operaciones de campo. El personal de soporte técnico puede cambiar el ID de la estación y reconfigurar el dispositivo sin perder la conectividad de la red WiFi local.

### 2. Robustez en la inicialización (Unmask automático de hostapd)
- **Contexto:** En Debian/Raspbian OS, el paquete `hostapd` suele estar enmascarado por defecto al instalarse, lo que bloquea su arranque e impide la activación del AP con errores del tipo `Unit hostapd.service is masked.`.
- **Decisión:** Se integró la orden `systemctl unmask hostapd 2>/dev/null || true` en las secciones de instalación (`do_install`) y activación (`do_enable`) dentro del script de control `/usr/local/bin/wifiap`.
- **Consecuencia:** Prevención de fallos silenciosos en la puesta en marcha de estaciones y despliegue robusto del Punto de Acceso.

## Referencias

- Sesión de origen: [2026-06-04_wifi_ap_seguro.md](file:///home/rsa/git/institucional/RSA-Bitacora-LLM-Milton/sesiones/2026/06/2026-06-04_wifi_ap_seguro.md)
- Contexto técnico relacionado: [wifiap.sh](file:///home/rsa/git/montajes/acelerografo-DEV00/scripts/task/wifiap.sh)
- Configuración maestra: [configuracion_maestra.json](file:///home/rsa/git/montajes/acelerografo-DEV00/configuration/configuracion_maestra.json)


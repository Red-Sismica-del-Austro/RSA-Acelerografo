---
proyecto: acelerografo-rsa
tipo: contexto_tecnico
archivo: scripts/operation/web/
temas: [web, flask, configuracion, html, javascript]
generado: 2026-06-10
---
# Entorno Web de Configuración — Contexto para Agentes IA

> Servidor web interactivo y seguro basado en Flask y Vanilla JS para la configuración en caliente del acelerógrafo.

**Ruta**: `scripts/operation/web/`  
**LOC**: ~1500 (combinado) | **Lenguaje**: Python, HTML, JavaScript | **Dependencias**: Flask, Supervisor, Vanilla JS, CSS  
**Proceso**: Gestionado por Supervisor daemon en `/etc/supervisor/conf.d/config_server.conf` ejecutando `config_server.py`.

---

## Arquitectura

El servidor de configuración web Flask se ejecuta en segundo plano. Permite editar de manera interactiva la configuración maestra (`configuracion_maestra.json`), aplicar los cambios en caliente ejecutando la hidratación, y reiniciar los servicios del sistema sin intervención de comandos directos en consola.

```mermaid
graph TD
    A[Usuario Móvil (WiFi AP) / PC (SSH Tunnel)] -->|HTTP GET/POST /api/config| B[config_server.py (Flask)]
    B -->|Lee/Escribe con fcntl LOCK_EX| C[configuracion_maestra.json]
    B -->|Subproceso: python3| D[hidratar_configuracion.py]
    D -->|Genera| E[Archivos de runtime .json y hostapd.conf]
    B -->|Subproceso: sudo supervisorctl / registrocontinuo| F[Reinicio de servicios: registro_continuo y mqtt_coordinator]
    A -->|HTTP GET /api/check| B
    B -->|Subproceso: python3| G[comprobar_registro_wrapper.py]
    G -->|Subproceso: ejecutable C| H[comprobar_registro binario]
    H -->|stdout parseado a JSON| G
    G -->|JSON estructurado| B
    B -->|JSON campos separados| A
```

---

## Configuraciones / Variables de Entorno y Puertos

- **Puerto:** `5000` (escucha en `0.0.0.0` para recibir conexiones del WiFi AP).
- **Aislamiento de Firewall:** Cuando el AP está activo, `wifiap.sh` inserta reglas de `iptables` que bloquean las peticiones al puerto `5000` entrantes por la interfaz cableada `eth0`, restringiendo el acceso exclusivamente a `wlan0` (WiFi AP) y `lo` (localhost).
- **Supervisor Config (`config_server.conf`):**
  - Comando: `$PROJECT_LOCAL_ROOT/.venv/bin/python3 config_server.py`
  - Variables: `PROJECT_LOCAL_ROOT` (ej. `/home/rsa/projects/acelerografo-rsa`), `PROJECT_GIT_ROOT` (ej. `/home/rsa/git/RSA-Acelerografo`).
  - Logs: `config_server.out.log` y `config_server.err.log` en el directorio de logs.

---

## Componentes / Funciones / Servicios Clave

### Backend (`config_server.py`)
| Elemento | Descripción |
|----------|-------------|
| `_validar_configuracion(data)` | Valida tipos, límites y expresiones regulares (regex) de cada campo (allow-list estricta). |
| `_ejecutar_subproceso(cmd, desc)` | Ejecución segura de subprocesos usando arrays de comandos sin `shell=True`. |
| `_comprobar_registro()` | Invoca `comprobar_registro_wrapper.py` con timeout 15s y retorna su salida JSON. |
| `get_config()` | Endpoint `/api/config` [GET] para leer la configuración de la estación. |
| `post_config()` | Endpoint `/api/config` [POST] para escribir, respaldar (`.bak`), hidratar y reiniciar daemons. |
| `get_check()` | Endpoint `/api/check` [GET] que ejecuta el diagnóstico y retorna datos estructurados. |
| `get_status()` | Endpoint `/api/status` [GET] que reporta el estado operativo de los daemons principales. |

### Wrapper de Diagnóstico (`comprobar_registro_wrapper.py`)
| Elemento | Descripción |
|----------|-------------|
| **Ruta** | `scripts/operation/acelerografo/comprobar_registro_wrapper.py` |
| **Propósito** | Ejecutar el binario C `comprobar_registro`, parsear su stdout a JSON estructurado. |
| **Salida** | JSON con campos: `hora_sistema`, `nombre_archivo`, `tamano_archivo`, `fuente_reloj`, `hora_uc`, `aceleracion_x/y/z`, `error_reloj`. |
| **Fallback** | Si el parseo falla, incluye `salida_cruda` en el JSON de error para depuración. |

### Frontend (`index.html` & `app.js`)
| Elemento | Descripción |
|----------|-------------|
| `recogerPayload()` | Serializa los inputs del DOM y preserva los campos ocultos (como los IDs de Drive). |
| `validarPayload(p)` | Duplica en cliente la lógica de validación de inputs y regex para feedback interactivo. |
| `mostrarDiffEnModal()` | Compara la configuración previa con la nueva y despliega los cambios en el modal. |
| `comprobarRegistro()` | Llama a `/api/check`, recibe JSON estructurado y construye el grid de diagnóstico con `createElement`/`textContent`. |
| `_crearTarjetaDato()` | Construye una tarjeta DOM individual para el grid de resultados del diagnóstico. |
| `_claseReloj()` | Determina el color semántico de la fuente de reloj (verde=GPS, amarillo=RTC, azul=RPi, rojo=Error). |
| Auto-capitalización | Listeners en tiempo real para capitalizar el código de estación (`estacion_id`) y el nombre completo (`nombre`). |

---

## Limitaciones Conocidas / TODOs

- **Autenticación (TODO):** Actualmente la seguridad depende del aislamiento físico del AP y de túneles SSH. Falta implementar Basic Auth o JWT en Flask para blindar el puerto en red abierta.
- **CSRF Protection (TODO):** Implementar tokens CSRF en formularios si se llega a habilitar autenticación persistente basada en cookies.
- **Rollback Parcial:** Si la hidratación falla, se restaura el backup. Pero si el fallo ocurre al reiniciar los servicios, el JSON se guarda con los nuevos datos aunque los daemons no hayan levantado (el rollback no es transaccional a nivel de daemons).
- **Diagnóstico — Dependencia del binario compilado:** El endpoint `/api/check` requiere que el binario `comprobar_registro` esté compilado y disponible en `$PROJECT_LOCAL_ROOT/scripts/acelerografo/ejecutables/`. Si no existe (ej. en instalación nueva antes de compilar), el endpoint retornará error 500.
- **Diagnóstico — Parseo frágil de la salida C:** El wrapper parsea la salida del programa C con regex. Si el formato de `comprobar_registro_5.x.x.c` cambia en futuras versiones, las regex deberán actualizarse en `comprobar_registro_wrapper.py`.

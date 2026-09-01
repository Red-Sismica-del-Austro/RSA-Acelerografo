## Flujo de Trabajo

```mermaid
graph TD
    Start((Inicio)) --> Menu[bash menu.sh]
    Menu --> Op4[4. Limpieza Global]
    Op4 --> Op1[1. Instalación Sistema + Venv]
    Op1 --> Op2[2. Desplegar / 3. Actualizar]
    Op2 --> End((Fin))
    
    style Op4 stroke-dasharray: 5 5
    note[Nota: Opción 4 solo si hay basura global]
```

## Configurar una Nueva Estación
Para configurar una estación por primera vez, siga los siguientes pasos:

1. Ejecute el menú con el comando `bash menu.sh`.
2. Seleccione la opción 0 para establecer las variables de entorno.
3. Seleccione la opción 1 para instalar las librerías del sistema y crear el entorno virtual de Python.
4. Seleccione la opción 2 para desplegar el proyecto.

## Actualizar el Proyecto a la Última Versión Disponible
Para actualizar el proyecto, siga los siguientes pasos:

1. Obtenga la última versión del repositorio mediante el comando `git pull`.
2. Ejecute el menú y seleccione la opción 3. Esto sincroniza los scripts, recompila los programas en C y actualiza el entorno virtual si `requirements.txt` ha cambiado.

## Migrar de Instalación Global a Entorno Virtual
Si el equipo tiene librerías de Python instaladas globalmente con `pip3`, es necesario desinstalarlas antes de usar el entorno virtual:

1. Ejecute el menú y seleccione la opción 4 para desinstalar las librerías globales de Python.
2. Seleccione la opción 1 para reinstalar las librerías del sistema y crear el entorno virtual.

## Opciones del Menú

| Opción | Descripción |
|--------|-------------|
| 0 | Establecer variables de entorno |
| 1 | Instalar librerías del sistema y crear entorno virtual de Python |
| 2 | Desplegar el proyecto (solo configuración inicial) |
| 3 | Actualizar el proyecto |
| 4 | Desinstalar librerías globales de Python |
| 5 | Salir |

# Importante

## Entorno Virtual de Python
Los scripts de Python se ejecutan desde un entorno virtual ubicado en `$PROJECT_LOCAL_ROOT/.venv/`. Las dependencias se definen en `requirements.txt`. No instale paquetes de Python globalmente con `sudo pip3 install`.

## Rutas de los Directorios del Proyecto
Es muy importante que las rutas definidas en el archivo de configuración `configuracion_dispositivo.json` coincidan con las variables de entorno definidas en el archivo `/scripts/env/project_paths.sh`.

## Backups de Archivos de Configuración
Antes de realizar una actualización, respalde el directorio de configuración con todos sus archivos.

## 🌐 Panel Web de Configuración
El proyecto incluye un servidor de configuración web Flask (`config_server.py`) que expone una interfaz interactiva para modificar la configuración de forma segura en caliente.
* **Ubicación local:** `$PROJECT_LOCAL_ROOT/scripts/web/`
* **Servicio:** Administrado mediante Supervisor (`config_server`).
* **Seguridad:** Escucha en `0.0.0.0:5000` pero está protegido contra accesos externos vía Ethernet (`eth0`) por reglas de firewall aplicadas automáticamente al encender el AP.

## 📶 Administración del Punto de Acceso WiFi (AP)
Para configurar el acelerógrafo en el campo desde un dispositivo móvil, se utiliza el script de control `/usr/local/bin/wifiap`.

### Comandos de control (ejecutar con `sudo`):
* **Instalar dependencias e inicializar (solo la primera vez):**
  ```bash
  sudo wifiap install
  ```
  Esto instala `hostapd` y `dnsmasq`, desabilita el arranque automático por defecto y configura el alias DNS `config.local` que resuelve a `192.168.4.1`.
  
* **Activar el AP WiFi:**
  ```bash
  sudo wifiap enable
  ```
  Esto configura la IP estática `192.168.4.1` en `wlan0`, inicia el AP oculto y configura una regla en `iptables` que bloquea el acceso al puerto `5000` desde la interfaz Ethernet cableada (`eth0`).

* **Desactivar el AP WiFi:**
  ```bash
  sudo wifiap disable
  ```
  Esto apaga el AP, elimina la configuración estática de `dhcpcd` y restaura el estado limpio de red.

* **Consultar estado:**
  ```bash
  sudo wifiap status
  ```

### Acceso desde el móvil:
1. Conectarse a la red WiFi del acelerógrafo (por defecto el SSID tiene la estructura `ACEL-NOM00-CONFIG`, donde `NOM00` es el ID del dispositivo. Se configura en `configuracion_maestra.json`). Al ser una red oculta, se debe añadir de manera manual e ingresar la contraseña establecida.
2. Abrir en el navegador la dirección: `http://192.168.4.1:5000` o `http://config.local:5000`.


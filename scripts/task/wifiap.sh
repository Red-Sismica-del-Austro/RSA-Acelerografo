#!/bin/bash

# Script de Control de WiFi AP para Acelerógrafo RSA
# Debe ser instalado en /usr/local/bin/wifiap y correr con privilegios sudo.

# Cargar variables de entorno si existen
if [ -f "/etc/profile.d/project_paths.sh" ]; then
    source /etc/profile.d/project_paths.sh
elif [ -f "/usr/local/bin/project_paths" ]; then
    source /usr/local/bin/project_paths
fi

# Fallback si no están definidas
PROJECT_LOCAL_ROOT=${PROJECT_LOCAL_ROOT:-"/home/rsa/projects/acelerografo-rsa"}

DHCPCD_CONF="/etc/dhcpcd.conf"
DNSMASQ_AP_CONF="/etc/dnsmasq.d/wifiap.conf"
HOSTAPD_CONF="/etc/hostapd/hostapd.conf"
LOCAL_HOSTAPD_SRC="$PROJECT_LOCAL_ROOT/configuracion/hostapd.conf"

# Asegurar que se ejecuta como root (a través de sudo)
if [ "$EUID" -ne 0 ]; then
  echo "Error: Este script debe ser ejecutado con privilegios de root (sudo)."
  exit 1
fi

show_usage() {
    echo "Uso: sudo wifiap {install|enable|disable|status}"
    exit 1
}

do_install() {
    echo "=== Instalando y configurando dependencias de WiFi AP ==="
    
    # 1. Instalar paquetes si no están instalados
    echo "Comprobando paquetes hostapd y dnsmasq..."
    apt-get update -qq
    apt-get install -y hostapd dnsmasq rfkill
    
    # 2. Deshabilitar los servicios para que no arranquen por defecto al bootear
    echo "Deshabilitando servicios para control a demanda..."
    systemctl unmask hostapd 2>/dev/null || true
    systemctl disable hostapd dnsmasq
    systemctl stop hostapd dnsmasq 2>/dev/null || true
    
    # 3. Crear configuración de dnsmasq dedicada para wlan0
    echo "Configurando dnsmasq..."
    mkdir -p /etc/dnsmasq.d
    cat > "$DNSMASQ_AP_CONF" <<EOF
# Configuración de AP para wlan0 de la RSA
interface=wlan0
dhcp-range=192.168.4.2,192.168.4.20,255.255.255.0,24h
domain=local
address=/config.local/192.168.4.1
EOF
    
    echo "Instalación completada con éxito. Asegúrate de hidratar la configuración antes de habilitar."
}

do_enable() {
    echo "=== Activando Punto de Acceso WiFi (AP) ==="
    
    # 1. Comprobar que existe la configuración hidratada de hostapd
    if [ ! -f "$LOCAL_HOSTAPD_SRC" ]; then
        echo "Error: No se encontró la configuración hidratada del AP en:"
        echo "  $LOCAL_HOSTAPD_SRC"
        echo "Ejecuta primero la hidratación de configuración."
        exit 1
    fi
    
    # 2. Copiar configuración de hostapd y asegurar permisos seguros (sólo root)
    echo "Copiando configuración de hostapd..."
    cp "$LOCAL_HOSTAPD_SRC" "$HOSTAPD_CONF"
    chown root:root "$HOSTAPD_CONF"
    chmod 600 "$HOSTAPD_CONF"
    
    # 3. Modificar dhcpcd.conf si no se ha agregado la configuración estática
    if ! grep -q "# --- RSA WIFI AP START ---" "$DHCPCD_CONF"; then
        echo "Configurando IP estática para wlan0 en dhcpcd..."
        # Respaldar original
        cp "$DHCPCD_CONF" "${DHCPCD_CONF}.bak"
        
        # Escribir la IP estática y el bloqueo de wpa_supplicant
        cat >> "$DHCPCD_CONF" <<EOF

# --- RSA WIFI AP START ---
interface wlan0
    static ip_address=192.168.4.1/24
    nohook wpa_supplicant
# --- RSA WIFI AP END ---
EOF
    fi
    
    # 4. Asegurar que la interfaz no está bloqueada por hardware o software
    rfkill unblock wlan
    
    # 5. Reiniciar los servicios de red e iniciar el AP
    echo "Reiniciando servicios de red..."
    ip link set wlan0 down 2>/dev/null || true
    systemctl restart dhcpcd
    sleep 2
    ip link set wlan0 up
    
    echo "Iniciando dnsmasq..."
    systemctl restart dnsmasq
    
    echo "Iniciando hostapd..."
    systemctl unmask hostapd 2>/dev/null || true
    systemctl restart hostapd
    
    # 6. Proteger el puerto 5000 en eth0 para evitar acceso externo no autenticado
    echo "Aplicando regla de firewall (iptables) para proteger eth0 en el puerto 5000..."
    iptables -D INPUT -p tcp -i eth0 --dport 5000 -j DROP 2>/dev/null || true
    iptables -A INPUT -p tcp -i eth0 --dport 5000 -j DROP
    
    echo "Punto de Acceso WiFi habilitado."
    echo "SSID y configuración aplicados. IP del AP: 192.168.4.1"
}

do_disable() {
    echo "=== Desactivando Punto de Acceso WiFi (AP) ==="
    
    # 1. Detener servicios de AP
    echo "Deteniendo hostapd y dnsmasq..."
    systemctl stop hostapd dnsmasq 2>/dev/null || true
    
    # 2. Remover regla de firewall de iptables
    echo "Removiendo regla de firewall de iptables..."
    iptables -D INPUT -p tcp -i eth0 --dport 5000 -j DROP 2>/dev/null || true
    
    # 3. Remover configuración del AP en dhcpcd.conf si existe
    if grep -q "# --- RSA WIFI AP START ---" "$DHCPCD_CONF"; then
        echo "Removiendo configuración de IP estática de dhcpcd..."
        # Respaldar antes de editar
        cp "$DHCPCD_CONF" "${DHCPCD_CONF}.bak"
        
        # Eliminar el bloque
        sed -i '/# --- RSA WIFI AP START ---/,/# --- RSA WIFI AP END ---/d' "$DHCPCD_CONF"
    fi
    
    # 4. Reiniciar interfaz y dhcpcd
    echo "Restaurando interfaz wlan0..."
    ip link set wlan0 down 2>/dev/null || true
    systemctl restart dhcpcd
    sleep 1
    
    echo "Punto de Acceso WiFi deshabilitado de forma limpia."
}

do_status() {
    echo "=== Estado del AP WiFi ==="
    
    local hostapd_active=$(systemctl is-active hostapd 2>/dev/null)
    local dnsmasq_active=$(systemctl is-active dnsmasq 2>/dev/null)
    local wlan0_ip=$(ip addr show wlan0 2>/dev/null | grep -oE 'inet 192\.168\.4\.[0-9]+/[0-9]+')
    
    echo "Servicio hostapd (AP): $hostapd_active"
    echo "Servicio dnsmasq (DHCP/DNS): $dnsmasq_active"
    
    if [ -n "$wlan0_ip" ]; then
        echo "IP asignada en wlan0: $wlan0_ip (AP activo)"
    else
        echo "IP asignada en wlan0: Ninguna o no está en rango AP (AP inactivo)"
    fi
}

case "$1" in
    install)
        do_install
        ;;
    enable)
        do_enable
        ;;
    disable)
        do_disable
        ;;
    status)
        do_status
        ;;
    *)
        show_usage
        ;;
esac

exit 0

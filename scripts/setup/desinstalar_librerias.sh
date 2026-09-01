#!/bin/bash
set -euo pipefail

echo "=== Desinstalando librerías Python instaladas globalmente ==="
echo ""

# Paquetes pip a desinstalar (los que instalaba instalar_librerias.sh con sudo pip3)
PAQUETES_PIP=(
    "python-dotenv"
    "paho-mqtt"
    "google-api-python-client"
    "google-auth-httplib2"
    "google-auth-oauthlib"
    "google-auth"
    "oauth2client"
    "httplib2"
    "obspy"
    "numpy"
    "matplotlib"
    "scipy"
)

echo "Desinstalando paquetes pip globales..."
for paquete in "${PAQUETES_PIP[@]}"; do
    if pip3 show "$paquete" > /dev/null 2>&1; then
        echo "  Desinstalando: $paquete"
        sudo pip3 uninstall -y "$paquete"
    else
        echo "  No encontrado: $paquete (ya desinstalado o no instalado via pip)"
    fi
done

echo ""
echo "=== Desinstalación completada ==="
echo ""
echo "Verifique los paquetes restantes con: pip3 list"
echo "Los paquetes de apt (python3-numpy, python3-scipy, etc.) NO se desinstalan."
echo ""

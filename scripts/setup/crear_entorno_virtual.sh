#!/bin/bash
set -euo pipefail

# Validar variables de entorno
if [ -z "${PROJECT_LOCAL_ROOT:-}" ] || [ -z "${PROJECT_GIT_ROOT:-}" ]; then
    echo "ERROR: Las variables PROJECT_LOCAL_ROOT y PROJECT_GIT_ROOT deben estar definidas"
    exit 1
fi

VENV_DIR="$PROJECT_LOCAL_ROOT/.venv"
REQUIREMENTS="$PROJECT_GIT_ROOT/requirements.txt"

echo "=== Creando entorno virtual en: $VENV_DIR ==="
echo ""

# Asegurar que python3-venv está instalado
if ! dpkg -l python3-venv 2>/dev/null | grep -q "^ii"; then
    echo "Instalando python3-venv..."
    sudo apt-get install -y python3-venv
fi

# Eliminar venv anterior si existe
if [ -d "$VENV_DIR" ]; then
    echo "Eliminando entorno virtual anterior..."
    rm -rf "$VENV_DIR"
fi

# Crear el entorno virtual CON acceso a paquetes del sistema
# Esto hereda numpy, scipy, matplotlib instalados via apt
echo "Creando venv con --system-site-packages..."
python3 -m venv --system-site-packages "$VENV_DIR"

# Activar el venv y actualizar pip
source "$VENV_DIR/bin/activate"
pip install --upgrade pip

# Instalar dependencias desde requirements.txt
# --upgrade fuerza la instalación en el venv aunque existan versiones del sistema
# Esto es necesario porque pyopenssl y matplotlib del sistema son incompatibles
# con las versiones de cryptography y numpy que requieren las otras dependencias
if [ -f "$REQUIREMENTS" ]; then
    echo "Instalando dependencias desde requirements.txt..."
    pip install --upgrade -r "$REQUIREMENTS"
else
    echo "ADVERTENCIA: No se encontró $REQUIREMENTS"
fi

# Verificar todos los paquetes críticos
echo ""
echo "=== Verificando paquetes del entorno virtual ==="
python3 -c "import numpy; print('  numpy:', numpy.__version__)" || echo "  ERROR: numpy no disponible"
python3 -c "import scipy; print('  scipy:', scipy.__version__)" || echo "  ERROR: scipy no disponible"
python3 -c "import matplotlib; print('  matplotlib:', matplotlib.__version__)" || echo "  ERROR: matplotlib no disponible"
python3 -c "import obspy; print('  obspy:', obspy.__version__)" || echo "  ERROR: obspy no instalado"
python3 -c "import paho.mqtt; print('  paho-mqtt: OK')" || echo "  ERROR: paho-mqtt no instalado"
python3 -c "from dotenv import load_dotenv; print('  python-dotenv: OK')" || echo "  ERROR: python-dotenv no instalado"
python3 -c "from googleapiclient.discovery import build; print('  google-api: OK')" || echo "  ERROR: google-api no instalado"
python3 -c "from OpenSSL import crypto; print('  pyopenssl: OK')" || echo "  ERROR: pyopenssl no instalado"
python3 -c "import tflite_runtime.interpreter as tflite; print('tflite ok')" || echo "  ERROR: tflite no instalado"

deactivate

echo ""
echo "=== Entorno virtual creado con éxito ==="
echo "Python del venv: $VENV_DIR/bin/python3"
echo ""


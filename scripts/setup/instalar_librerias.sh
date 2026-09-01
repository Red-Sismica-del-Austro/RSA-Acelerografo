#!/bin/bash

# Instalacion libreria WirinPi
cd $PROJECT_GIT_ROOT/main-libraries
sudo dpkg -i wiringpi-latest.deb

# Instalacion libreria bcm2835
tar zxvf bcm2835-1.58.tar.gz
cd bcm2835-1.58
./configure
make
sudo make check
sudo make install

# Instalacion ibjansson:
sudo apt-get install -y libjansson-dev

# Instalacion de python3-venv (necesario para entornos virtuales)
sudo apt-get install -y python3-venv

# Instalacion de paquetes pesados precompilados via apt
# (se heredan al venv con --system-site-packages)
sudo apt-get install -y \
    python3-pip python3-dev \
    python3-numpy python3-scipy python3-matplotlib \
    python3-lxml python3-setuptools python3-sqlalchemy \
    python3-decorator python3-requests python3-packaging \
    libatlas-base-dev libopenblas-dev gfortran

# Instalacion de Supervisor
sudo apt-get install -y supervisor

# Instalacion de NTP
sudo apt install ntp -y
sudo apt install ntpstat -y

# Crear el entorno virtual e instalar dependencias Python
# (hereda numpy/scipy/matplotlib de apt, instala obspy/paho-mqtt/etc via pip)
echo "Creando entorno virtual e instalando dependencias Python..."
bash $PROJECT_GIT_ROOT/scripts/setup/crear_entorno_virtual.sh
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
sudo apt-get install libjansson-dev

# Instalacion libreria paho-mqtt
sudo pip3 install paho-mqtt

# Instalacion libreria Google Drive API
sudo pip3 install --upgrade google-api-python-client google-auth-httplib2 google-auth-oauthlib
sudo pip3 install --upgrade oauth2client

# Instalacion de Supervisor
sudo apt-get install supervisor

# Instalacion de NTP
sudo apt install ntp -y
sudo apt install ntpstat -y

# Instalacion de Obspy
while true; do
    read -p "Desea continuar con la instalación de ObsPy? (s/n) " response
    case "$response" in
        s|S)
            echo "Instalando dependencias necesarias..."
            sudo apt-get install -y \
                python3-pip python3-dev \
                python3-scipy python3-lxml python3-setuptools \
                python3-sqlalchemy python3-decorator python3-requests \
                python3-packaging python3-pyproj python3-pytest \
                python3-geographiclib python3-cartopy python3-pyshp \
                libatlas-base-dev libopenblas-dev gfortran

            echo "Actualizando pip..."
            sudo pip3 install --upgrade pip

            echo "Actualizando NumPy y Matplotlib..."
            sudo pip3 install --upgrade numpy matplotlib

            echo "Instalando ObsPy..."
            sudo pip3 install obspy

            echo "Comprobando instalación de ObsPy..."
            python3 -c "import obspy; print(obspy.__version__)"

            break  # Salir del bucle después de la instalación
            ;;
        n|N)
            echo "Instalación de ObsPy cancelada."
            break  # Salir del bucle sin instalar
            ;;
        *)
            echo "Opción no válida, por favor ingrese 's' para sí o 'n' para no."
            ;;
    esac
done
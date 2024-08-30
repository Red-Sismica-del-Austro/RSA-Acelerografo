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

# Instalacion libreria paho-mqtt
sudo pip3 install paho-mqtt

# Instalacion libreria Google Drive API
sudo pip3 install --upgrade google-api-python-client google-auth-httplib2 google-auth-oauthlib
sudo pip3 install --upgrade oauth2client

# Instalacion libreria WirinPi
#cd /tmp
#wget https://project-downloads.drogon.net/wiringpi-latest.deb
#sudo dpkg -i wiringpi-latest.deb

#!/bin/bash

# Cargar las variables de entorno
source /usr/local/bin/project_paths

# Dependiendo de los parámetros que se le pasen al programa se usa una opción u otra
case "$1" in
  start)
    echo "Arrancando sistema de registro continuo..."
    sudo killall -q registro_continuo
    sudo -E $PROJECT_LOCAL_ROOT/scripts/acelerografo/ejecutables/registro_continuo &
    sleep 5
    python3 $PROJECT_LOCAL_ROOT/scripts/mseed/binary_to_mseed.py 1 &
    ;;
  stop)
    echo "Deteniendo sistema de registro continuo..."
    sudo killall -q registro_continuo
    sudo $PROJECT_LOCAL_ROOT/scripts/acelerografo/ejecutables/reset_master
    ;;
  *)
    echo "Modo de uso: registrocontinuo start|stop"
    exit 1
    ;;
esac
 
exit 0 

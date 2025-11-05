#!/bin/bash

# Cargar las variables de entorno
source /usr/local/bin/project_paths

# Dependiendo de los parámetros que se le pasen al programa se usa una opción u otra
case "$1" in
  start)
    echo "Arrancando sistema de registro continuo..."
    sudo -E "$PROJECT_LOCAL_ROOT/scripts/acelerografo/ejecutables/registro_continuo" &
    sleep 5
    /usr/bin/python3 "$PROJECT_LOCAL_ROOT/scripts/mseed/binary_to_mseed.py" 1 &
    pid_mseed=$!
    wait $pid_mseed
    /usr/bin/python3 "$PROJECT_LOCAL_ROOT/scripts/drive/gestor_archivos_acq.py" 
    ;;
  
  stop)
    echo "Deteniendo sistema de registro continuo..."
    sudo killall -q registro_continuo
    sudo "$PROJECT_LOCAL_ROOT/scripts/acelerografo/ejecutables/reset_master"
    ;;

  restart)
    echo "Reiniciando sistema de registro continuo..."
    $0 stop && $0 start
    ;;
  
  *)
    echo "Modo de uso: registrocontinuo start|stop|restart"
    exit 1
    ;;
esac

exit 0



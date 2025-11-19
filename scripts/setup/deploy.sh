#!/bin/bash
set -euo pipefail  # Modo seguro: salir en error, variables no definidas, errores en pipes

# Validar que las variables requeridas estén definidas
if [ -z "${PROJECT_GIT_ROOT:-}" ] || [ -z "${PROJECT_LOCAL_ROOT:-}" ]; then
    echo "ERROR: Las variables PROJECT_GIT_ROOT y PROJECT_LOCAL_ROOT deben estar definidas"
    exit 1
fi

echo "Usando la ruta del repositorio Git: $PROJECT_GIT_ROOT"
echo "Usando la ruta del proyecto local: $PROJECT_LOCAL_ROOT"

# Crear los directorios del proyecto local si no existen (sin sudo)
mkdir -p $PROJECT_LOCAL_ROOT
mkdir -p $PROJECT_LOCAL_ROOT/configuracion
mkdir -p $PROJECT_LOCAL_ROOT/log-files
mkdir -p $PROJECT_LOCAL_ROOT/tmp-files
mkdir -p $PROJECT_LOCAL_ROOT/resultados/eventos-detectados
mkdir -p $PROJECT_LOCAL_ROOT/resultados/eventos-extraidos
mkdir -p $PROJECT_LOCAL_ROOT/resultados/registro-continuo
mkdir -p $PROJECT_LOCAL_ROOT/resultados/mseed
mkdir -p $PROJECT_LOCAL_ROOT/scripts/acelerografo/ejecutables
mkdir -p $PROJECT_LOCAL_ROOT/scripts/acelerografo/libraries
mkdir -p $PROJECT_LOCAL_ROOT/scripts/mseed
mkdir -p $PROJECT_LOCAL_ROOT/scripts/mqtt
mkdir -p $PROJECT_LOCAL_ROOT/scripts/drive
mkdir -p $PROJECT_LOCAL_ROOT/scripts/task

# Asegurar que los directorios creados tengan la propiedad correcta (sin sudo)
chown -R $USER:$USER $PROJECT_LOCAL_ROOT

# Crea los archivos necesarios
echo $(date) > $PROJECT_LOCAL_ROOT/resultados/registro-continuo/nueva-estacion.txt
echo 'nueva-estacion.txt' > $PROJECT_LOCAL_ROOT/tmp-files/NombreArchivoRegistroContinuo.tmp

# Crea los archivos log
touch $PROJECT_LOCAL_ROOT/log-files/drive.log
touch $PROJECT_LOCAL_ROOT/log-files/gestor_acq.log 
touch $PROJECT_LOCAL_ROOT/log-files/mqtt.log
touch $PROJECT_LOCAL_ROOT/log-files/mseed.log
touch $PROJECT_LOCAL_ROOT/log-files/registro_continuo.log

# Copiar los archivos de configuración del proyecto en Git al proyecto local
cp $PROJECT_GIT_ROOT/configuration/configuracion_dispositivo.json $PROJECT_LOCAL_ROOT/configuracion/
cp $PROJECT_GIT_ROOT/configuration/configuracion_mqtt.json $PROJECT_LOCAL_ROOT/configuracion/
cp $PROJECT_GIT_ROOT/configuration/configuracion_mseed.json $PROJECT_LOCAL_ROOT/configuracion/

# Copiar los scripts de Python del proyecto en Git al proyecto local
cp $PROJECT_GIT_ROOT/scripts/operation/mqtt/cliente.py $PROJECT_LOCAL_ROOT/scripts/mqtt/cliente.py
cp $PROJECT_GIT_ROOT/scripts/operation/mseed/binary_to_mseed.py $PROJECT_LOCAL_ROOT/scripts/mseed/binary_to_mseed.py
cp $PROJECT_GIT_ROOT/scripts/operation/mseed/extract_segment.py $PROJECT_LOCAL_ROOT/scripts/mseed/extract_segment.py
cp $PROJECT_GIT_ROOT/scripts/operation/drive/gestor_archivos_acq.py $PROJECT_LOCAL_ROOT/scripts/drive/gestor_archivos_acq.py

# Copiar el task-script crontab.txt al directorio de proyectos
cp $PROJECT_GIT_ROOT/scripts/task/crontab.txt $PROJECT_LOCAL_ROOT/scripts/task/
cp $PROJECT_GIT_ROOT/scripts/task/crontab.txt $PROJECT_LOCAL_ROOT/tmp-files/crontab_backup.txt 

# Copiar los archivos de configuracion de Supervisor al directorio de configuracion (esto sí requiere sudo)
sudo cp $PROJECT_GIT_ROOT/scripts/task/mqttcliente.conf /etc/supervisor/conf.d/

# Actualizar Supervisor
sudo supervisorctl reread
sudo supervisorctl update
sudo supervisorctl start mqttcliente

# Copiar los task-scripts al directorio /usr/local/bin sin la extensión .sh
for script in $PROJECT_GIT_ROOT/scripts/task/*.sh; do
    script_name=$(basename "$script" .sh)
    sudo cp "$script" "/usr/local/bin/$script_name"
    # Conceder permisos de ejecución solo al script copiado
    sudo chmod +x "/usr/local/bin/$script_name"
done

# Crear un crontab con permiso de superusuario usando el contenido del archivo crontab.txt
sudo crontab $PROJECT_GIT_ROOT/scripts/task/crontab.txt

# Navegar al directorio donde está el Makefile y ejecutar make
cd $PROJECT_GIT_ROOT/scripts/setup/
make

echo "Despliegue completado con éxito."

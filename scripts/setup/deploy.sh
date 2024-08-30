#!/bin/bash

# Definir la raíz del proyecto en Git y el proyecto local
#USER_HOME=$(eval echo ~$SUDO_USER)  # Obtiene el home del usuario original cuando se usa sudo
#PROJECT_GIT_ROOT="$USER_HOME/git/Acelerografo-RSA"
#PROJECT_LOCAL_ROOT="$USER_HOME/projects/acelerografo-rsa"

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

# Asegurar que los directorios creados tengan la propiedad correcta (sin sudo)
chown -R $USER:$USER $PROJECT_LOCAL_ROOT

# Crea los archivos necesarios
echo $(date) > $PROJECT_LOCAL_ROOT/resultados/registro-continuo/nueva-estacion.txt
echo 'nueva-estacion.txt' > $PROJECT_LOCAL_ROOT/tmp-files/NombreArchivoRegistroContinuo.tmp

# Copiar los archivos de configuración del proyecto en Git al proyecto local
cp $PROJECT_GIT_ROOT/configuration/configuracion_dispositivo.json $PROJECT_LOCAL_ROOT/configuracion/
cp $PROJECT_GIT_ROOT/configuration/configuracion_mqtt.json $PROJECT_LOCAL_ROOT/configuracion/
cp $PROJECT_GIT_ROOT/configuration/configuracion_mseed.json $PROJECT_LOCAL_ROOT/configuracion/

# Copiar los scripts de Python del proyecto en Git al proyecto local
cp $PROJECT_GIT_ROOT/scripts/operation/mqtt/cliente*.py $PROJECT_LOCAL_ROOT/scripts/mqtt/cliente.py
cp $PROJECT_GIT_ROOT/scripts/operation/mseed/binary_to_mseed*.py $PROJECT_LOCAL_ROOT/scripts/mseed/binary_to_mseed.py
cp $PROJECT_GIT_ROOT/scripts/operation/drive/subir_archivo*.py $PROJECT_LOCAL_ROOT/scripts/drive/subir_archivo.py

# Copiar los task-scripts al directorio /usr/local/bin sin la extensión .sh (esto sí requiere sudo)
for script in $PROJECT_GIT_ROOT/scripts/task/*.sh; do
    script_name=$(basename "$script" .sh)
    sudo cp "$script" "/usr/local/bin/$script_name"
done

# Conceder permisos de ejecución a los task-scripts
sudo chmod +x /usr/local/bin/*

# Crear un crontab con permiso de superusuario y agregar el contenido del archivo crontab.txt
sudo crontab -l > mycron
cat $PROJECT_GIT_ROOT/scripts/task/crontab.txt >> mycron
echo "" >> mycron  # Añadir una nueva línea al final del archivo
sudo crontab mycron
rm mycron

# Navegar al directorio donde está el Makefile y ejecutar make
cd $PROJECT_GIT_ROOT/scripts/setup/
make

echo "Despliegue completado con éxito."

# Instrucciones de Uso

## Configurar una Nueva Estación
Para configurar una estación por primera vez, siga los siguientes pasos:

1. Ejecute el menú con el comando `bash menu.sh`.
2. Seleccione la opción 0 para establecer las variables de entorno.
3. Seleccione la opción 1 para instalar las librerías necesarias.
4. Seleccione la opción 2 para desplegar el proyecto.

## Actualizar el Proyecto a la Última Versión Disponible
Para actualizar el proyecto, siga los siguientes pasos:

1. Obtenga la última versión del repositorio mediante el comando `git pull`.
2. Ejecute el menú y seleccione la opción 3.

# Importante

## Rutas de los Directorios del Proyecto
Es muy importante que las rutas definidas en el archivo de configuración `configuracion_dispositivo.json` coincidan con las variables de entorno definidas en el archivo `/scripts/env/project_paths.sh`.

## Backups de Archivos de Configuración
Antes de realizar una actualización, respalde el directorio de configuración con todos sus archivos.

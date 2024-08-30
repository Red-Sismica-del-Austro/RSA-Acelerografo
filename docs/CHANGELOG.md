# Registro de Cambios

## 2024-06-27 - programas/conversor_mseed.py [2.0.0]
### Cambios
- Se cambió la lectura de parametros mseed de un archivo csv a un archivo json.
- Se cambió la lectura de parametros del dispositivo de un archivo txt a un archivo json.
- Se realizó una revision completa del programa y se otimizaron varias funciones.
- Se actualizó el script de ayuda para incluir intrucciones para ejecutar este programa.
- Se actualizó el script registro continuo para corregir el nuevo formato del nombre del programa.

## 2024-07-05 - programas/conversor_mseed.py [2.1.0]
### Optimización
- Se optimizó la función leer_archivo_binario() para realizar operaciones vectorizadas en lugar de iterativas.
- Esta optimización redujo el tiempo de conversión del archivo binario a formato mseed de 30 minutos a 30 segundos.
- Se realizaron comparaciones entre la matriz numpy extraída y el archivo mseed obtenido con la versión original para garantizar que la versión optimizada del programa produce los mismos resultados que la versión original.
- También se verificó utilizando un archivo binario incompleto del cual se eliminaron 100 muestras de manera aleatoria.

## 2024-07-11 - programas/subir_archivo_drive.py [2.0.0] 
### Cambios 
- Se depuró el código de la funcion para que se adapte al estandar establecido por el resto de programas.
- Se cambió la lectura de parametros del dispositivo de un archivo txt a un archivo json.
- Se cambió la estructura del nombre de los archivos de Registro Continuo y Evento Extraido almacenados en los archivos temporales NombreArchivoRegistroContinuo.tmp y NombreArchivoEventoExtraido.tmp para que no incluyan el path completo del archivo, sino unicamente el nombre y la extension. 
- Se agregó un parametro mas de entrada que indique si se debe borrar el archivo despues de subirlo a Drive.
- Se cambió el orden de los parametros de entrada quedando de la siguiente manera: subir_archivo_drive.py <nombre_archivo> <tipo_archivo> <borrar_despues>

## 2024-07-11 - programas/extraer_evento_binario.c [2.1.1] 
### Patch
- Se realizó un cambio en el código para que la estructura del nombre del archivo extraido coincida con los cambios implementados en el programa subir_archivo_drive.py

## 2024-07-11 - programas/conversor_mseed.py [2.1.1] 
### Patch
- Se realizó un cambio en el código para que la estructura del nombre de los archivos coincidan con los cambios implementados en el programa subir_archivo_drive.py

## 2024-07-11 - configuracion/configuracion_dispositivo.json | setup-scripts/actualizar.sh | setup-scripts/iniciar.sh | setup-scripts/compilar.sh 
### Patch
- Se realizaron correcciones para que los nombres de las variables y los programas coincidan con los nuevos formatos

## 2024-08-16 - scripts/setup/deploy.sh | scripts/setup/update.sh | scripts/setup/makefile 
### Cambios / Optimización 
- Se realizó una reestructuración completa de los directorios y archivos del proyecto
- Se añadió el script `deploy.sh` que automatiza el proceso de despliegue del proyecto. 
  - Crea los directorios necesarios en el proyecto local.
  - Copia los archivos de configuración, scripts de Python y task-scripts desde el repositorio Git a sus respectivas ubicaciones.
  - Copia los task-scripts a `/usr/local/bin` y concede los permisos de ejecución necesarios.
  - Modifica el crontab solo si es necesario.
  - Ejecuta el `Makefile` para compilar los programas si es requerido.

- Se añadió el script `update.sh` para la actualización automática del proyecto.
  - Verifica si se realizaron cambios en los archivos de configuración, scripts de MQTT, MSeed y Drive.
  - Actualiza los archivos en el proyecto local si hay cambios.
  - Verifica si se realizaron cambios en los task-scripts y actualiza `/usr/local/bin` sin modificar el crontab.
  - Verifica si hay cambios en los archivos de `acelerografo` y `libraries` y ejecuta `make` si es necesario.
  - Imprime una lista de los archivos que fueron actualizados durante el proceso.

## 2024-08-19 - scripts/operation/acelerografo/comprobar_registro_5.0.0.c
### Cambios 
- Se cambió la lectura de parametros del dispositivo de un archivo txt a un archivo json.

## 2024-08-29 
### Cambios / Optimización 
- Se realizaron cambios en varios de los scripts para utilizar variables de entorno
- Esta es la ultima version estable, testeada y lista para ser desplegada en produccion.
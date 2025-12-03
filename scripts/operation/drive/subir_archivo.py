"""
Script para subir archivos a Google Drive con sistema de reintentos configurable

EJEMPLOS DE USO:

python3 subir_archivo.py --continuous archivo.dat      # Sube archivo de registro continuo
python3 subir_archivo.py --mseed archivo.mseed          # Sube archivo miniSEED procesado
python3 subir_archivo.py --event evento.dat             # Sube archivo de evento extraído
python3 subir_archivo.py --tmp temporal.tmp             # Sube archivo temporal
python3 subir_archivo.py --log sistema.log              # Sube archivo de log

MODOS DISPONIBLES:

--continuous : Archivos de registro continuo (.dat)
               Directorio: directorios.registro_continuo
               Drive ID: drive.carpetas.continuos_id

--mseed      : Archivos miniSEED procesados (.mseed)
               Directorio: directorios.archivos_mseed
               Drive ID: drive.carpetas.mseed_id

--event      : Archivos de eventos extraídos (.dat)
               Directorio: directorios.eventos_extraidos
               Drive ID: drive.carpetas.events_id

--tmp        : Archivos temporales (.tmp)
               Directorio: directorios.archivos_temporales
               Drive ID: drive.carpetas.tmp_id

--log        : Archivos de log (.log)
               Directorio: log-files/ (hardcodeado)
               Drive ID: drive.carpetas.logs_id

SISTEMA DE REINTENTOS:

El script implementa reintentos automáticos en caso de fallos durante la subida:
- Número de reintentos: Configurado en drive.config.max_reintentos (por defecto: 3)
- Tiempo de espera entre reintentos: Configurado en drive.config.tiempo_espera (por defecto: 2 segundos)
- Logging detallado de cada intento
- Espera exponencial entre reintentos para evitar sobrecarga

REQUISITOS:

- Variable de entorno PROJECT_LOCAL_ROOT debe estar definida
- Archivos de configuración necesarios:
    * configuracion_dispositivo.json (con estructura drive.carpetas y drive.config)
    * drive_credentials.json
    * drive_token.json

ESTRUCTURA JSON REQUERIDA:

{
  "drive": {
    "carpetas": {
      "continuos_id": "...",
      "mseed_id": "...",
      "events_id": "...",
      "tmp_id": "...",
      "logs_id": "..."
    },
    "config": {
      "max_reintentos": 5,
      "tiempo_espera": 2
    }
  }
}
"""

######################################### ~Librerias~ #################################################
from __future__ import print_function
from googleapiclient import errors
from googleapiclient.http import MediaFileUpload
from googleapiclient.discovery import build
from httplib2 import Http
from oauth2client import file, client, tools
import os
from datetime import datetime
import time
import sys
import json
import logging
#######################################################################################################


##################################### ~Variables globales~ ############################################
loggers = {}
isConecctedDrive = False
SCOPES = 'https://www.googleapis.com/auth/drive'
#######################################################################################################


######################################### ~Funciones~ #################################################

# Lee un archivo de configuración en formato JSON y devuelve su contenido como un diccionario.
def read_fileJSON(nameFile):

    try:
        with open(nameFile, 'r') as f:
            data = json.load(f)
        return data
    except FileNotFoundError:
        print(f"Archivo {nameFile} no encontrado.")
        return None
    except json.JSONDecodeError:
        print(f"Error al decodificar el archivo {nameFile}.")
        return None
  
# Metodo que permite realizar la autenticacion a Google Drive
def get_authenticated(SCOPES, credential_file, token_file, service_name = 'drive', api_version = 'v3'):
    # The file token.json stores the user's access and refresh tokens, and is
    # created automatically when the authorization flow completes for the first
    # time.
    store = file.Storage(token_file)
    creds = store.get()
    if not creds or creds.invalid:
        flow = client.flow_from_clientsecrets(credential_file, SCOPES)
        creds = tools.run_flow(flow, store)
    service = build(service_name, api_version, http = creds.authorize(Http()))

    return service

# Metodo que permite subir un archivo a la cuenta de Drive
def insert_file(service, name, description, parent_id, mime_type, filename):
    # MODO TEST: Descomentar las siguientes líneas para simular fallos
    #import random
    #if random.random() < 0.7:  # 70% de probabilidad de fallo
    #    raise Exception("Simulación de error de red")

    media_body = MediaFileUpload(filename, mimetype = mime_type, chunksize=-1, resumable = True)
    body = {
        'name': name,
        'description': description,
        'mimeType': mime_type
    }

    # Si se recibe la ID de la carpeta superior, la coloca
    if parent_id:
        body['parents'] = [parent_id]

    # Realiza la carga del archivo en la carpeta respectiva de Drive
    try:
        #print("punto de control")
        file = service.files().create(
            body = body,
            media_body = media_body,
            fields='id').execute()

        return file

    except errors.HttpError as error:
        print('An error occurred: %s' % error)
        return None


# Metodo para intentar conectarse a Google Drive y activar la bandera de conexion
def Try_Autenticar_Drive(SCOPES, credentials_file, token_file, logger):
    global isConecctedDrive
    # Llama al metodo para realizar la autenticacion, la primera vez se
    # abrira el navegador, pero desde la segunda ya no
    try:
        service = get_authenticated(SCOPES, credentials_file, token_file)
        isConecctedDrive = True
        print("Inicio Drive Ok")
        logger.info("Inicio Drive Ok")
        return service
    except Exception as e:
        isConecctedDrive = False
        print("********** Error Inicio Drive ********")
        logger.error("Error Inicio Drive: %s", str(e))
        return 0


# Función para inicializar y obtener el logger de un cliente
def obtener_logger(id_estacion, log_directory, log_filename):
    global loggers
    if id_estacion not in loggers:
        # Crear un logger para el cliente
        logger = logging.getLogger(id_estacion)
        logger.setLevel(logging.DEBUG)
        # Verificar si el directorio de logs existe, si no, crearlo
        if not os.path.isdir(log_directory):
            try:
                os.makedirs(log_directory)
                logger.info(f"Directorio de logs creado: {log_directory}")
            except Exception as e:
                logger.error(f"Error al crear el directorio de logs {log_directory}: {e}")
        # Ruta completa del archivo de log
        log_path = os.path.join(log_directory, log_filename)
        # Crear manejador de archivo, apuntando al archivo existente
        file_handler = logging.FileHandler(log_path)
        file_handler.setLevel(logging.DEBUG)
        # Crear formato de logging y añadirlo al manejador
        formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
        file_handler.setFormatter(formatter)
        # Añadir el manejador al logger
        logger.addHandler(file_handler)
        loggers[id_estacion] = logger
    return loggers[id_estacion]

#######################################################################################################


############################################ ~Main~ ###################################################
def main():

    # Mapeo de modos de archivo
    MODOS = {
        'continuous': {
            'dir_key': 'registro_continuo',
            'drive_key': 'continuos_id',
            'descripcion': 'Archivos de registro continuo'
        },
        'mseed': {
            'dir_key': 'archivos_mseed',
            'drive_key': 'mseed_id',
            'descripcion': 'Archivos miniSEED procesados'
        },
        'event': {
            'dir_key': 'eventos_extraidos',
            'drive_key': 'events_id',
            'descripcion': 'Archivos de eventos extraídos'
        },
        'tmp': {
            'dir_key': 'archivos_temporales',
            'drive_key': 'tmp_id',
            'descripcion': 'Archivos temporales'
        },
        'log': {
            'dir_key': 'log_directory',
            'drive_key': 'logs_id',
            'descripcion': 'Archivos de log'
        }
    }

    # Validar argumentos
    if len(sys.argv) != 3:
        print("Uso: subir_archivo.py --<modo> <nombre_archivo>")
        print("\nModos disponibles:")
        for modo, info in MODOS.items():
            print(f"  --{modo:<12} {info['descripcion']}")
        print("\nEjemplos:")
        print("  python3 subir_archivo.py --continuous archivo.dat")
        print("  python3 subir_archivo.py --mseed archivo.mseed")
        print("  python3 subir_archivo.py --event evento.dat")
        print("  python3 subir_archivo.py --tmp temporal.tmp")
        print("  python3 subir_archivo.py --log sistema.log")
        return

    modo_arg = sys.argv[1]
    nombre_archivo = sys.argv[2]

    # Validar que el argumento comience con --
    if not modo_arg.startswith('--'):
        print(f"Error: El modo debe comenzar con '--'. Recibido: {modo_arg}")
        return

    # Extraer el modo sin el prefijo --
    modo = modo_arg[2:]

    # Validar que el modo sea válido
    if modo not in MODOS:
        print(f"Error: Modo '{modo}' no válido.")
        print(f"Modos disponibles: {', '.join(['--' + m for m in MODOS.keys()])}")
        return

    # Obtiene la variable de entorno para definir la ruta del archivo de configuración
    project_local_root = os.getenv("PROJECT_LOCAL_ROOT")
    if not project_local_root:
        print("La variable de entorno PROJECT_LOCAL_ROOT no está definida.")
        return

    # Definir rutas de archivos y directorios
    config_dispositivo_path = os.path.join(project_local_root, "configuracion", "configuracion_dispositivo.json")
    credentials_file = os.path.join(project_local_root, "configuracion", "drive_credentials.json")
    token_file = os.path.join(project_local_root, "configuracion", "drive_token.json")
    log_directory = os.path.join(project_local_root, "log-files")

    # Lee el archivo de configuración del dispositivo
    config_dispositivo = read_fileJSON(config_dispositivo_path)
    if config_dispositivo is None:
        print("No se pudo leer el archivo de configuración del dispositivo. Terminando el programa.")
        return

    # Obtener ID de la estación
    id_estacion = config_dispositivo.get("dispositivo", {}).get("id", "Unknown")

    # Obtener configuración de reintentos y tiempo de espera
    max_reintentos = config_dispositivo.get("drive", {}).get("config", {}).get("max_reintentos", 3)
    tiempo_espera = config_dispositivo.get("drive", {}).get("config", {}).get("tiempo_espera", 2)

    # Obtener información del modo seleccionado
    modo_info = MODOS[modo]
    dir_key = modo_info['dir_key']
    drive_key = modo_info['drive_key']

    # Obtener ruta del directorio
    if dir_key == 'log_directory':
        # log_directory es hardcodeado
        path_file = log_directory
    else:
        path_file = config_dispositivo.get("directorios", {}).get(dir_key, "")
        if not path_file:
            print(f"Error: No se encontró la ruta '{dir_key}' en configuracion_dispositivo.json")
            return

    # Obtener ID de carpeta de Drive
    drive_id = config_dispositivo.get("drive", {}).get("carpetas", {}).get(drive_key, "")
    if not drive_id:
        print(f"Error: No se encontró el ID de Drive '{drive_key}' en configuracion_dispositivo.json")
        return

    # Construir ruta completa del archivo
    path_completo_archivo = os.path.join(path_file, nombre_archivo)
        
    # Obtiene el directorio de logs y lo crea si no existe
    if not os.path.exists(log_directory):
        os.makedirs(log_directory)

    # Inicializa el logger
    logger = obtener_logger(id_estacion, log_directory, "drive.log")

    # Verifica si el archivo existe
    if not os.path.isfile(path_completo_archivo):
        print("El archivo %s no existe. Terminando el programa." % path_completo_archivo)
        logger.error("El archivo %s no existe. Terminando el programa." % path_completo_archivo)
        return

    # Llama al metodo para intentar conectarse a Google Drive
    service = Try_Autenticar_Drive(SCOPES, credentials_file, token_file, logger)

    if isConecctedDrive == True:
        # Llama al metodo para subir el archivo a Google Drive con reintentos
        intento = 0
        archivo_subido = False

        while intento < max_reintentos and not archivo_subido:
            intento += 1
            try:
                if intento == 1:
                    logger.info(f'Subiendo el archivo: {nombre_archivo}')
                    print(f'Subiendo el archivo: {path_completo_archivo}')
                else:
                    logger.info(f'Reintento {intento}/{max_reintentos} para subir el archivo: {nombre_archivo}')
                    print(f'Reintento {intento}/{max_reintentos}...')

                file_uploaded = insert_file(service, nombre_archivo, nombre_archivo, drive_id, 'text/plain', path_completo_archivo)

                if file_uploaded:
                    archivo_subido = True
                    logger.info(f'Archivo {nombre_archivo} subido correctamente a Google Drive en el intento {intento}')
                    print(f'Archivo {nombre_archivo} subido correctamente a Google Drive')
                else:
                    logger.warning(f'Intento {intento} fallido: No se recibió confirmación de subida')
                    if intento < max_reintentos:
                        logger.info(f'Esperando {tiempo_espera} segundos antes del siguiente intento...')
                        print(f'Esperando {tiempo_espera} segundos antes de reintentar...')
                        time.sleep(tiempo_espera)

            except Exception as e:
                logger.error(f'Error en intento {intento}/{max_reintentos} subiendo {nombre_archivo}. Codigo: {str(e)}')
                print(f'Error en intento {intento}: {str(e)}')

                if intento < max_reintentos:
                    logger.info(f'Esperando {tiempo_espera} segundos antes del siguiente intento...')
                    print(f'Esperando {tiempo_espera} segundos antes de reintentar...')
                    time.sleep(tiempo_espera)

        # Verificar resultado final
        if not archivo_subido:
            logger.error(f'No se pudo subir el archivo {nombre_archivo} después de {max_reintentos} intentos')
            print(f'ERROR: No se pudo subir el archivo después de {max_reintentos} intentos')
    else:
        logger.error("No se pudo conectar a Google Drive. Verifica las credenciales.")
        print("ERROR: No se pudo conectar a Google Drive")
    

#######################################################################################################


#######################################################################################################
if __name__ == '__main__':
    main()
#######################################################################################################
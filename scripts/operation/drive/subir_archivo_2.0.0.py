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

    # Lee los parametros de entrada: <nombre_archivo> <tipo_archivo> <borrar_despues>
    
    if len(sys.argv) != 4:
        print("Uso: subir_archivo_drive.py <nombre_archivo> <tipo_archivo: 1.Registro continuo 2.Evento extraido 3.mseed> <borrar_despues: 0.No 1.Si >")
        return
    
    nombre_archivo = sys.argv[1]
    tipo_archivo = sys.argv[2] 
    borrar_despues = sys.argv[3]

    # Obtiene la variable de entorno para definir la ruta del archivo de configuracion:
    project_local_root = os.getenv("PROJECT_LOCAL_ROOT")
    if project_local_root:
        #print(f"PROJECT_LOCAL_ROOT: {project_local_root}")
        # Concatenar PROJECT_LOCAL_CONFIG con las diferentes rutas de los archivos y scripts:
        config_dispositivo_path = os.path.join(project_local_root, "configuracion", "configuracion_dispositivo.json")
        credentials_file = os.path.join(project_local_root, "configuracion", "drive_credentials.json")
        token_file = os.path.join(project_local_root, "configuracion", "drive_token.json")
        log_directory = os.path.join(project_local_root, "log-files")
    else:
        print("La variable de entorno no están definida.")
        return

    # Lee el archivo de configuración del dispositivo
    config_dispositivo = read_fileJSON(config_dispositivo_path)
    if config_dispositivo is None:
        print("No se pudo leer el archivo de configuración del dispositivo. Terminando el programa.")
        return

    if tipo_archivo=='1':
        #Archivos registro continuo
        path_file = config_dispositivo.get("directorios", {}).get("registro_continuo", "Unknown")
        drive_id = config_dispositivo.get("drive", {}).get("registro_continuo", "Unknown")
    elif tipo_archivo=='2':
        #Archivos eventos extraidos
        path_file = config_dispositivo.get("directorios", {}).get("eventos_extraidos", "Unknown")
        drive_id = config_dispositivo.get("drive", {}).get("eventos_extraidos", "Unknown")
    elif tipo_archivo=='3':
        #Archivos registro continuo
        path_file = config_dispositivo.get("directorios", {}).get("archivos_mseed", "Unknown")
        drive_id = config_dispositivo.get("drive", {}).get("registro_continuo", "Unknown")
    else:
        print("Tipo de archivo no soportado")
        
    id_estacion = config_dispositivo.get("dispositivo", {}).get("id", "Unknown")
    path_completo_archivo = path_file + nombre_archivo
        
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

    #Llama al metodo para intentar conectarse a Google Drive
    service = Try_Autenticar_Drive(SCOPES, credentials_file, token_file, logger)
    
    if isConecctedDrive == True:
        # Llama al metodo para subir el archivo a Google Drive
        try:
            print('Subiendo el archivo: %s' %path_completo_archivo)
            #logger.info("Subiendo el archivo: %s", nombre_archivo)
            file_uploaded = insert_file(service, nombre_archivo, nombre_archivo, drive_id, 'text/plain', path_completo_archivo)
            logger.info(f'Archivo {nombre_archivo} subido correctamente a Google Drive')
            print('Archivo ' + nombre_archivo + ' subido correctamente a Google Drive ' )
            if borrar_despues =='1':
                os.remove(path_completo_archivo)
                print('Archivo local eliminado: %s' % path_completo_archivo)
                logger.info(f'Archivo {nombre_archivo} eliminado')
        except Exception as e:
            # Llama al metodo para guardar el evento ocurrido en el archivo
            logger.error(f'Error subiendo el archivo {nombre_archivo} a Google Drive. Codigo: {str(e)}')
            print ('Error subiendo el archivo a Google Drive')
    

#######################################################################################################


#######################################################################################################
if __name__ == '__main__':
    main()
#######################################################################################################

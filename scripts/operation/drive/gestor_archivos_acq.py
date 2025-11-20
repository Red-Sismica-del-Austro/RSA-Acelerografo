import os
import subprocess
import shutil
import socket
import json
import logging

# Configurar logging básico para mensajes tempranos
logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')

# Variable global para guardar los loggers por id_estacion
loggers = {}

######################################### ~Funciones~ #################################################

# Lee un archivo de configuración en formato JSON y devuelve su contenido como un diccionario.
def read_fileJSON(nameFile):
    try:
        with open(nameFile, 'r') as f:
            data = json.load(f)
        logging.info(f"Archivo de configuración {nameFile} leído correctamente.")
        return data
    except FileNotFoundError:
        logging.error(f"Archivo {nameFile} no encontrado.")
        return None
    except json.JSONDecodeError:
        logging.error(f"Error al decodificar el archivo {nameFile}.")
        return None

# Retorna el porcentaje de espacio libre en la partición donde se encuentra 'path'
def get_free_space_percentage(path):
    total, used, free = shutil.disk_usage(path)
    percentage = (free / total) * 100
    return percentage

# Verifica la conexión a internet intentando conectar al servidor DNS de Google
def check_internet_connection(logger, host="8.8.8.8", port=53, timeout=3):
    try:
        socket.setdefaulttimeout(timeout)
        socket.socket(socket.AF_INET, socket.SOCK_STREAM).connect((host, port))
        logger.info("Conexión a internet verificada.")
        return True
    except Exception as e:
        logger.warning(f"Fallo en la conexión a internet: {e}")
        return False

# Borra el archivo más antiguo con la extensión indicada en el directorio especificado
def delete_oldest_file(directory, extension, logger):
    files = [os.path.join(directory, f) for f in os.listdir(directory) if f.endswith(extension)]
    if not files:
        logger.warning(f"No se encontraron archivos con extensión {extension} en {directory}.")
        return
    oldest_file = min(files, key=os.path.getmtime)
    filename = os.path.basename(oldest_file)
    try:
        os.remove(oldest_file)
        logger.info(f"Se borró el archivo más antiguo: {filename}")
    except Exception as e:
        logger.error(f"Error al borrar el archivo {filename}: {e}")

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
                print(f"Directorio de logs creado: {log_directory}")
            except Exception as e:
                print(f"Error al crear el directorio de logs {log_directory}: {e}")
        # Ruta completa del archivo de log
        log_path = os.path.join(log_directory, log_filename)
        # Crear manejador de archivo, apuntando al archivo de log
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

def main():
    # Obtiene la variable de entorno para definir la ruta del archivo de configuración:
    project_local_root = os.getenv("PROJECT_LOCAL_ROOT")
    if not project_local_root:
        logging.error("La variable de entorno PROJECT_LOCAL_ROOT no está definida.")
        return
    
    # Definir rutas de archivos y directorios
    script_subir_archivo_drive = os.path.join(project_local_root, "scripts", "drive", "subir_archivo.py")
    mseed_directory = os.path.join(project_local_root, "resultados", "mseed")
    binary_directory = os.path.join(project_local_root, "resultados", "registro-continuo")
    config_dispositivo_path = os.path.join(project_local_root, "configuracion", "configuracion_dispositivo.json")
    log_directory = os.path.join(project_local_root, "log-files")
    
    # Verificar que los directorios existen
    if not os.path.isdir(mseed_directory):
        logging.error(f"El directorio mseed no existe: {mseed_directory}")
        return
    if not os.path.isdir(binary_directory):
        logging.error(f"El directorio de archivos binarios no existe: {binary_directory}")
        return

    # Lee el archivo de configuración del dispositivo
    config_dispositivo = read_fileJSON(config_dispositivo_path)
    if config_dispositivo is None:
        logging.error("No se pudo leer el archivo de configuración del dispositivo. Terminando el programa.")
        return
    
    mode_acq = config_dispositivo.get("dispositivo", {}).get("modo_adquisicion", "Unknown")
    id_estacion = config_dispositivo.get("dispositivo", {}).get("id", "Unknown")

    # Inicializa el logger
    logger = obtener_logger(id_estacion, log_directory, "gestor_acq.log")
    
    # Escanear el contenido de los directorios
    try:
        archivos_mseed = [f for f in os.listdir(mseed_directory) if f.endswith(".mseed")]
        archivos_binarios = [f for f in os.listdir(binary_directory) if f.endswith(".dat")]
        logger.info(f"Se encontraron {len(archivos_mseed)} archivos mseed y {len(archivos_binarios)} archivos binarios.")
    except Exception as e:
        logger.error(f"Error al listar archivos en los directorios: {e}")
        return
    
    if mode_acq == "offline":
        logger.info("Modo offline activado.")
        # Crear lista de rutas completas de los archivos binarios
        binary_files = [os.path.join(binary_directory, f) for f in archivos_binarios]
        if binary_files:
            # Encontrar el archivo binario más reciente
            most_recent_file = max(binary_files, key=os.path.getmtime)
            filename_bin_recent = os.path.basename(most_recent_file)
            logger.info(f"Archivo binario más reciente (no se borrará): {filename_bin_recent}")
            # Borrar todos los archivos excepto el más reciente
            for path_archivo in binary_files:
                if path_archivo != most_recent_file:
                    filename_bin = os.path.basename(path_archivo)
                    try:
                        os.remove(path_archivo)
                        logger.info(f"Archivo binario borrado: {filename_bin}")
                    except Exception as e:
                        logger.error(f"Error al borrar {filename_bin}: {e}")
        else:
            logger.warning("No se encontraron archivos binarios en el directorio.")

        # Verificar espacio disponible en la partición donde se encuentra el directorio mseed
        free_space = get_free_space_percentage(mseed_directory)
        if free_space < 10:
            logger.warning("El espacio disponible es menor al 10%. Se procederá a borrar el archivo mseed más antiguo.")
            delete_oldest_file(mseed_directory, ".mseed", logger)
    
    elif mode_acq == "online":
        logger.info("Modo online activado.")
        if check_internet_connection(logger):
            #logger.info("Conexión a internet establecida. Se procederá a subir los archivos mseed a Google Drive.")
            if archivos_mseed:
                for archivo in archivos_mseed:
                    #logger.info(f"Subiendo el archivo: {archivo}")
                    result = subprocess.run(["python3", script_subir_archivo_drive, archivo, "3", "1"])
                    if result.returncode != 0:
                        logger.error(f"Error al subir el archivo {archivo}. Código de retorno: {result.returncode}")
            else:
                logger.warning("No se encontraron archivos mseed en el directorio especificado.")
        else:
             # Si no hay conexion a internet verifica el espacio disponible 
            free_space = get_free_space_percentage(mseed_directory)
            if free_space < 10:
                logger.warning("El espacio disponible es menor al 10%. Se procederá a borrar el archivo mseed más antiguo.")
                delete_oldest_file(mseed_directory, ".mseed", logger)
            else:
                logger.info("Espacio disponible suficiente en la partición.")

        # Verificar espacio disponible en el directorio de archivos binarios
        free_space = get_free_space_percentage(binary_directory)
        if free_space < 10:
            logger.warning("El espacio disponible es menor al 10%. Se procederá a borrar el archivo binario más antiguo.")
            delete_oldest_file(binary_directory, ".dat", logger)
        else:
            logger.info("Espacio disponible suficiente en la partición.")
    
    else:
        logger.error(f"Modo de adquisición desconocido: {mode_acq}")
 

if __name__ == "__main__":
    main()
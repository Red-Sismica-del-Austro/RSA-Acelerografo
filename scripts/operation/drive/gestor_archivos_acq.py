"""
Gestor de archivos para sistema de adquisición de datos sísmicos

DESCRIPCIÓN:
Script que gestiona archivos binarios y miniSEED según el modo de adquisición:
- Modo offline: Gestiona espacio eliminando archivos binarios antiguos
- Modo online: Sube archivos miniSEED a Google Drive automáticamente

USO:
    python3 gestor_archivos_acq.py              # Ejecución normal
    python3 gestor_archivos_acq.py --dry-run    # Simulación sin cambios reales

MODO DRY-RUN:
El parámetro --dry-run permite simular todas las operaciones sin realizar cambios:
- No borra archivos locales
- No sube archivos a Google Drive
- Muestra qué operaciones se ejecutarían
- Útil para verificar comportamiento antes de ejecutar en producción

REQUISITOS:
- Variable de entorno PROJECT_LOCAL_ROOT debe estar definida
- Archivo configuracion_dispositivo.json con:
  * dispositivo.modo_adquisicion: "online" o "offline"
  * directorios.registro_continuo
  * directorios.archivos_mseed
  * drive.carpetas.mseed_id (para modo online)
  * drive.config.max_reintentos
  * drive.config.tiempo_espera
"""

import os
import shutil
import socket
import json
import logging
import sys

# Importar funciones de subir_archivo.py (mismo directorio)
from subir_archivo import (
    Try_Autenticar_Drive,
    subir_archivo_con_reintentos,
    SCOPES
)

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
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.connect((host, port))
        sock.close()
        logger.info("Conexión a internet verificada.")
        return True
    except Exception as e:
        logger.warning(f"Fallo en la conexión a internet: {e}")
        return False

# Borra el archivo más antiguo con la extensión indicada en el directorio especificado
def delete_oldest_file(directory, extension, logger, dry_run=False):
    files = [os.path.join(directory, f) for f in os.listdir(directory) if f.endswith(extension)]
    if not files:
        logger.warning(f"No se encontraron archivos con extensión {extension} en {directory}.")
        return
    oldest_file = min(files, key=os.path.getmtime)
    filename = os.path.basename(oldest_file)

    if dry_run:
        logger.info(f"[DRY-RUN] Se borraría el archivo más antiguo: {filename}")
        print(f"[DRY-RUN] Se borraría: {filename}")
        return

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
    # Verificar si se ejecuta en modo dry-run
    dry_run = "--dry-run" in sys.argv

    if dry_run:
        print("\n" + "="*70)
        print("MODO DRY-RUN ACTIVADO")
        print("="*70)
        print("Las operaciones se simularán sin realizar cambios reales.")
        print("No se subirán archivos ni se borrarán datos.")
        print("="*70 + "\n")

    # Obtiene la variable de entorno para definir la ruta del archivo de configuración:
    project_local_root = os.getenv("PROJECT_LOCAL_ROOT")
    if not project_local_root:
        logging.error("La variable de entorno PROJECT_LOCAL_ROOT no está definida.")
        return
    
    # Definir rutas de archivos y directorios
    config_dispositivo_path = os.path.join(project_local_root, "configuracion", "configuracion_dispositivo.json")
    log_directory = os.path.join(project_local_root, "log-files")

    # Lee el archivo de configuración del dispositivo
    config_dispositivo = read_fileJSON(config_dispositivo_path)
    if config_dispositivo is None:
        logging.error("No se pudo leer el archivo de configuración del dispositivo. Terminando el programa.")
        return

    # Obtener rutas desde configuracion_dispositivo.json
    mseed_directory = config_dispositivo.get("directorios", {}).get("archivos_mseed", "")
    binary_directory = config_dispositivo.get("directorios", {}).get("registro_continuo", "")

    if not mseed_directory:
        logging.error("No se encontró la ruta 'archivos_mseed' en configuracion_dispositivo.json")
        return
    if not binary_directory:
        logging.error("No se encontró la ruta 'registro_continuo' en configuracion_dispositivo.json")
        return

    # Verificar que los directorios existen
    if not os.path.isdir(mseed_directory):
        logging.error(f"El directorio mseed no existe: {mseed_directory}")
        return
    if not os.path.isdir(binary_directory):
        logging.error(f"El directorio de archivos binarios no existe: {binary_directory}")
        return
    
    mode_acq = config_dispositivo.get("dispositivo", {}).get("modo_adquisicion", "Unknown")
    id_estacion = config_dispositivo.get("dispositivo", {}).get("id", "Unknown")

    # Obtener umbral de espacio libre mínimo (por defecto 10%)
    min_free_space_threshold = config_dispositivo.get("dispositivo", {}).get("umbral_espacio_minimo", 10)

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
        if dry_run:
            logger.info("[DRY-RUN] Simulando operaciones en modo offline")

        # Crear lista de rutas completas de los archivos binarios
        binary_files = [os.path.join(binary_directory, f) for f in archivos_binarios]
        if binary_files:
            # Encontrar el archivo binario más reciente
            most_recent_file = max(binary_files, key=os.path.getmtime)
            filename_bin_recent = os.path.basename(most_recent_file)
            logger.info(f"Archivo binario más reciente (no se borrará): {filename_bin_recent}")

            # Borrar todos los archivos excepto el más reciente
            archivos_a_borrar = [p for p in binary_files if p != most_recent_file]
            if dry_run:
                logger.info(f"[DRY-RUN] Se borrarían {len(archivos_a_borrar)} archivos binarios")
                for path_archivo in archivos_a_borrar:
                    filename_bin = os.path.basename(path_archivo)
                    #logger.info(f"[DRY-RUN] Se borraría: {filename_bin}")
                    print(f"[DRY-RUN] Se borraría archivo binario: {filename_bin}")
            else:
                for path_archivo in archivos_a_borrar:
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
        logger.info(f"Espacio libre en directorio mseed: {free_space:.2f}%")
        if free_space < min_free_space_threshold:
            logger.warning(f"El espacio disponible es menor al {min_free_space_threshold}%. Se procederá a borrar el archivo mseed más antiguo.")
            delete_oldest_file(mseed_directory, ".mseed", logger, dry_run)
    
    elif mode_acq == "online":
        logger.info("Modo online activado.")
        if dry_run:
            logger.info("[DRY-RUN] Simulando operaciones en modo online")

        if check_internet_connection(logger):
            logger.info("Conexión a internet establecida. Se procederá a subir los archivos mseed a Google Drive.")
            if archivos_mseed:
                # Obtener parámetros de subida desde configuración
                max_reintentos = config_dispositivo.get("drive", {}).get("config", {}).get("max_reintentos", 3)
                tiempo_espera = config_dispositivo.get("drive", {}).get("config", {}).get("tiempo_espera", 2)
                drive_id = config_dispositivo.get("drive", {}).get("carpetas", {}).get("mseed_id", "")

                if not drive_id:
                    logger.error("No se encontró el ID de carpeta de Drive 'mseed_id' en configuracion_dispositivo.json")
                else:
                    if dry_run:
                        # Modo dry-run: simular subida sin conectar a Drive
                        logger.info(f"[DRY-RUN] Se subirían {len(archivos_mseed)} archivos a Google Drive")
                        for archivo in archivos_mseed:
                            #logger.info(f"[DRY-RUN] Se subiría: {archivo}")
                            print(f"[DRY-RUN] Se subiría a Drive: {archivo}")
                        logger.info(f"[DRY-RUN] Resumen: {len(archivos_mseed)} archivos preparados para subir")
                    else:
                        # Obtener rutas de configuración
                        credentials_file = os.path.join(project_local_root, "configuracion", "drive_credentials.json")
                        token_file = os.path.join(project_local_root, "configuracion", "drive_token.json")

                        # Autenticar una sola vez para todos los archivos
                        logger.info("Autenticando en Google Drive...")
                        service = Try_Autenticar_Drive(SCOPES, credentials_file, token_file, logger)

                        if service:
                            # Subir todos los archivos usando la misma conexión
                            archivos_subidos_exitosamente = 0
                            for archivo in archivos_mseed:
                                path_completo = os.path.join(mseed_directory, archivo)
                                logger.info(f"Procesando archivo: {archivo}")

                                exito = subir_archivo_con_reintentos(
                                    service=service,
                                    nombre_archivo=archivo,
                                    path_completo_archivo=path_completo,
                                    drive_id=drive_id,
                                    max_reintentos=max_reintentos,
                                    tiempo_espera=tiempo_espera,
                                    logger=logger,
                                    borrar_despues=False
                                )

                                if exito:
                                    archivos_subidos_exitosamente += 1

                            logger.info(f"Resumen: {archivos_subidos_exitosamente}/{len(archivos_mseed)} archivos subidos exitosamente")
                        else:
                            logger.error("No se pudo autenticar en Google Drive. Verifica las credenciales.")
            else:
                logger.warning("No se encontraron archivos mseed en el directorio especificado.")
        else:
             # Si no hay conexion a internet verifica el espacio disponible
            free_space = get_free_space_percentage(mseed_directory)
            logger.info(f"Espacio libre en directorio mseed: {free_space:.2f}%")
            if free_space < min_free_space_threshold:
                logger.warning(f"El espacio disponible es menor al {min_free_space_threshold}%. Se procederá a borrar el archivo mseed más antiguo.")
                delete_oldest_file(mseed_directory, ".mseed", logger, dry_run)
            else:
                logger.info("Espacio disponible suficiente en la partición.")

        # Verificar espacio disponible en el directorio de archivos binarios
        free_space = get_free_space_percentage(binary_directory)
        logger.info(f"Espacio libre en directorio binarios: {free_space:.2f}%")
        if free_space < min_free_space_threshold:
            logger.warning(f"El espacio disponible es menor al {min_free_space_threshold}%. Se procederá a borrar el archivo binario más antiguo.")
            delete_oldest_file(binary_directory, ".dat", logger)
        else:
            logger.info("Espacio disponible suficiente en la partición.")
    
    else:
        logger.error(f"Modo de adquisición desconocido: {mode_acq}")
 

if __name__ == "__main__":
    main()

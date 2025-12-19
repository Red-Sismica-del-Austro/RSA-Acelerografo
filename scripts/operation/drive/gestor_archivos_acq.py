"""
Gestor de archivos para sistema de adquisición de datos sísmicos

DESCRIPCIÓN:
Script que gestiona archivos binarios y miniSEED según el modo de adquisición configurado.
Implementa políticas de gestión de almacenamiento basadas en dos modos de operación:

MODOS DE OPERACIÓN:
- online: Sube archivos a Google Drive, aplica retención temporal y control de espacio
- offline: Maximiza almacenamiento local, retiene solo archivos continuous necesarios

USO:
    python3 gestor_archivos_acq.py              # Ejecución normal
    python3 gestor_archivos_acq.py --dry-run    # Simulación sin cambios reales

MODO DRY-RUN:
El parámetro --dry-run permite simular todas las operaciones sin realizar cambios:
- NO borra archivos locales
- NO sube archivos a Google Drive
- Registra en archivo separado: gestor_acq_dry-run.log
- Muestra qué operaciones se ejecutarían (prefijo [DRY-RUN])
- Útil para verificar comportamiento antes de ejecutar en producción

CONFIGURACIÓN:
El modo de operación y políticas se configuran en configuracion_dispositivo.json:
- dispositivo.modo_adquisicion: "online" o "offline"
- gestion_almacenamiento.umbrales: mínimo y crítico de espacio
- gestion_almacenamiento.politicas: configuración específica por modo

REQUISITOS:
- Variable de entorno PROJECT_LOCAL_ROOT debe estar definida
- Archivo configuracion_dispositivo.json con estructura completa
- Credenciales de Google Drive (para modo online)
"""

import os
import shutil
import socket
import json
import logging
import sys
from datetime import datetime, timedelta
import time

# Importar funciones de subir_archivo.py (mismo directorio)
from subir_archivo import (
    Try_Autenticar_Drive,
    subir_archivo_con_reintentos,
    SCOPES
)

# Importar el gestor de estado de subidas
from drive_status_manager import esta_protegido, ya_fue_subido

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

# ========== FUNCIONES AUXILIARES PARA GESTIÓN DE ARCHIVOS ==========

def obtener_archivo_mas_reciente(directorio, extension):
    """
    Obtiene el archivo más reciente con la extensión especificada.

    Args:
        directorio: Ruta del directorio
        extension: Extensión del archivo (ej: ".dat", ".mseed")

    Returns:
        str: Ruta completa del archivo más reciente, o None si no hay archivos
    """
    try:
        archivos = [os.path.join(directorio, f) for f in os.listdir(directorio) if f.endswith(extension)]
        if not archivos:
            return None
        return max(archivos, key=os.path.getmtime)
    except Exception:
        return None


def calcular_antiguedad_dias(ruta_archivo):
    """
    Calcula la antigüedad de un archivo en días.

    Args:
        ruta_archivo: Ruta completa del archivo

    Returns:
        int: Número de días desde la última modificación
    """
    tiempo_modificacion = os.path.getmtime(ruta_archivo)
    fecha_modificacion = datetime.fromtimestamp(tiempo_modificacion)
    antiguedad = datetime.now() - fecha_modificacion
    return antiguedad.days


def esta_protegido_por_fallo(nombre_archivo, tipo_archivo, log_directory):
    """
    Verifica si un archivo está protegido por haber fallado al subirse.

    Args:
        nombre_archivo: Nombre del archivo (sin ruta)
        tipo_archivo: Tipo de archivo ("continuous", "mseed", etc.)
        log_directory: Directorio de logs

    Returns:
        bool: True si está protegido, False si puede borrarse
    """
    try:
        return esta_protegido(log_directory, nombre_archivo, tipo_archivo)
    except Exception:
        return False


def eliminar_archivo_con_verificacion(ruta_archivo, tipo_archivo, log_directory, logger, dry_run=False):
    """
    Elimina un archivo verificando primero si está protegido.

    Args:
        ruta_archivo: Ruta completa del archivo
        tipo_archivo: Tipo de archivo ("continuous", "mseed", etc.)
        log_directory: Directorio de logs
        logger: Logger para registro
        dry_run: Si True, solo simula la eliminación

    Returns:
        bool: True si se eliminó (o simularía eliminar), False si está protegido
    """
    nombre_archivo = os.path.basename(ruta_archivo)

    # Verificar si está protegido
    if esta_protegido_por_fallo(nombre_archivo, tipo_archivo, log_directory):
        logger.info(f"Archivo protegido (fallo subida) | {tipo_archivo} | {nombre_archivo}")
        return False

    if dry_run:
        logger.info(f"[DRY-RUN] Se borraría | {tipo_archivo} | {nombre_archivo}")
        return True

    try:
        os.remove(ruta_archivo)
        logger.info(f"Archivo eliminado | {tipo_archivo} | {nombre_archivo}")
        return True
    except Exception as e:
        logger.error(f"Error al eliminar | {tipo_archivo} | {nombre_archivo} | {str(e)}")
        return False

#######################################################################################################

def main():
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

    # Detectar modo dry-run
    dry_run = "--dry-run" in sys.argv

    # Inicializa el logger (usa archivo separado si está en dry-run)
    if dry_run:
        logger = obtener_logger(id_estacion, log_directory, "gestor_acq_dry-run.log")
        logger.warning("="*70)
        logger.warning("MODO DRY-RUN ACTIVADO")
        logger.warning("="*70)
        logger.warning("Las operaciones se simularán sin realizar cambios reales.")
        logger.warning("No se subirán archivos ni se borrarán datos.")
        logger.warning("="*70)
    else:
        logger = obtener_logger(id_estacion, log_directory, "gestor_acq.log")

    # ========== VALIDAR MODO DE OPERACIÓN ==========
    # Validar modo
    if mode_acq not in ["online", "offline"]:
        logger.error(f"Modo de adquisición inválido: {mode_acq}. Debe ser 'online' o 'offline'")
        return

    # ========== CARGAR CONFIGURACIÓN DE GESTIÓN DE ALMACENAMIENTO ==========
    gestion_almacenamiento = config_dispositivo.get("gestion_almacenamiento", {})

    # Cargar umbrales
    umbrales = gestion_almacenamiento.get("umbrales", {})
    umbral_minimo = umbrales.get("minimo", 10)
    umbral_critico = umbrales.get("critico", 5)

    # Cargar políticas
    politicas = gestion_almacenamiento.get("politicas", {})
    politica_modo = politicas.get(mode_acq, {})

    # Si no existe la política del modo, usar valores por defecto
    if not politica_modo:
        logger.warning(f"No se encontró política para modo '{mode_acq}'. Usando valores por defecto.")
        if mode_acq == "online":
            politica_modo = {
                "subir": ["mseed"],
                "retener_dias": {"continuous": 30, "mseed": 30}
            }
        elif mode_acq == "offline":
            politica_modo = {
                "subir": [],
                "retener_dias": {"continuous": 7}
            }

    logger.info(f"Configuración cargada | modo: {mode_acq} | umbral_minimo: {umbral_minimo}% | umbral_critico: {umbral_critico}%")

    # Escanear el contenido de los directorios
    try:
        archivos_mseed = [f for f in os.listdir(mseed_directory) if f.endswith(".mseed")]
        archivos_binarios = [f for f in os.listdir(binary_directory) if f.endswith(".dat")]
        logger.info(f"Se encontraron {len(archivos_mseed)} archivos mseed y {len(archivos_binarios)} archivos binarios.")
    except Exception as e:
        logger.error(f"Error al listar archivos en los directorios: {e}")
        return
    
    if mode_acq == "offline":
        logger.info("MODO OFFLINE ACTIVADO")

        # ========== POLÍTICA DE RETENCIÓN TEMPORAL ==========
        retener_dias_continuous = politica_modo.get("retener_dias", {}).get("continuous", 7)

        # Identificar archivo continuous más reciente (está en uso)
        archivo_mas_reciente_continuous = obtener_archivo_mas_reciente(binary_directory, ".dat")

        if archivo_mas_reciente_continuous:
            logger.info(f"Archivo más reciente protegido | continuous | {os.path.basename(archivo_mas_reciente_continuous)}")

        # Listar archivos continuous
        archivos_continuous_paths = [os.path.join(binary_directory, f) for f in archivos_binarios]

        # Eliminar archivos continuous antiguos (excepto el más reciente)
        for ruta_archivo in archivos_continuous_paths:
            # Proteger el más reciente
            if archivo_mas_reciente_continuous and ruta_archivo == archivo_mas_reciente_continuous:
                continue

            # Verificar antigüedad
            antiguedad = calcular_antiguedad_dias(ruta_archivo)
            if antiguedad > retener_dias_continuous:
                nombre_archivo = os.path.basename(ruta_archivo)

                if dry_run:
                    logger.info(f"[DRY-RUN] Se borraría por antigüedad | continuous | {nombre_archivo} | {antiguedad} días")
                else:
                    try:
                        os.remove(ruta_archivo)
                        logger.info(f"Eliminado por antigüedad | continuous | {nombre_archivo} | {antiguedad} días")
                    except Exception as e:
                        logger.error(f"Error al eliminar | continuous | {nombre_archivo} | {str(e)}")

        # ========== POLÍTICA DE CONTROL DE ESPACIO ==========
        free_space = get_free_space_percentage(mseed_directory)
        logger.info(f"Espacio libre | mseed | {free_space:.2f}%")

        # Umbral mínimo
        if free_space < umbral_minimo:
            logger.warning(f"Espacio bajo umbral mínimo | offline | {free_space:.2f}% < {umbral_minimo}%")

            # Eliminar TODOS los archivos continuous excepto el más reciente
            archivos_continuous_paths = [os.path.join(binary_directory, f) for f in os.listdir(binary_directory) if f.endswith(".dat")]
            for ruta_archivo in archivos_continuous_paths:
                if archivo_mas_reciente_continuous and ruta_archivo == archivo_mas_reciente_continuous:
                    continue
                nombre_archivo = os.path.basename(ruta_archivo)

                if dry_run:
                    logger.info(f"[DRY-RUN] Se borraría por espacio | continuous | {nombre_archivo}")
                else:
                    try:
                        os.remove(ruta_archivo)
                        logger.info(f"Eliminado por espacio | continuous | {nombre_archivo}")
                    except Exception as e:
                        logger.error(f"Error al eliminar | continuous | {nombre_archivo} | {str(e)}")

            # Verificar espacio nuevamente
            free_space = get_free_space_percentage(mseed_directory)

            # Si aún bajo umbral, eliminar mseed más antiguo
            if free_space < umbral_minimo:
                logger.warning(f"Espacio insuficiente tras eliminar continuous | offline | {free_space:.2f}%")
                delete_oldest_file(mseed_directory, ".mseed", logger, dry_run)

        # Umbral crítico
        if free_space < umbral_critico:
            logger.warning(f"Espacio crítico en modo offline - intervención necesaria | offline | {free_space:.2f}% < {umbral_critico}%")

            # Eliminar mseed más antiguo (FIFO)
            delete_oldest_file(mseed_directory, ".mseed", logger, dry_run)
    
    elif mode_acq == "online":
        logger.info("MODO ONLINE ACTIVADO")

        # Detectar conectividad
        tiene_conexion = check_internet_connection(logger)

        if tiene_conexion:
            logger.info("Conexión a internet | online | disponible")

            # ========== POLÍTICA DE SUBIDA A DRIVE ==========
            tipos_a_subir = politica_modo.get("subir", [])

            # Preparar archivos para subir (empezar por los más antiguos)
            archivos_para_subir = []
            archivos_ya_subidos_count = 0

            if "mseed" in tipos_a_subir:
                archivos_mseed_paths = [os.path.join(mseed_directory, f) for f in archivos_mseed]
                archivos_mseed_ordenados = sorted(archivos_mseed_paths, key=os.path.getmtime)
                for path in archivos_mseed_ordenados:
                    nombre_archivo = os.path.basename(path)
                    # Verificar si ya fue subido
                    if ya_fue_subido(log_directory, nombre_archivo, "mseed"):
                        archivos_ya_subidos_count += 1
                        logger.info(f"Archivo ya subido previamente | mseed | {nombre_archivo}")
                    else:
                        archivos_para_subir.append((path, "mseed"))

            if "continuous" in tipos_a_subir:
                archivos_binarios_paths = [os.path.join(binary_directory, f) for f in archivos_binarios]
                archivos_binarios_ordenados = sorted(archivos_binarios_paths, key=os.path.getmtime)
                # Proteger el más reciente (está en uso)
                archivo_mas_reciente_continuous = obtener_archivo_mas_reciente(binary_directory, ".dat")
                for path in archivos_binarios_ordenados:
                    nombre_archivo = os.path.basename(path)
                    # Proteger el más reciente
                    if archivo_mas_reciente_continuous and path == archivo_mas_reciente_continuous:
                        continue
                    # Verificar si ya fue subido
                    if ya_fue_subido(log_directory, nombre_archivo, "continuous"):
                        archivos_ya_subidos_count += 1
                        logger.info(f"Archivo ya subido previamente | continuous | {nombre_archivo}")
                    else:
                        archivos_para_subir.append((path, "continuous"))

            # Registrar resumen de archivos ya subidos
            if archivos_ya_subidos_count > 0:
                logger.info(f"Archivos omitidos (ya subidos) | online | {archivos_ya_subidos_count} archivos")

            # Subir archivos si hay alguno configurado
            if archivos_para_subir:
                if dry_run:
                    logger.info(f"[DRY-RUN] Se subirían {len(archivos_para_subir)} archivos a Google Drive")
                    for path_completo, tipo_archivo in archivos_para_subir:
                        nombre_archivo = os.path.basename(path_completo)
                        logger.info(f"[DRY-RUN] Se subiría | {tipo_archivo} | {nombre_archivo}")
                else:
                    logger.info(f"Archivos pendientes de subida | online | {len(archivos_para_subir)} archivos")

                    # Obtener parámetros de Drive
                    max_reintentos = config_dispositivo.get("drive", {}).get("config", {}).get("max_reintentos", 3)
                    tiempo_espera = config_dispositivo.get("drive", {}).get("config", {}).get("tiempo_espera", 2)
                    credentials_file = os.path.join(project_local_root, "configuracion", "drive_credentials.json")
                    token_file = os.path.join(project_local_root, "configuracion", "drive_token.json")

                    # Autenticar una sola vez
                    logger.info("Autenticando en Google Drive | online")
                    service = Try_Autenticar_Drive(SCOPES, credentials_file, token_file, logger)

                    if service:
                        archivos_subidos = 0
                        for path_completo, tipo_archivo in archivos_para_subir:
                            nombre_archivo = os.path.basename(path_completo)

                            # Obtener drive_id según tipo
                            if tipo_archivo == "mseed":
                                drive_id = config_dispositivo.get("drive", {}).get("carpetas", {}).get("mseed_id", "")
                            elif tipo_archivo == "continuous":
                                drive_id = config_dispositivo.get("drive", {}).get("carpetas", {}).get("continuos_id", "")
                            else:
                                logger.warning(f"Tipo de archivo desconocido | {tipo_archivo} | {nombre_archivo}")
                                continue

                            if not drive_id:
                                logger.error(f"ID de carpeta Drive no encontrado | {tipo_archivo}")
                                continue

                            logger.info(f"Subiendo archivo | {tipo_archivo} | {nombre_archivo}")

                            exito = subir_archivo_con_reintentos(
                                service=service,
                                nombre_archivo=nombre_archivo,
                                path_completo_archivo=path_completo,
                                drive_id=drive_id,
                                max_reintentos=max_reintentos,
                                tiempo_espera=tiempo_espera,
                                logger=logger,
                                borrar_despues=False,
                                tipo_archivo=tipo_archivo,
                                log_directory=log_directory
                            )

                            if exito:
                                archivos_subidos += 1

                        logger.info(f"Resumen subida | online | {archivos_subidos}/{len(archivos_para_subir)} archivos subidos")
                    else:
                        logger.error("Autenticación fallida | online | verificar credenciales")
            else:
                # No hay archivos para subir
                if archivos_ya_subidos_count > 0:
                    logger.info(f"Sin archivos pendientes | online | todos ya fueron subidos previamente")
                else:
                    logger.info(f"Sin archivos para subir | online | no hay archivos configurados para subida")

            # ========== POLÍTICA DE RETENCIÓN TEMPORAL ==========
            retener_dias = politica_modo.get("retener_dias", {})

            # Identificar archivo continuous más reciente (está en uso)
            archivo_mas_reciente_continuous = obtener_archivo_mas_reciente(binary_directory, ".dat")
            if archivo_mas_reciente_continuous:
                logger.info(f"Archivo más reciente protegido | continuous | {os.path.basename(archivo_mas_reciente_continuous)}")

            # Eliminar continuous antiguos (excepto el más reciente y los fallidos)
            if "continuous" in retener_dias:
                dias_continuous = retener_dias["continuous"]
                archivos_continuous_paths = [os.path.join(binary_directory, f) for f in archivos_binarios]

                for ruta_archivo in archivos_continuous_paths:
                    # Proteger el más reciente
                    if archivo_mas_reciente_continuous and ruta_archivo == archivo_mas_reciente_continuous:
                        continue

                    # Verificar antigüedad
                    antiguedad = calcular_antiguedad_dias(ruta_archivo)
                    if antiguedad > dias_continuous:
                        # Intentar eliminar (verifica automáticamente si está protegido)
                        eliminado = eliminar_archivo_con_verificacion(
                            ruta_archivo, "continuous", log_directory, logger, dry_run
                        )
                        if eliminado:
                            logger.info(f"Eliminado por antigüedad | continuous | {os.path.basename(ruta_archivo)} | {antiguedad} días")

            # Eliminar mseed antiguos (solo los que NO están protegidos por fallo de subida)
            if "mseed" in retener_dias:
                dias_mseed = retener_dias["mseed"]
                archivos_mseed_paths = [os.path.join(mseed_directory, f) for f in archivos_mseed]

                for ruta_archivo in archivos_mseed_paths:
                    antiguedad = calcular_antiguedad_dias(ruta_archivo)
                    if antiguedad > dias_mseed:
                        # Intentar eliminar (verifica automáticamente si está protegido)
                        eliminado = eliminar_archivo_con_verificacion(
                            ruta_archivo, "mseed", log_directory, logger, dry_run
                        )
                        if eliminado:
                            logger.info(f"Eliminado por antigüedad | mseed | {os.path.basename(ruta_archivo)} | {antiguedad} días")

            # ========== POLÍTICA DE CONTROL DE ESPACIO ==========
            free_space = get_free_space_percentage(mseed_directory)
            logger.info(f"Espacio libre | mseed | {free_space:.2f}%")

            # Umbral mínimo
            if free_space < umbral_minimo:
                logger.warning(f"Espacio bajo umbral mínimo | online | {free_space:.2f}% < {umbral_minimo}%")

                # Eliminar archivos continuous antiguos (excepto el más reciente)
                archivos_continuous_paths = [os.path.join(binary_directory, f) for f in os.listdir(binary_directory) if f.endswith(".dat")]
                archivos_continuous_ordenados = sorted(archivos_continuous_paths, key=os.path.getmtime)

                for ruta_archivo in archivos_continuous_ordenados:
                    if archivo_mas_reciente_continuous and ruta_archivo == archivo_mas_reciente_continuous:
                        continue

                    eliminado = eliminar_archivo_con_verificacion(
                        ruta_archivo, "continuous", log_directory, logger, dry_run
                    )
                    if eliminado:
                        logger.info(f"Eliminado por espacio | continuous | {os.path.basename(ruta_archivo)}")

                # Verificar espacio nuevamente
                free_space = get_free_space_percentage(mseed_directory)

                # Si aún bajo umbral, eliminar mseed más antiguo (verificando que no esté protegido)
                if free_space < umbral_minimo:
                    logger.warning(f"Espacio insuficiente tras eliminar continuous | online | {free_space:.2f}%")

                    archivos_mseed_paths = [os.path.join(mseed_directory, f) for f in os.listdir(mseed_directory) if f.endswith(".mseed")]
                    archivos_mseed_ordenados = sorted(archivos_mseed_paths, key=os.path.getmtime)

                    for ruta_archivo in archivos_mseed_ordenados:
                        eliminado = eliminar_archivo_con_verificacion(
                            ruta_archivo, "mseed", log_directory, logger, dry_run
                        )
                        if eliminado:
                            logger.info(f"Eliminado por espacio | mseed | {os.path.basename(ruta_archivo)}")
                            break  # Eliminar solo uno a la vez

            # Umbral crítico
            if free_space < umbral_critico:
                logger.warning(f"Espacio crítico | online | {free_space:.2f}% < {umbral_critico}%")

                # Eliminar TODOS los continuous (excepto el más reciente)
                archivos_continuous_paths = [os.path.join(binary_directory, f) for f in os.listdir(binary_directory) if f.endswith(".dat")]
                for ruta_archivo in archivos_continuous_paths:
                    if archivo_mas_reciente_continuous and ruta_archivo == archivo_mas_reciente_continuous:
                        continue

                    eliminado = eliminar_archivo_con_verificacion(
                        ruta_archivo, "continuous", log_directory, logger, dry_run
                    )
                    if eliminado:
                        logger.info(f"Eliminado por espacio crítico | continuous | {os.path.basename(ruta_archivo)}")

                # Verificar espacio nuevamente
                free_space = get_free_space_percentage(mseed_directory)

                # Si aún crítico, eliminar mseed más antiguos (FIFO, verificando protección)
                if free_space < umbral_critico:
                    archivos_mseed_paths = [os.path.join(mseed_directory, f) for f in os.listdir(mseed_directory) if f.endswith(".mseed")]
                    archivos_mseed_ordenados = sorted(archivos_mseed_paths, key=os.path.getmtime)

                    for ruta_archivo in archivos_mseed_ordenados:
                        eliminado = eliminar_archivo_con_verificacion(
                            ruta_archivo, "mseed", log_directory, logger, dry_run
                        )
                        if eliminado:
                            logger.info(f"Eliminado por espacio crítico | mseed | {os.path.basename(ruta_archivo)}")
                            # Verificar si ya se alcanzó el umbral
                            free_space = get_free_space_percentage(mseed_directory)
                            if free_space >= umbral_critico:
                                break

        else:
            # ========== MODO ONLINE SIN CONECTIVIDAD ==========
            logger.warning("Modo online sin conectividad | online | acumulando archivos")

            # Solo aplicar control de espacio (no subir, no eliminar por retención)
            free_space = get_free_space_percentage(mseed_directory)
            logger.info(f"Espacio libre | mseed | {free_space:.2f}%")

            # Identificar archivo continuous más reciente
            archivo_mas_reciente_continuous = obtener_archivo_mas_reciente(binary_directory, ".dat")
            if archivo_mas_reciente_continuous:
                logger.info(f"Archivo más reciente protegido | continuous | {os.path.basename(archivo_mas_reciente_continuous)}")

            # Umbral mínimo
            if free_space < umbral_minimo:
                logger.warning(f"Espacio bajo umbral mínimo | online-sin-conexión | {free_space:.2f}% < {umbral_minimo}%")

                # Eliminar continuous más antiguo
                archivos_continuous_paths = [os.path.join(binary_directory, f) for f in os.listdir(binary_directory) if f.endswith(".dat")]
                archivos_continuous_ordenados = sorted(archivos_continuous_paths, key=os.path.getmtime)

                for ruta_archivo in archivos_continuous_ordenados:
                    if archivo_mas_reciente_continuous and ruta_archivo == archivo_mas_reciente_continuous:
                        continue

                    nombre_archivo = os.path.basename(ruta_archivo)

                    if dry_run:
                        logger.info(f"[DRY-RUN] Se borraría por espacio | continuous | {nombre_archivo}")
                        break
                    else:
                        try:
                            os.remove(ruta_archivo)
                            logger.info(f"Eliminado por espacio | continuous | {nombre_archivo}")
                            break
                        except Exception as e:
                            logger.error(f"Error al eliminar | continuous | {nombre_archivo} | {str(e)}")

                # Verificar espacio nuevamente
                free_space = get_free_space_percentage(mseed_directory)

                # Si aún bajo umbral, eliminar mseed más antiguo (FIFO)
                if free_space < umbral_minimo:
                    logger.warning(f"Espacio insuficiente | online-sin-conexión | {free_space:.2f}%")
                    delete_oldest_file(mseed_directory, ".mseed", logger, dry_run)

            # Umbral crítico
            if free_space < umbral_critico:
                logger.warning(f"Espacio crítico | online-sin-conexión | {free_space:.2f}% < {umbral_critico}%")
                delete_oldest_file(mseed_directory, ".mseed", logger, dry_run)

    else:
        logger.error(f"Modo de adquisición desconocido: {mode_acq}")
 

if __name__ == "__main__":
    main()

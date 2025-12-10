"""
Módulo para gestionar el estado de subidas fallidas a Google Drive

Este módulo maneja un archivo JSON que registra los archivos que fallaron
al subirse a Google Drive, permitiendo protegerlos de ser borrados por
el gestor de archivos.

Estructura del JSON:
{
  "archivos_fallidos": {
    "mseed": {
      "archivo.mseed": {"fecha": "2025-12-10 15:00:00", "intentos": 5}
    },
    "dat": {},
    "tmp": {},
    "log": {}
  }
}
"""

import json
import os
from datetime import datetime
from threading import Lock

# Lock para operaciones thread-safe
_file_lock = Lock()

# Tipos de archivo soportados
TIPOS_ARCHIVO = ["mseed", "dat", "tmp", "log"]


def _obtener_ruta_json(log_directory):
    """Obtiene la ruta completa del archivo JSON de estado"""
    return os.path.join(log_directory, "drive_upload_failures.json")


def _inicializar_estructura():
    """Retorna la estructura inicial del JSON"""
    return {
        "archivos_fallidos": {
            "mseed": {},
            "dat": {},
            "tmp": {},
            "log": {}
        }
    }


def _leer_json(log_directory):
    """
    Lee el archivo JSON de estado. Si no existe, crea uno nuevo.

    Args:
        log_directory: Directorio donde se guarda el JSON

    Returns:
        dict: Estructura de datos del JSON
    """
    ruta_json = _obtener_ruta_json(log_directory)

    if not os.path.exists(ruta_json):
        return _inicializar_estructura()

    try:
        with open(ruta_json, 'r') as f:
            data = json.load(f)

        # Validar estructura
        if "archivos_fallidos" not in data:
            return _inicializar_estructura()

        # Asegurar que existan todas las claves de tipos
        for tipo in TIPOS_ARCHIVO:
            if tipo not in data["archivos_fallidos"]:
                data["archivos_fallidos"][tipo] = {}

        return data

    except (json.JSONDecodeError, IOError) as e:
        print(f"Error al leer {ruta_json}: {e}. Creando estructura nueva.")
        return _inicializar_estructura()


def _escribir_json(log_directory, data):
    """
    Escribe el archivo JSON de estado de forma segura.

    Args:
        log_directory: Directorio donde se guarda el JSON
        data: Estructura de datos a escribir
    """
    ruta_json = _obtener_ruta_json(log_directory)

    # Crear directorio si no existe
    if not os.path.exists(log_directory):
        os.makedirs(log_directory)

    try:
        # Escribir a archivo temporal primero (atomic write)
        ruta_temp = ruta_json + '.tmp'
        with open(ruta_temp, 'w') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

        # Renombrar (operación atómica en sistemas UNIX)
        os.replace(ruta_temp, ruta_json)

    except IOError as e:
        print(f"Error al escribir {ruta_json}: {e}")


def marcar_como_fallido(log_directory, nombre_archivo, tipo_archivo, intentos, logger=None):
    """
    Marca un archivo como fallido en la subida a Google Drive.

    Args:
        log_directory: Directorio donde se guarda el JSON
        nombre_archivo: Nombre del archivo que falló
        tipo_archivo: Tipo de archivo ("mseed", "dat", "tmp", "log")
        intentos: Número de intentos realizados
        logger: Logger opcional para registrar la operación
    """
    if tipo_archivo not in TIPOS_ARCHIVO:
        raise ValueError(f"Tipo de archivo inválido: {tipo_archivo}. Debe ser uno de {TIPOS_ARCHIVO}")

    with _file_lock:
        data = _leer_json(log_directory)

        # Agregar o actualizar el archivo fallido
        data["archivos_fallidos"][tipo_archivo][nombre_archivo] = {
            "fecha": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "intentos": intentos
        }

        _escribir_json(log_directory, data)

        if logger:
            logger.warning(f"Archivo marcado como fallido: {nombre_archivo} (tipo: {tipo_archivo}, intentos: {intentos})")


def marcar_como_exitoso(log_directory, nombre_archivo, tipo_archivo, logger=None):
    """
    Remueve un archivo de la lista de fallidos (indica subida exitosa).

    Args:
        log_directory: Directorio donde se guarda el JSON
        nombre_archivo: Nombre del archivo que se subió exitosamente
        tipo_archivo: Tipo de archivo ("mseed", "dat", "tmp", "log")
        logger: Logger opcional para registrar la operación
    """
    if tipo_archivo not in TIPOS_ARCHIVO:
        raise ValueError(f"Tipo de archivo inválido: {tipo_archivo}. Debe ser uno de {TIPOS_ARCHIVO}")

    with _file_lock:
        data = _leer_json(log_directory)

        # Remover el archivo de fallidos si existe
        if nombre_archivo in data["archivos_fallidos"][tipo_archivo]:
            del data["archivos_fallidos"][tipo_archivo][nombre_archivo]
            _escribir_json(log_directory, data)

            if logger:
                logger.info(f"Archivo removido de fallidos (subida exitosa): {nombre_archivo}")


def esta_protegido(log_directory, nombre_archivo, tipo_archivo):
    """
    Verifica si un archivo está protegido (falló al subirse).

    Args:
        log_directory: Directorio donde se guarda el JSON
        nombre_archivo: Nombre del archivo a verificar
        tipo_archivo: Tipo de archivo ("mseed", "dat", "tmp", "log")

    Returns:
        bool: True si el archivo está en la lista de fallidos, False si puede borrarse
    """
    if tipo_archivo not in TIPOS_ARCHIVO:
        return False

    with _file_lock:
        data = _leer_json(log_directory)
        return nombre_archivo in data["archivos_fallidos"][tipo_archivo]


def obtener_archivos_fallidos(log_directory, tipo_archivo=None):
    """
    Obtiene la lista de archivos fallidos.

    Args:
        log_directory: Directorio donde se guarda el JSON
        tipo_archivo: Tipo específico a consultar, o None para todos

    Returns:
        dict o list: Diccionario completo o lista de archivos según tipo
    """
    with _file_lock:
        data = _leer_json(log_directory)

        if tipo_archivo:
            if tipo_archivo not in TIPOS_ARCHIVO:
                return {}
            return data["archivos_fallidos"][tipo_archivo]

        return data["archivos_fallidos"]


def limpiar_archivos_inexistentes(log_directory, directorios_por_tipo, logger=None):
    """
    Limpia del JSON archivos que ya no existen en el sistema de archivos.

    Args:
        log_directory: Directorio donde se guarda el JSON
        directorios_por_tipo: Dict con mapeo tipo -> ruta_directorio
            Ej: {"mseed": "/ruta/mseed", "dat": "/ruta/dat"}
        logger: Logger opcional para registrar la operación
    """
    with _file_lock:
        data = _leer_json(log_directory)
        archivos_removidos = 0

        for tipo, directorio in directorios_por_tipo.items():
            if tipo not in TIPOS_ARCHIVO:
                continue

            archivos_a_remover = []

            for nombre_archivo in data["archivos_fallidos"][tipo]:
                ruta_completa = os.path.join(directorio, nombre_archivo)
                if not os.path.exists(ruta_completa):
                    archivos_a_remover.append(nombre_archivo)

            # Remover archivos inexistentes
            for nombre_archivo in archivos_a_remover:
                del data["archivos_fallidos"][tipo][nombre_archivo]
                archivos_removidos += 1
                if logger:
                    logger.info(f"Removido de fallidos (archivo ya no existe): {nombre_archivo}")

        if archivos_removidos > 0:
            _escribir_json(log_directory, data)
            if logger:
                logger.info(f"Limpieza completada: {archivos_removidos} archivos removidos del registro de fallidos")


def obtener_estadisticas(log_directory):
    """
    Obtiene estadísticas de archivos fallidos.

    Args:
        log_directory: Directorio donde se guarda el JSON

    Returns:
        dict: Estadísticas por tipo de archivo
    """
    with _file_lock:
        data = _leer_json(log_directory)

        estadisticas = {}
        for tipo in TIPOS_ARCHIVO:
            estadisticas[tipo] = len(data["archivos_fallidos"][tipo])

        estadisticas["total"] = sum(estadisticas.values())

        return estadisticas

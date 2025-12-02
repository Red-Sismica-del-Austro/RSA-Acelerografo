"""
Script de conversión de archivos binarios (.dat) a formato miniSEED (.mseed)

EJEMPLOS DE USO:

1. Modo simple (sintaxis corta):
   python3 binary_to_mseed.py 1                                          # Registro continuo
   python3 binary_to_mseed.py 2                                          # Evento extraído
   python3 binary_to_mseed.py 3 archivo.dat                              # Conversión manual (nombre)
   python3 binary_to_mseed.py 3 /ruta/completa/archivo.dat              # Conversión manual (ruta absoluta)

2. Modo con flags (sintaxis descriptiva):
   python3 binary_to_mseed.py --continuous                               # Registro continuo
   python3 binary_to_mseed.py --event                                    # Evento extraído
   python3 binary_to_mseed.py --file archivo.dat                         # Conversión manual (nombre)
   python3 binary_to_mseed.py --file /ruta/completa/archivo.dat         # Conversión manual (ruta absoluta)

DESCRIPCIÓN DE MODOS:

- Modo 1 (--continuous):
    Lee el nombre del archivo desde NombreArchivoRegistroContinuo.tmp
    Busca en: directorios.registro_continuo (del JSON)
    Guarda en: directorios.archivos_mseed (del JSON)

- Modo 2 (--event):
    Lee el nombre del archivo desde NombreArchivoEventoExtraido.tmp
    Busca en: directorios.eventos_extraidos (del JSON)
    Guarda en: directorios.eventos_extraidos (del JSON)

- Modo 3 (--file):
    Especifica manualmente el archivo a convertir
    Si la ruta es absoluta, usa esa ruta directamente
    Si es solo el nombre, busca en: directorios.registro_continuo (del JSON)
    Guarda en: directorios.archivos_mseed (del JSON)

REQUISITOS:

- Variable de entorno PROJECT_LOCAL_ROOT debe estar definida
- Archivos de configuración necesarios:
    * configuracion_dispositivo.json
    * configuracion_mseed.json
"""

######################################### ~Librerias~ #################################################
import numpy as np
from obspy import UTCDateTime, read, Trace, Stream
import os
import subprocess
import time
import sys
import json
from time import time as timer
import logging
import datetime
import argparse
#######################################################################################################

##################################### ~Variables globales~ ############################################
loggers = {}
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
    

def leer_archivo_binario_0(archivo_binario, logger):
    start_time = timer()
    datos = [[], [], []]
    tiempos = []

    chunk_size = 2506 * 60  # Leer en bloques de aproximadamente 2.5 MB
    with open(archivo_binario, "rb") as f:
        while True:
            chunk = np.fromfile(f, dtype=np.uint8, count=chunk_size)
            if chunk.size == 0:
                break

            num_tramas = len(chunk) // 2506
            if num_tramas == 0:
                continue

            chunk = chunk[:num_tramas * 2506].reshape((num_tramas, 2506))

            horas = chunk[:, 2503].astype(np.uint32)
            minutos = chunk[:, 2504].astype(np.uint32)
            segundos = chunk[:, 2505].astype(np.uint32)


            #n_segundos = horas * 3600 + minutos * 60 + segundos
            #tiempos.extend(n_segundos)
            for h, m, s in zip(horas, minutos, segundos):
                if h > 23 or m > 59 or s > 59:
                    logger.warning(f"Trama con tiempo inválido detectado: {h:02}:{m:02}:{s:02}")
                    continue
                tiempos.append(h * 3600 + m * 60 + s)

            
            # Procesar los datos de forma vectorizada
            datos_crudos = chunk[:, :2500].reshape((-1, 250, 10))

            for j in range(3):
                dato_1 = datos_crudos[:, :, j * 3 + 1].flatten()
                dato_2 = datos_crudos[:, :, j * 3 + 2].flatten()
                dato_3 = datos_crudos[:, :, j * 3 + 3].flatten()

                xValue = ((dato_1.astype(np.uint32) << 12) & 0xFF000) + \
                         ((dato_2.astype(np.uint32) << 4) & 0xFF0) + \
                         ((dato_3.astype(np.uint32) >> 4) & 0xF)

                # Convertir xValue a int32 para manejar valores negativos
                xValue = xValue.astype(np.int32)
                mask = xValue >= 0x80000
                xValue[mask] = -1 * ((~xValue[mask] + 1) & 0x7FFFF)

                datos[j].extend(xValue)

    datos_np = np.array(datos)

    logger.info(f"Archivo {os.path.basename(archivo_binario)} leido con exito")

    # Detectar segundos faltantes en el array tiempos
    tiempos_np = np.array(tiempos)
    segundos_faltantes = []
    dif_segundos = np.diff(tiempos_np)


    # Validación de saltos anómalos
    saltos_grandes = dif_segundos[dif_segundos > 1]
    if len(saltos_grandes) > 0:
         top5 = [int(x) for x in sorted(saltos_grandes)[-5:]]
         total_faltantes = sum(int(x - 1) for x in saltos_grandes)
         logger.warning(f"Detectados {len(saltos_grandes)} saltos mayores a 1 segundo (total {total_faltantes} segundos faltantes). Top 5: {top5}")


    missing_indices = np.where(dif_segundos > 1)[0]
    for idx in missing_indices:
        segundos_faltantes.extend(range(tiempos_np[idx] + 1, tiempos_np[idx + 1]))

    tiempo_incio = datetime.timedelta(seconds=int(tiempos_np[0]))
    tiempo_final = datetime.timedelta(seconds=int(tiempos_np[-1]))
    
    # Imprimir primeros y últimos elementos de tiempos_np y segundos_faltantes
    print(f"Primer elemento de tiempos_np: {tiempos_np[0]}")
    print(f"Último elemento de tiempos_np: {tiempos_np[-1]}")
    print(f"Tiempo primer elemento: {tiempo_incio}")
    print(f"Tiempo ultimo elemento: {tiempo_final}")

    if segundos_faltantes:
        logger.warning(f"Tiempo primera muestra: {tiempo_incio}. Tiempo ultima muestra: {tiempo_final}")
    else:
        logger.info(f"Tiempo primera muestra: {tiempo_incio}. Tiempo ultima muestra: {tiempo_final}")

    end_time = timer()
    print(f"Tiempo de ejecución de leer_archivo_binario: {end_time - start_time:.4f} segundos")
    return datos_np, segundos_faltantes if segundos_faltantes else None

def leer_archivo_binario(archivo_binario, logger):
    start_time = timer()
    datos = [[], [], []]
    tiempos = []

    chunk_size = 2506 * 60  # Leer en bloques de aproximadamente 2.5 MB
    with open(archivo_binario, "rb") as f:
        while True:
            chunk = np.fromfile(f, dtype=np.uint8, count=chunk_size)
            if chunk.size == 0:
                break

            num_tramas = len(chunk) // 2506
            if num_tramas == 0:
                continue

            chunk = chunk[:num_tramas * 2506].reshape((num_tramas, 2506))

            horas = chunk[:, 2503].astype(np.uint32)
            minutos = chunk[:, 2504].astype(np.uint32)
            segundos = chunk[:, 2505].astype(np.uint32)

            # Crear máscara de tramas con tiempos válidos
            mascara_valida = (horas <= 23) & (minutos <= 59) & (segundos <= 59)
            tramas_invalidas = (~mascara_valida).sum()

            for h, m, s, valido in zip(horas, minutos, segundos, mascara_valida):
                if not valido:
                    logger.warning(f"Trama con tiempo inválido detectado: {h:02}:{m:02}:{s:02}")
                    continue
                tiempos.append(h * 3600 + m * 60 + s)

            # Filtrar datos crudos solo con tramas válidas
            chunk_valido = chunk[mascara_valida]
            datos_crudos = chunk_valido[:, :2500].reshape((-1, 250, 10))

            for j in range(3):
                dato_1 = datos_crudos[:, :, j * 3 + 1].flatten()
                dato_2 = datos_crudos[:, :, j * 3 + 2].flatten()
                dato_3 = datos_crudos[:, :, j * 3 + 3].flatten()

                xValue = ((dato_1.astype(np.uint32) << 12) & 0xFF000) + \
                         ((dato_2.astype(np.uint32) << 4) & 0xFF0) + \
                         ((dato_3.astype(np.uint32) >> 4) & 0xF)

                xValue = xValue.astype(np.int32)
                mask = xValue >= 0x80000
                xValue[mask] = -1 * ((~xValue[mask] + 1) & 0x7FFFF)

                datos[j].extend(xValue)

    datos_np = np.array(datos)

    logger.info(f"Archivo {os.path.basename(archivo_binario)} leído con éxito")

    if tramas_invalidas > 0:
        logger.warning(f"Se descartaron {tramas_invalidas} tramas con tiempo inválido para mantener la alineación de datos.")

    tiempos_np = np.array(tiempos)
    segundos_faltantes = []
    dif_segundos = np.diff(tiempos_np)

    # Validación de saltos anómalos
    saltos_grandes = dif_segundos[dif_segundos > 1]
    if len(saltos_grandes) > 0:
        top5 = [int(x) for x in sorted(saltos_grandes)[-5:]]
        total_faltantes = sum(int(x - 1) for x in saltos_grandes)
        logger.warning(f" Segundos faltantes: {total_faltantes}. Saltos mayores a 1 segundo: {len(saltos_grandes)}. Top 5: {top5}")

    missing_indices = np.where(dif_segundos > 1)[0]
    for idx in missing_indices:
        segundos_faltantes.extend(range(tiempos_np[idx] + 1, tiempos_np[idx + 1]))

    tiempo_inicio = datetime.timedelta(seconds=int(tiempos_np[0]))
    tiempo_final = datetime.timedelta(seconds=int(tiempos_np[-1]))

    print(f"Primer elemento de tiempos_np: {tiempos_np[0]}")
    print(f"Último elemento de tiempos_np: {tiempos_np[-1]}")
    print(f"Tiempo primer elemento: {tiempo_inicio}")
    print(f"Tiempo último elemento: {tiempo_final}")

    logger.info(f"Tiempo primera muestra: {tiempo_inicio}. Tiempo última muestra: {tiempo_final}")

    end_time = timer()
    print(f"Tiempo de ejecución de leer_archivo_binario: {end_time - start_time:.4f} segundos")
    return datos_np, segundos_faltantes if segundos_faltantes else None


# Extrae y convierte valores de tiempo del archivo binario y los devuelve en un diccionario.
def extraer_tiempo_binario(archivo):
    # Abrir el archivo en modo de lectura binaria
    with open(archivo, "rb") as f:
        # Leer 2506 bytes del archivo y almacenarlos en un arreglo de numpy
        tramaDatos = np.fromfile(f, np.int8, 2506)
    
    if tramaDatos.size < 2506:
        print("Error: Tamaño de trama insuficiente. Archivo binario podría estar dañado o incompleto.")
        return
    
    # Extraer valores de tiempo de posiciones específicas
    hora = int(tramaDatos[2503])
    minuto = int(tramaDatos[2504])
    segundo = int(tramaDatos[2505])
    n_segundo = hora * 3600 + minuto * 60 + segundo
    
    anio = int(tramaDatos[2500]) + 2000
    mes = int(tramaDatos[2501])
    dia = int(tramaDatos[2502])
       
    # Crear diccionario de resultados con valores numéricos y cadenas formateadas
    tiempo_binario = {
        "anio": anio,
        "anio_s": str(anio),
        "mes": mes,
        "mes_s": str(mes).zfill(2),
        "dia": dia,
        "dia_s": str(dia).zfill(2),
        "hora": hora,
        "hora_s": str(hora).zfill(2),
        "minuto": minuto,
        "minuto_s": str(minuto).zfill(2),
        "segundo": segundo,
        "segundo_s": str(segundo).zfill(2),
        "n_segundo": n_segundo
    }
    return(tiempo_binario)


# Genera el nombre del archivo Mini-SEED basado en el tipo de archivo, el código de estación y el tiempo extraído.
def nombrar_archivo_mseed(codigo_estacion,tiempo_binario):
    # Formatear fecha y hora como cadenas
    fecha_string = tiempo_binario["anio_s"] + tiempo_binario["mes_s"] + tiempo_binario["dia_s"]
    hora_string = tiempo_binario["hora_s"] + tiempo_binario["minuto_s"] + tiempo_binario["segundo_s"]
    
    fileName = f'{codigo_estacion}_{fecha_string}_{hora_string}.mseed'

    print(fileName)
    return fileName
    

# Convierte los datos procesados del archivo binario a formato Mini-SEED y los guarda con el nombre especificado.
def conversion_mseed_digital(fileName, path, tiempo_binario, datos_archivo_binario, segundos_faltantes, parametros_mseed, logger):
    nombre = parametros_mseed["SENSOR(2)"]

    # Crear trazas para cada canal
    trazaCH1 = obtenerTraza(nombre, 1, datos_archivo_binario[0], tiempo_binario, segundos_faltantes, parametros_mseed)
    trazaCH2 = obtenerTraza(nombre, 2, datos_archivo_binario[1], tiempo_binario, segundos_faltantes, parametros_mseed)        
    trazaCH3 = obtenerTraza(nombre, 3, datos_archivo_binario[2], tiempo_binario, segundos_faltantes, parametros_mseed)

    # Crear un objeto Stream con las trazas
    stData = Stream(traces=[trazaCH1, trazaCH2, trazaCH3])

    fileNameCompleto = path + fileName
    
    stData.write(fileNameCompleto, format='MSEED', encoding='STEIM1', reclen=512)
    print('Se ha creado el archivo: %s' %fileNameCompleto)
    logger.info(f"Archivo {fileName} creado con exito")


# Crea una traza de datos con los parámetros especificados y ajusta los datos para incluir ceros en los segundos faltantes si es necesario.
def obtenerTraza(nombreCanal, num_canal, data, tiempo_binario, segundos_faltantes, parametros_mseed):
    anio = tiempo_binario["anio"]
    mes = tiempo_binario["mes"]
    dia = tiempo_binario["dia"]
    horas = tiempo_binario["hora"]
    minutos = tiempo_binario["minuto"]
    segundos = tiempo_binario["segundo"]
    microsegundos = 0  # Si siempre es 0, podemos establecerlo aquí directamente

    fsample = int(parametros_mseed["MUESTREO(20)"])
    calidad = parametros_mseed["CALIDAD(16)"]

    # Determinar el prefijo del nombre del canal basado en la frecuencia de muestreo
    if fsample > 80:
        nombreCanal = 'E'
    else:
        nombreCanal = 'S'

    # Añadir el sufijo basado en el tipo de sensor
    if parametros_mseed["SENSOR(2)"] == 'SISMICO':
        nombreCanal += 'L'
    else:
        nombreCanal += 'N'

    # Determinar el índice del canal
    num_canal = num_canal - 3 * (int((num_canal - 1) / 3))
    nombreCanal += parametros_mseed["CANAL(18)"][num_canal - 1:num_canal]

    # Crear diccionario de estadísticas
    stats = {
        'network': parametros_mseed["RED(19)"],
        'station': parametros_mseed["CODIGO(1)"],
        'location': str(parametros_mseed["UBICACION(17)"]),  # Convertir a cadena
        'channel': nombreCanal,
        'npts': len(data),
        'sampling_rate': fsample,
        'mseed': {'dataquality': calidad},
        'starttime': UTCDateTime(anio, mes, dia, horas, minutos, segundos, microsegundos)
    }

    # Si hay segundos faltantes, ajustar los datos para incluir ceros en los segundos faltantes
    if segundos_faltantes is not None:
        segundo_inicio = (horas * 3600) + (minutos * 60) + segundos
        muestras_por_segundo = fsample
        lista_ceros = np.zeros(muestras_por_segundo, dtype=np.int32)
        npts_completo = len(data) + int(len(segundos_faltantes) * muestras_por_segundo)
        data_completo = np.zeros(npts_completo, dtype=np.int32)
        data_completo[:len(data)] = data
        stats['npts'] = npts_completo

        for segundo_faltante in segundos_faltantes:
            tiempo_muestra_faltante = int(segundo_faltante - segundo_inicio)
            indice_muestra_faltante = tiempo_muestra_faltante * muestras_por_segundo
            data_completo = np.insert(data_completo, indice_muestra_faltante, lista_ceros)

        traza = Trace(data=data_completo, header=stats)
    else:
        traza = Trace(data=data, header=stats)
   
    return traza


# Función para inicializar y obtener el logger de un cliente
def obtener_logger(id_estacion, log_directory, log_filename):
    global loggers
    if id_estacion not in loggers:
        # Crear un logger para el cliente
        logger = logging.getLogger(id_estacion)
        logger.setLevel(logging.DEBUG)
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

    start_time_total = timer()

    # Parser de argumentos
    parser = argparse.ArgumentParser(description="Conversor de binario a Mini-SEED")
    parser.add_argument("modo_simple", nargs="?", choices=["1", "2", "3"],
                        help="Modo simple (1: Registro continuo, 2: Evento extraído, 3: Conversión manual)")
    parser.add_argument("archivo_nombre", nargs="?",
                        help="Nombre del archivo binario (requerido para modo 3)")
    parser.add_argument("--continuous", action="store_true",
                        help="Modo registro continuo (equivalente a modo 1)")
    parser.add_argument("--event", action="store_true",
                        help="Modo evento extraído (equivalente a modo 2)")
    parser.add_argument("--file", metavar="ARCHIVO",
                        help="Modo conversión manual, especifica el archivo binario (equivalente a modo 3)")
    args = parser.parse_args()

    # Obtiene la variable de entorno para definir la ruta del archivo de configuración
    project_local_root = os.getenv("PROJECT_LOCAL_ROOT")
    if not project_local_root:
        print("La variable de entorno PROJECT_LOCAL_ROOT no está definida.")
        return

    # Definir rutas de archivos y directorios
    config_mseed_file = os.path.join(project_local_root, "configuracion", "configuracion_mseed.json")
    config_dispositivo_file = os.path.join(project_local_root, "configuracion", "configuracion_dispositivo.json")
    archivoNombresArchivosRC = os.path.join(project_local_root, "tmp-files", "NombreArchivoRegistroContinuo.tmp")
    archivoNombresArchivosEE = os.path.join(project_local_root, "tmp-files", "NombreArchivoEventoExtraido.tmp")
    log_directory = os.path.join(project_local_root, "log-files")

    # Lee el archivo de configuración de mseed
    config_mseed = read_fileJSON(config_mseed_file)
    if config_mseed is None:
        print("No se pudo leer el archivo de configuración mseed. Terminando el programa.")
        return

    # Lee el archivo de configuración del dispositivo
    config_dispositivo = read_fileJSON(config_dispositivo_file)
    if config_dispositivo is None:
        print("No se pudo leer el archivo de configuración del dispositivo. Terminando el programa.")
        return

    # Obtener rutas desde configuracion_dispositivo.json
    path_registro_continuo = config_dispositivo.get("directorios", {}).get("registro_continuo", "")
    path_eventos_extraidos = config_dispositivo.get("directorios", {}).get("eventos_extraidos", "")
    path_archivos_mseed = config_dispositivo.get("directorios", {}).get("archivos_mseed", "")

    # Obtiene el codigo de la estacion
    codigo_estacion = config_mseed.get("CODIGO(1)", "Unknown")
    if codigo_estacion == "Unknown":
        print("No se encontró 'CODIGO(1)' en configuracion_mseed.json")
        return

    # Obtiene el ID del dispositivo
    dispositivo_id = config_dispositivo.get("dispositivo", {}).get("id", "Unknown")
    if dispositivo_id == "Unknown":
        print("No se encontró 'id' del dispositivo en configuracion_dispositivo.json")
        return

    # Verificar que el directorio de logs existe, si no, crearlo
    if not os.path.isdir(log_directory):
        try:
            os.makedirs(log_directory)
            print(f"Directorio de logs creado: {log_directory}")
        except Exception as e:
            print(f"Error al crear el directorio de logs {log_directory}: {e}")
            return

    # Inicializa el logger
    logger = obtener_logger(dispositivo_id, log_directory, "mseed.log")

    # Determinar tipo de archivo y ruta
    if args.modo_simple in ("1", "2", "3"):
        tipoArchivo = args.modo_simple
    elif args.continuous:
        tipoArchivo = "1"
    elif args.event:
        tipoArchivo = "2"
    elif args.file:
        tipoArchivo = "3"
    else:
        logger.error("No se especificó un modo válido.")
        print("Error: No se especificó un modo válido.")
        print("Uso:")
        print("  python3 binary_to_mseed.py 1               # Registro continuo")
        print("  python3 binary_to_mseed.py 2               # Evento extraído")
        print("  python3 binary_to_mseed.py 3 archivo.dat   # Conversión manual")
        print("  python3 binary_to_mseed.py --continuous    # Registro continuo")
        print("  python3 binary_to_mseed.py --event         # Evento extraído")
        print("  python3 binary_to_mseed.py --file archivo.dat  # Conversión manual")
        return

    if tipoArchivo == '1':
        # Archivos registro continuo
        if not path_registro_continuo:
            logger.error("No se encontró la ruta 'registro_continuo' en configuracion_dispositivo.json")
            print("Error: No se encontró la ruta 'registro_continuo' en configuracion_dispositivo.json")
            return
        if not path_archivos_mseed:
            logger.error("No se encontró la ruta 'archivos_mseed' en configuracion_dispositivo.json")
            print("Error: No se encontró la ruta 'archivos_mseed' en configuracion_dispositivo.json")
            return

        # Verificar que los directorios existen
        if not os.path.isdir(path_registro_continuo):
            logger.error(f"El directorio de registro continuo no existe: {path_registro_continuo}")
            print(f"Error: El directorio de registro continuo no existe: {path_registro_continuo}")
            return
        if not os.path.isdir(path_archivos_mseed):
            logger.error(f"El directorio de archivos mseed no existe: {path_archivos_mseed}")
            print(f"Error: El directorio de archivos mseed no existe: {path_archivos_mseed}")
            return

        try:
            with open(archivoNombresArchivosRC) as ficheroNombresArchivos:
                lineasFicheroNombresArchivos = ficheroNombresArchivos.readlines()
                if len(lineasFicheroNombresArchivos) < 2:
                    logger.error("El archivo de nombres de registro continuo no tiene suficientes líneas.")
                    print("Error: El archivo de nombres de registro continuo no tiene suficientes líneas.")
                    return
                binary_filename = lineasFicheroNombresArchivos[1].rstrip('\n')
        except FileNotFoundError:
            logger.error(f"No se encontró el archivo: {archivoNombresArchivosRC}")
            print(f"Error: No se encontró el archivo: {archivoNombresArchivosRC}")
            return

        binary_file = os.path.join(path_registro_continuo, binary_filename)
        path_archivo_salida = path_archivos_mseed
        logger.info(f'Convirtiendo el archivo de registro continuo: {binary_filename}')
        print(f'Convirtiendo el archivo: {binary_filename}')

    elif tipoArchivo == '2':
        # Archivos eventos extraidos
        if not path_eventos_extraidos:
            logger.error("No se encontró la ruta 'eventos_extraidos' en configuracion_dispositivo.json")
            print("Error: No se encontró la ruta 'eventos_extraidos' en configuracion_dispositivo.json")
            return

        # Verificar que el directorio existe
        if not os.path.isdir(path_eventos_extraidos):
            logger.error(f"El directorio de eventos extraídos no existe: {path_eventos_extraidos}")
            print(f"Error: El directorio de eventos extraídos no existe: {path_eventos_extraidos}")
            return

        try:
            with open(archivoNombresArchivosEE) as ficheroNombresArchivos:
                lineasFicheroNombresArchivos = ficheroNombresArchivos.readlines()
                if len(lineasFicheroNombresArchivos) < 1:
                    logger.error("El archivo de nombres de eventos extraidos no tiene suficientes líneas.")
                    print("Error: El archivo de nombres de eventos extraidos no tiene suficientes líneas.")
                    return
                binary_filename = lineasFicheroNombresArchivos[0].rstrip('\n')
        except FileNotFoundError:
            logger.error(f"No se encontró el archivo: {archivoNombresArchivosEE}")
            print(f"Error: No se encontró el archivo: {archivoNombresArchivosEE}")
            return

        binary_file = os.path.join(path_eventos_extraidos, binary_filename)
        path_archivo_salida = path_eventos_extraidos
        logger.info(f'Convirtiendo el archivo de evento extraído: {binary_filename}')
        print(f'Convirtiendo el archivo: {binary_filename}')

    elif tipoArchivo == '3':
        # Conversión manual de archivo específico
        # Determinar la ruta del archivo: puede venir como argumento posicional o con --file
        archivo_input = args.archivo_nombre or args.file

        if not archivo_input:
            logger.error("Se debe especificar el archivo binario como segundo argumento o con --file")
            print("Error: Se debe especificar el archivo binario.")
            print("Uso: python3 binary_to_mseed.py 3 <archivo.dat>")
            print("  o: python3 binary_to_mseed.py --file <archivo.dat>")
            return

        # Si la ruta es absoluta, usarla directamente; si no, buscar en path_registro_continuo
        if os.path.isabs(archivo_input):
            binary_file = archivo_input
            binary_filename = os.path.basename(archivo_input)
        else:
            if not path_registro_continuo:
                logger.error("No se encontró la ruta 'registro_continuo' en configuracion_dispositivo.json")
                print("Error: No se encontró la ruta 'registro_continuo' en configuracion_dispositivo.json")
                return
            binary_filename = archivo_input
            binary_file = os.path.join(path_registro_continuo, binary_filename)

        if not path_archivos_mseed:
            logger.error("No se encontró la ruta 'archivos_mseed' en configuracion_dispositivo.json")
            print("Error: No se encontró la ruta 'archivos_mseed' en configuracion_dispositivo.json")
            return

        # Verificar que el directorio de salida existe
        if not os.path.isdir(path_archivos_mseed):
            logger.error(f"El directorio de archivos mseed no existe: {path_archivos_mseed}")
            print(f"Error: El directorio de archivos mseed no existe: {path_archivos_mseed}")
            return

        path_archivo_salida = path_archivos_mseed
        logger.info(f'Convirtiendo el archivo manual: {binary_filename} desde {binary_file}')
        print(f'Convirtiendo el archivo manual: {binary_filename}')

    # Verificar que el archivo binario existe
    if not os.path.isfile(binary_file):
        logger.error(f"El archivo binario no existe: {binary_file}")
        print(f"Error: El archivo binario no existe: {binary_file}")
        return

    # Extraer tiempo del archivo binario
    tiempo_binario = extraer_tiempo_binario(binary_file)
    if tiempo_binario is None:
        logger.error(f'Tamaño de trama insuficiente. Archivo binario podría estar dañado o incompleto: {binary_filename}')
        print("Error al extraer el tiempo del archivo binario.")
        return  

    # Inicializa la conversion del archivo
    nombre_archivo_mseed = nombrar_archivo_mseed(codigo_estacion, tiempo_binario)
    datos_archivo_binario, segundos_faltantes = leer_archivo_binario(binary_file, logger)
    conversion_mseed_digital(nombre_archivo_mseed, path_archivo_salida, tiempo_binario, datos_archivo_binario, segundos_faltantes, config_mseed, logger)

    #print('Se ha creado el archivo: %s' %nombre_archivo_mseed)

    end_time_total = timer()
    print(f"Tiempo total de ejecución: {end_time_total - start_time_total:.4f} segundos")

    # Sube los archivos convertidos a Drive
    '''
    if tipoArchivo=='1':
        subprocess.run(["python3", script_subir_archivo_drive, nombre_archivo_mseed, "3", "1"])
        time.sleep(5)
        subprocess.run(["python3", script_subir_archivo_drive, binary_filename, "1", "0"])
    elif tipoArchivo=='2':
        subprocess.run(["python3", script_subir_archivo_drive, nombre_archivo_mseed, "2", "1"])
    '''
#######################################################################################################
if __name__ == '__main__':
    main()
#######################################################################################################


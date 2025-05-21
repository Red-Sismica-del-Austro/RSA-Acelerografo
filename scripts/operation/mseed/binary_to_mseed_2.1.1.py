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
    parser.add_argument("modo_simple", nargs="?", choices=["1", "2"],
                        help="Modo simple (1: Registro continuo, 2: Evento extraído)")
    parser.add_argument("--modo", choices=["rc", "ee", "archivo"],
                        help="Modo de conversión (rc: registro continuo, ee: evento extraído, archivo: conversión manual)")
    parser.add_argument("--nombre", help="Nombre del archivo binario (solo en modo archivo)")
    args = parser.parse_args()

    # Variable de entorno
    project_local_root = os.getenv("PROJECT_LOCAL_ROOT")
    if not project_local_root:
        print("La variable de entorno PROJECT_LOCAL_ROOT no está definida.")
        return
    config_mseed_file = os.path.join(project_local_root, "configuracion", "configuracion_mseed.json")
    config_dispositivo_file = os.path.join(project_local_root, "configuracion", "configuracion_dispositivo.json")
    archivoNombresArchivosRC = os.path.join(project_local_root, "tmp-files", "NombreArchivoRegistroContinuo.tmp")
    archivoNombresArchivosEE = os.path.join(project_local_root, "tmp-files", "NombreArchivoEventoExtraido.tmp")
    script_subir_archivo_drive = os.path.join(project_local_root, "scripts", "drive", "subir_archivo.py")
    log_directory = os.path.join(project_local_root, "log-files")

    # Carga de configuraciones
    config_mseed = read_fileJSON(config_mseed_file)
    config_dispositivo = read_fileJSON(config_dispositivo_file)
    if config_mseed is None or config_dispositivo is None:
        print("Error leyendo archivos de configuración. Terminando el programa.")
        return
    
    # Determinar tipo de archivo y ruta
    if args.modo_simple in ("1", "2"):
        tipoArchivo = args.modo_simple
    elif args.modo == "rc":
        tipoArchivo = "1"
    elif args.modo == "ee":
        tipoArchivo = "2"
    elif args.modo == "archivo":
        tipoArchivo = "archivo"
    else:
        print("Error: No se especificó un modo válido.")
        return

    if tipoArchivo=='1':
        #Archivos registro continuo
        path_registro_continuo = config_dispositivo.get("directorios", {}).get("registro_continuo", "Unknown")
        with open(archivoNombresArchivosRC) as ficheroNombresArchivos:
            lineasFicheroNombresArchivos = ficheroNombresArchivos.readlines()
            if len(lineasFicheroNombresArchivos) < 2:
                print("Error: El archivo de nombres de registro continuo no tiene suficientes líneas.")
                return
            binary_filename = lineasFicheroNombresArchivos[1].rstrip('\n')
            binary_file = path_registro_continuo + binary_filename
            path_archivo_salida = config_dispositivo.get("directorios", {}).get("archivos_mseed", "Unknown")
            print(f'Convirtiendo el archivo: {binary_filename}')
    elif tipoArchivo=='2':
        #Archivos eventos extraidos
        path_eventos_extraidos = config_dispositivo.get("directorios", {}).get("eventos_extraidos", "Unknown")
        with open(archivoNombresArchivosEE) as ficheroNombresArchivos:
            lineasFicheroNombresArchivos = ficheroNombresArchivos.readlines()
            if len(lineasFicheroNombresArchivos) < 1:
                print("Error: El archivo de nombres de eventos extraidos no tiene suficientes líneas.")
                return
            binary_filename = lineasFicheroNombresArchivos[0].rstrip('\n')
            binary_file = path_eventos_extraidos + binary_filename
            path_archivo_salida = path_eventos_extraidos
            print(f'Convirtiendo el archivo: {binary_filename}')
    elif tipoArchivo == "archivo":
        if not args.nombre:
            print("Error: Se debe especificar --nombre con el nombre del archivo binario.")
            return
        binary_filename = args.nombre
        binary_file = os.path.join(project_local_root, "resultados", "registro-continuo", binary_filename)
        path_archivo_salida = config_dispositivo.get("directorios", {}).get("archivos_mseed", "Unknown")
        print(f'Convirtiendo el archivo manual: {binary_filename}')

            
    # Obtiene el codigo de la estacion
    codigo_estacion = config_mseed["CODIGO(1)"]
    # Obtiene el ID del dispositivo
    dispositivo_id = config_dispositivo.get("dispositivo", {}).get("id", "Unknown")
    # Inicializa el logger
    logger = obtener_logger(dispositivo_id, log_directory, "mseed.log")
    logger.info(f'Convirtiendo el archivo binario: {binary_filename}')

    # Extraer tiempo del archivo binario
    tiempo_binario = extraer_tiempo_binario(binary_file)
    if tiempo_binario is None:
        print("Error al extraer el tiempo del archivo binario.")
        logger.error(f'Tamaño de trama insuficiente. Archivo binario podría estar dañado o incompleto')
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


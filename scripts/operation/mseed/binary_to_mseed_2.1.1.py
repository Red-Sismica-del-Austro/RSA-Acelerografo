######################################### ~Librerias~ #################################################
import numpy as np
from obspy import UTCDateTime, read, Trace, Stream
import os
import subprocess
import time
import sys
import json
from time import time as timer
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
    

def leer_archivo_binario(archivo_binario):
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

            n_segundos = horas * 3600 + minutos * 60 + segundos
            tiempos.extend(n_segundos)
            
            # Procesar los datos de forma vectorizada
            datos_crudos = chunk[:, :2500].reshape((-1, 250, 10))

            for j in range(3):
                dato_1 = datos_crudos[:, :, j * 3 + 1].flatten()
                dato_2 = datos_crudos[:, :, j * 3 + 2].flatten()
                dato_3 = datos_crudos[:, :, j * 3 + 3].flatten()

                xValue = ((dato_1.astype(np.uint32) << 12) & 0xFF000) + ((dato_2.astype(np.uint32) << 4) & 0xFF0) + ((dato_3.astype(np.uint32) >> 4) & 0xF)

                # Convertir xValue a int32 para manejar valores negativos
                xValue = xValue.astype(np.int32)

                mask = xValue >= 0x80000
                #xValue[mask] = xValue[mask] & 0x7FFFF
                xValue[mask] = -1 * ((~xValue[mask] + 1) & 0x7FFFF)

                datos[j].extend(xValue)

    datos_np = np.array(datos)

    # Detectar segundos faltantes en el array tiempos
    tiempos_np = np.array(tiempos)
    segundos_faltantes = []
    dif_segundos = np.diff(tiempos_np)
    missing_indices = np.where(dif_segundos > 1)[0]
    for idx in missing_indices:
        segundos_faltantes.extend(range(tiempos_np[idx] + 1, tiempos_np[idx + 1]))

    
    # Imprimir primeros y últimos elementos de tiempos_np y segundos_faltantes
    print(f"Primer elemento de tiempos_np: {tiempos_np[0]}")
    print(f"Último elemento de tiempos_np: {tiempos_np[-1]}")

    if segundos_faltantes:
        print(f"Primer elemento de segundos_faltantes: {segundos_faltantes[0]}")
        print(f"Último elemento de segundos_faltantes: {segundos_faltantes[-1]}")
        print(f"Se encontraron {len(segundos_faltantes)} segundos faltantes")

    end_time = timer()
    print(f"Tiempo de ejecución de leer_archivo_binario: {end_time - start_time:.4f} segundos")
    return datos_np, segundos_faltantes if segundos_faltantes else None


# Extrae y convierte valores de tiempo del archivo binario y los devuelve en un diccionario.
def extraer_tiempo_binario(archivo):
    # Abrir el archivo en modo de lectura binaria
    with open(archivo, "rb") as f:
        # Leer 2506 bytes del archivo y almacenarlos en un arreglo de numpy
        tramaDatos = np.fromfile(f, np.int8, 2506)
    
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
def conversion_mseed_digital(fileName, path, tiempo_binario, datos_archivo_binario, segundos_faltantes, parametros_mseed):
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

#######################################################################################################

############################################ ~Main~ ###################################################
def main():

    start_time_total = timer()

    # Recibe como parametro el tipo de archivo binario a convertir (1:Resgistro continuo 2:Eventos extraidos)
    if len(sys.argv) != 2:
        print("Uso: conversor_mseed.py <tipo_archivo: 1.Registro continuo 2.Evento extraido>")
        return

    tipoArchivo = sys.argv[1] 

    # Obtiene la variable de entorno para definir la ruta del archivo de configuracion:
    project_local_root = os.getenv("PROJECT_LOCAL_ROOT")
    if project_local_root:
        #print(f"PROJECT_LOCAL_ROOT: {project_local_root}")
        # Concatenar PROJECT_LOCAL_CONFIG con las diferentes rutas de los archivos y scripts:
        config_mseed_path = os.path.join(project_local_root, "configuracion", "configuracion_mseed.json")
        config_dispositivo_path = os.path.join(project_local_root, "configuracion", "configuracion_dispositivo.json")
        archivoNombresArchivosRC = os.path.join(project_local_root,"tmp-files", "NombreArchivoRegistroContinuo.tmp")
        archivoNombresArchivosEE = os.path.join(project_local_root,"tmp-files","NombreArchivoEventoExtraido.tmp")
        script_subir_archivo_drive = os.path.join(project_local_root,"scripts", "drive","subir_archivo.py")
    else:
        print("La variable de entorno no están definida.")
        return

    # Lee el archivo de configuración mseed
    config_mseed = read_fileJSON(config_mseed_path)
    if config_mseed is None:
        print("No se pudo leer el archivo de configuración. Terminando el programa.")
        return
    
    # Lee el archivo de configuración del dispositivo
    config_dispositivo = read_fileJSON(config_dispositivo_path)
    if config_dispositivo is None:
        print("No se pudo leer el archivo de configuración del dispositivo. Terminando el programa.")
        return
    
    if tipoArchivo=='1':
        #Archivos registro continuo
        path_registro_continuo = config_dispositivo.get("directorios", {}).get("registro_continuo", "Unknown")
        with open(archivoNombresArchivosRC) as ficheroNombresArchivos:
            lineasFicheroNombresArchivos = ficheroNombresArchivos.readlines()
            nombreArchvioRegistroContinuo = lineasFicheroNombresArchivos[1].rstrip('\n')
            archivo_binario = path_registro_continuo + nombreArchvioRegistroContinuo
            path_archivo_salida = config_dispositivo.get("directorios", {}).get("archivos_mseed", "Unknown")
            print(f'Convirtiendo el archivo: {archivo_binario}')
    elif tipoArchivo=='2':
        #Archivos eventos extraidos
        path_eventos_extraidos = config_dispositivo.get("directorios", {}).get("eventos_extraidos", "Unknown")
        with open(archivoNombresArchivosEE) as ficheroNombresArchivos:
            lineasFicheroNombresArchivos = ficheroNombresArchivos.readlines()
            archivo_binario = path_eventos_extraidos + lineasFicheroNombresArchivos[0].rstrip('\n')
            path_archivo_salida = path_eventos_extraidos
            print(f'Convirtiendo el archivo: {archivo_binario}')

    
    codigo_estacion = config_mseed["CODIGO(1)"]
    tiempo_binario = extraer_tiempo_binario(archivo_binario)
    nombre_archivo_mseed = nombrar_archivo_mseed(codigo_estacion, tiempo_binario)
    datos_archivo_binario, segundos_faltantes = leer_archivo_binario(archivo_binario)

    conversion_mseed_digital(nombre_archivo_mseed, path_archivo_salida, tiempo_binario, datos_archivo_binario, segundos_faltantes, config_mseed)

    #print('Se ha creado el archivo: %s' %nombre_archivo_mseed)

    end_time_total = timer()
    print(f"Tiempo total de ejecución: {end_time_total - start_time_total:.4f} segundos")

    # Sube los archivos convertidos a Drive
    if tipoArchivo=='1':
        subprocess.run(["python3", script_subir_archivo_drive, nombre_archivo_mseed, "3", "1"])
        time.sleep(5)
        subprocess.run(["python3", script_subir_archivo_drive, nombreArchvioRegistroContinuo, "1", "0"])
    elif tipoArchivo=='2':
        subprocess.run(["python3", script_subir_archivo_drive, nombre_archivo_mseed, "2", "1"])

#######################################################################################################
if __name__ == '__main__':
    main()
#######################################################################################################


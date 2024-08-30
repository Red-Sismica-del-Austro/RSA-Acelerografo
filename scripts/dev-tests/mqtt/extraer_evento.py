import paho.mqtt.client as mqtt
import json
import os
import datetime
import subprocess

path = '/home/rsa/configuracion'

############################################ ~FUNCIONES~ ############################################

# Definir la funcion para buscar el archivo del registro continuo que contiene el dato solicitado
def BuscarArchivoRegistro(fecha_str):

    # Definir los paths
    pathRegistroContinuo = '/home/rsa/resultados/registro-continuo/'
    pathArchivoConfiguracion = '/home/rsa/configuracion/'

    # Lee el nombre de la estacion del archivo de configuracion:
    with open(pathArchivoConfiguracion + 'DatosConfiguracion.txt', 'r') as f:
        estacion = f.readline().strip()

    # Convierte la fecha de string a objeto datetime:
    anio = int(fecha_str[:2]) + 2000
    mes = int(fecha_str[2:4])
    dia = int(fecha_str[4:6])
    hora = int(fecha_str[7:9])
    minuto = int(fecha_str[9:11])
    segundo = int(fecha_str[11:13])
    fecha = datetime.datetime(anio, mes, dia, hora, minuto, segundo)

    # Extrae la duracion del evento
    duracion = int(fecha_str[14:])
    #print(duracion)
 
    # Formatea la fecha en el formato necesario para el nombre del archivo
    fecha_str = fecha.strftime("%y%m%d")

    # Obtiene una lista de los archivos disponibles
    archivos_disponibles = os.listdir(pathRegistroContinuo)
    archivos_filtrados = [archivo for archivo in archivos_disponibles if archivo.startswith(estacion + fecha_str)]
    archivos_filtrados.sort()

    print (archivos_filtrados)

    hora_busqueda = fecha.time()
    print(hora_busqueda)

    # Busca el archivo que contiene la medición deseada
    archivo_busqueda = None
    for archivo in archivos_filtrados:
        hora_str = archivo.split('-')[1][:6]
        hora_archivo = datetime.datetime.strptime(hora_str, '%H%M%S').time()
        fecha_archivo = datetime.datetime.strptime(fecha_str, '%y%m%d').date()
        fecha_hora_archivo = datetime.datetime.combine(fecha_archivo, hora_archivo)
        tamano_archivo = os.path.getsize(pathRegistroContinuo + archivo) # tamaño en bytes del archivo
        tamano_minuto = 150360 # tamaño en bytes de un archivo de un minuto
        minutos_por_archivo = tamano_archivo // tamano_minuto
        print(archivo,minutos_por_archivo)
        rango_tiempo_archivo = datetime.timedelta(minutes=minutos_por_archivo)
        if fecha_hora_archivo <= datetime.datetime.combine(fecha, hora_busqueda) < fecha_hora_archivo + rango_tiempo_archivo:
            archivo_busqueda = archivo
            break

    if archivo_busqueda is None:
        print("No se encontró ningún archivo que contenga la medición deseada.")
    else:
        print(archivo_busqueda)

        # Prepara los parametros para pasarle al programa extraerevento
        #nombre_archivo = pathRegistroContinuo + archivo_busqueda
        nombre_archivo = archivo_busqueda
        hora_segundos = str((hora*3600) + (minuto*60) + segundo)
        duracion = str(duracion)

        # Ejecutar el programa de C con los argumentos definidos
        subprocess.run(["/home/rsa/ejecutables/extraerevento", nombre_archivo, hora_segundos, duracion])

        # Obtener una lista de todos los archivos en la carpeta ordenados por fecha de creación
        ruta_carpeta = "/home/rsa/resultados/eventos-extraidos/"
        archivosExtraidos = sorted(
            [os.path.join(ruta_carpeta, archivo) for archivo in os.listdir(ruta_carpeta)],
            key=os.path.getctime,
            reverse=True
        )
        ultimo_archivo = archivosExtraidos[0]
        nombre_archivo_extraido = os.path.basename(ultimo_archivo)
        print(nombre_archivo_extraido)

        # Subir archivo extraido a Drive:
        comandoPython = ["sudo", "python3", "/home/rsa/ejecutables/SubirArchivoDrive.py", "2", nombre_archivo_extraido]
        # resultado = subprocess.run(comandoPython, capture_output=True, text=True)
        # print(resultado.stdout)
        subprocess.run(comandoPython)
  
# Definir la función para extraer la fecha, hora y duración del payload JSON
def procesar_mensaje(mensaje):
    payload = json.loads(mensaje.payload)
    fecha = payload["fecha"]
    hora = payload["hora"]
    duracion = payload["duracion"]
    print(f"Fecha: {fecha}, Hora: {hora}, Duración: {duracion}")

# Definir los callbacks para los eventos de conexión
def on_connect(client, userdata, flags, rc):
    print("Conectado al broker MQTT con código de resultado: " + str(rc))
    # Suscribirse al topic al conectarse
    client.subscribe(topic)

def on_message(client, userdata, msg):
    print("Mensaje recibido en el topic " + msg.topic + " con el contenido: " + str(msg.payload))
    #procesar_mensaje(msg)
    print(str(msg.payload))
    payload_str = msg.payload.decode('utf-8')
    print(payload_str)
    BuscarArchivoRegistro(payload_str)

    # Publicar en el topic que ya se cumplio la tarea
    publicar_mensaje(client, "status", "completado")

def publicar_mensaje(client, topic, mensaje):
    client.publish(topic, mensaje)

def read_json(path_base):
    with open(path_base,"r") as condig_file:
        config = json.load(condig_file)
    return config
#####################################################################################################

######################################### ~PARAMETROS MQTT~ #########################################
mqtt_config = read_json(path+'/mqtt-configuracion.json')
server_address = mqtt_config["server_address"]
username = mqtt_config["username"]
password = mqtt_config["password"]
topic = mqtt_config["topicSuscription"]
#####################################################################################################

############################################### ~MAIN~ ##############################################
# Crear una instancia del cliente MQTTc
client = mqtt.Client()

# Asignar los callbacks de conexión y de recepción de mensajes
client.on_connect = on_connect
client.on_message = on_message

# Conectarse al broker MQTT
client.username_pw_set(username, password)
client.connect(server_address, 1883, 60)

# Iniciar el loop para mantener la conexión y recibir mensajes
client.loop_forever()
#####################################################################################################
######################################### ~Funciones~ #################################################
import os
import json
import paho.mqtt.client as mqtt
import time
import logging
#######################################################################################################

##################################### ~Variables globales~ ############################################
variable = 0
#######################################################################################################

######################################### ~Funciones~ #################################################
# Funcion para leer el archivo de configuracion JSON
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

# Función que se llama cuando el cliente se conecta al broker
def on_connect(client, userdata, flags, rc):
    if rc == 0:
        print("Conectado al broker MQTT con éxito.")
        logger.info("Conectado al broker MQTT con éxito")
        # Publicar mensaje "online" cuando se reconecta
        if userdata['is_reconnecting']:
            publicar_mensaje(client, userdata['config_mqtt']["topicStatus"], userdata['dispositivo_id'], "online")
            userdata['is_reconnecting'] = False
    else:
        print(f"Error al conectar al broker MQTT. Codigo: {rc}")
        logger.error(f'Error al conectar al broker MQTT. Codigo: {rc}')

# Función que se llama cuando el cliente se desconecta del broker
def on_disconnect(client, userdata, rc):
    print("Desconectado del broker MQTT")
    logger.error("Desconectado del broker MQTT")
    userdata['is_reconnecting'] = True

# Función para publicar mensajes por MQTT en formato JSON
def publicar_mensaje(client, topic, id, mensaje):
    mensaje_json = json.dumps({"id": id, "status": mensaje})
    client.publish(topic, mensaje_json)

# Función para iniciar el cliente MQTT
def iniciar_cliente_mqtt(config_mqtt, dispositivo_id):
    client = mqtt.Client(userdata={'config_mqtt': config_mqtt, 'dispositivo_id': dispositivo_id, 'is_reconnecting': False})
    client.on_connect = on_connect
    client.on_disconnect = on_disconnect

    # Crear el mensaje LWT en formato JSON
    lwt_message = json.dumps({"id": dispositivo_id, "status": "offline"})
    lwt_topic = "status"  # Tópico LWT para notificar desconexiones

    # Establecer Last Will and Testament (LWT)
    client.will_set(lwt_topic, payload=lwt_message, qos=1, retain=False)
    
    try:
        client.username_pw_set(config_mqtt["username"], config_mqtt["password"])
        client.connect(config_mqtt["serverAddress"], 1883, 60)

        # Publicar mensaje de inicio
        publicar_mensaje(client, config_mqtt["topicStatus"], dispositivo_id, "on")

        #client.loop_forever()
        client.loop_start()
        while True:
            time.sleep(1)

    except Exception as e:
        print(f"Error al conectar o publicar en el broker MQTT. Codigo: {e}")
        logger.error(f"Error al conectar o publicar en el broker MQTT. Codigo: {e}")

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

    '''
    Ojo: Esta parte no esta funcionando debido a que el Supervisor no puede trabajar con variables de entorno
    # Obtiene la variable de entorno para definir la ruta del archivo de configuracion:
    project_local_root = os.getenv("PROJECT_LOCAL_ROOT")
    if project_local_root:
        # Concatenar PROJECT_LOCAL_CONFIG con las diferentes rutas de los archivos y scripts:
        config_dispositivo_path = os.path.join(project_local_root, "configuracion", "configuracion_dispositivo.json")
        config_mqtt_path = os.path.join(project_local_root, "configuracion", "configuracion_mqtt.json")
    else:
        print("La variable de entorno no están definida.")
        return
    '''

    config_mqtt_path = "/home/rsa/projects/acelerografo/configuracion/configuracion_mqtt.json"
    config_dispositivo_path = "/home/rsa/projects/acelerografo/configuracion/configuracion_dispositivo.json"
    log_directory = "/home/rsa/projects/acelerografo/log-files"
    
    # Lee el archivo de configuración MQTT
    config_mqtt = read_fileJSON(config_mqtt_path)
    if config_mqtt is None:
        print("No se pudo leer el archivo de configuración. Terminando el programa.")
        return
    
    # Lee el archivo de configuración del dispositivo
    config_dispositivo = read_fileJSON(config_dispositivo_path)
    if config_dispositivo is None:
        print("No se pudo leer el archivo de configuración del dispositivo. Terminando el programa.")
        return

    # Obtiene el ID del dispositivo
    dispositivo_id = config_dispositivo.get("dispositivo", {}).get("id", "Unknown")

    # Inicializa el logger
    logger = obtener_logger(id_estacion, log_directory, "mqtt.log")

    # Inicia el cliente mqtt
    iniciar_cliente_mqtt(config_mqtt, dispositivo_id)


#######################################################################################################
if __name__ == '__main__':
    main()
#######################################################################################################

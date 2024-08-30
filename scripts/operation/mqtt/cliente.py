######################################### ~Funciones~ #################################################
import os
import json
import paho.mqtt.client as mqtt
import time
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
        # Publicar mensaje "online" cuando se reconecta
        if userdata['is_reconnecting']:
            publicar_mensaje(client, userdata['config_mqtt']["topicStatus"], userdata['dispositivo_id'], "online")
            userdata['is_reconnecting'] = False
    else:
        print(f"Error al conectar al broker MQTT, código de resultado: {rc}")

# Función que se llama cuando el cliente se desconecta del broker
def on_disconnect(client, userdata, rc):
    print("Desconectado del broker MQTT.")
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
        print(f"Error al conectar o publicar en el broker MQTT: {e}")


#######################################################################################################

############################################ ~Main~ ###################################################
def main():

    '''
    # Obtiene la variable de entorno para definir la ruta del archivo de configuracion:
    project_local_root = os.getenv("PROJECT_LOCAL_ROOT")
    if project_local_root:
        # Concatenar PROJECT_LOCAL_CONFIG con las diferentes rutas de los archivos y scripts:
        config_mqtt_path = os.path.join(project_local_root, "configuracion", "configuracion_mqtt.json")
        config_dispositivo_path = os.path.join(project_local_root, "configuracion", "configuracion_dispositivo.json")
    else:
        print("La variable de entorno no están definida.")
        return
    '''
    
    config_mqtt_path = "/home/rsa/projects/acelerografo-rsa/configuracion/configuracion_mqtt.json"
    config_dispositivo_path = "/home/rsa/projects/acelerografo-rsa/configuracion/configuracion_dispositivo.json"
    
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

    iniciar_cliente_mqtt(config_mqtt, dispositivo_id)


#######################################################################################################
if __name__ == '__main__':
    main()
#######################################################################################################

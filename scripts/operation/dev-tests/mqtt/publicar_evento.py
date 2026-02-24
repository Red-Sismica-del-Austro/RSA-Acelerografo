######################################## ~Librerias~ ################################################
import paho.mqtt.client as mqtt
import json
import os
import datetime
import subprocess
import sys
import math
from datetime import timedelta
#####################################################################################################


############################################ ~Funciones~ ############################################
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
        client.subscribe(topic)
    else:
        print(f"Error al conectar al broker MQTT, código de resultado: {rc}")

def publicar_mensaje(client, topic, mensaje):
    client.publish(topic, mensaje)

def conversion_fecha(fecha,hora):
    hora_transf = str(timedelta(seconds=hora))
    fecha_transf = '20'+fecha[0:2]+'-'+fecha[2:4]+'-'+fecha[4:]
    return fecha_transf+'T'+hora_transf+'Z'

#####################################################################################################


############################################ ~Main~ ###################################################
def main():

    global topic

    # Obtencion de los parametros de entrada:
    fecha = sys.argv[1]
    hora = sys.argv[2]
    hora = int(hora)
    duracion = sys.argv[3]

    config_mqtt_path = '/home/rsa/configuracion/configuracion_mqtt.json'
    config_dispositivo_path = '/home/rsa/configuracion/configuracion_dispositivo.json'

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

    # Verifica si se debe publicar eventos
    if config_dispositivo["dispositivo"].get("publicarEventos", "no") != "si":
        print("La publicación de eventos está deshabilitada")
        return

    server_address = config_mqtt.get("serverAddress", "Unknown")
    username = config_mqtt.get("username", "Unknown")
    password = config_mqtt.get("password", "Unknown")
    topic = config_mqtt.get("topicPublish", "Unknown")

    # Crear una instancia del cliente MQTTc
    client = mqtt.Client()

    # Asignar los callbacks de conexión y de recepción de mensajes
    client.on_connect = on_connect
    
    # Conectarse al broker MQTT
    client.username_pw_set(username, password)
    client.connect(server_address, 1883, 60)

    dic = {
        config_dispositivo["dispositivo"]["ubicacion"]: {
            config_dispositivo["dispositivo"]["id"]: {
                "inicio": conversion_fecha(fecha, hora),
                "duracion": duracion  
            }
        }
    }
    publicar_mensaje(client, topic, json.dumps(dic))


#######################################################################################################
if __name__ == '__main__':
    main()
#######################################################################################################
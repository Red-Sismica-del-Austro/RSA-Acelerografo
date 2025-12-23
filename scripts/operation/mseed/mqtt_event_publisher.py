import json
import logging
import paho.mqtt.client as mqtt
from .seismic_pick import SeismicPick

class MQTTEventPublisher:
    """
    Publicador de eventos sísmicos vía MQTT.
    Reutiliza la lógica de conexión y manejo de errores de cliente.py
    """

    def __init__(self, config_mqtt, station_id, topic_prefix="eventos", logger=None):
        self.config = config_mqtt
        self.station_id = station_id
        self.topic_prefix = topic_prefix
        self.logger = logger or logging.getLogger(__name__)
        
        # Topic específico para los picks de esta estación
        self.event_topic = f"{self.topic_prefix}/{self.station_id}/picks"
        self.status_topic = self.config.get("topicStatus", "status")

        # Inicializar cliente MQTT
        self.client = mqtt.Client(userdata={
            'logger': self.logger,
            'is_reconnecting': False
        })
        
        # Callbacks (similares a cliente.py)
        self.client.on_connect = self._on_connect
        self.client.on_disconnect = self._on_disconnect
        
        # Configurar LWT
        lwt_message = json.dumps({"id": self.station_id, "status": "offline"})
        self.client.will_set(self.status_topic, payload=lwt_message, qos=1, retain=False)
        
        # Autenticación y conexión
        try:
            self.client.username_pw_set(self.config["username"], self.config["password"])
            self.client.connect(self.config["serverAddress"], 1883, 60)
            self.client.loop_start()
            self.logger.info(f"Cliente MQTT iniciado. Publicando en: {self.event_topic}")
        except Exception as e:
            self.logger.error(f"Error al conectar al broker MQTT: {e}")

    def _on_connect(self, client, userdata, flags, rc):
        if rc == 0:
            self.logger.info("Conectado al broker MQTT con éxito")
            # Publicar estado online
            self.publish_status("online")
        else:
            self.logger.error(f"Error al conectar al broker MQTT. Código: {rc}")

    def _on_disconnect(self, client, userdata, rc):
        if rc != 0:
            self.logger.warning(f"Desconexión inesperada del broker MQTT. Código: {rc}")
        else:
            self.logger.info("Desconexión limpia del broker MQTT")

    def publish_status(self, status):
        """Publica el estado del dispositivo"""
        try:
            payload = json.dumps({"id": self.station_id, "status": status})
            self.client.publish(self.status_topic, payload, qos=1)
        except Exception as e:
            self.logger.error(f"Error publicando estado: {e}")

    def publish_pick(self, pick: SeismicPick):
        """Publica un pick detectado en formato JSON"""
        try:
            payload = json.dumps(pick.to_dict())
            result = self.client.publish(self.event_topic, payload, qos=1)
            if result.rc == mqtt.MQTT_ERR_SUCCESS:
                self.logger.debug(f"Pick publicado vía MQTT: {pick.phase} @ {pick.time}")
                return True
            else:
                self.logger.error(f"Falla al publicar pick MQTT. Código: {result.rc}")
        except Exception as e:
            self.logger.error(f"Error en publish_pick: {e}")
        return False

    def stop(self):
        """Cierre limpio de la conexión"""
        self.logger.info("Deteniendo publicador MQTT...")
        self.publish_status("offline")
        self.client.loop_stop()
        self.client.disconnect()

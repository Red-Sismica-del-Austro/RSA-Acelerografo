# mqtt_coordinator.py - Agente Reactivo MQTT

import os
import json
import time
import threading
from datetime import datetime, timezone
from dotenv import load_dotenv
import paho.mqtt.client as mqtt

# Importar StructuredLogger del proyecto
import sys
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from structured_logger import StructuredLogger

# ═══════════════════════════════════════════════════════════════════════════
# CONFIGURACIÓN Y CONSTANTES
# ═══════════════════════════════════════════════════════════════════════════

HEALTH_INTERVAL = 300    # segundos
START_TIME = time.time()

# ═══════════════════════════════════════════════════════════════════════════
# UTILIDADES
# ═══════════════════════════════════════════════════════════════════════════

def cargar_configuracion(config_path: str, env_path: str) -> dict:
    """Carga configuración JSON y credenciales desde .env"""
    load_dotenv(env_path)
    
    with open(config_path, 'r') as f:
        config = json.load(f)
    
    config["broker"] = {
        "address": os.getenv("MQTT_BROKER"),
        "port": int(os.getenv("MQTT_PORT", 1883)),
        "username": os.getenv("MQTT_USERNAME"),
        "password": os.getenv("MQTT_PASSWORD")
    }
    return config

def resolver_topico(config: dict, topic_key: str, **kwargs) -> str:
    """Resuelve template de tópico con valores de configuración."""
    template = config["topics"][topic_key]
    return template.format(
        org=config["org"],
        app=config["app"],
        cap=config["cap"],
        id=config["id"],
        **kwargs
    )

def timestamp_iso() -> str:
    """Retorna timestamp actual en formato ISO8601 UTC."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

# ═══════════════════════════════════════════════════════════════════════════
# DISPATCHER DE COMANDOS
# ═══════════════════════════════════════════════════════════════════════════

class CommandDispatcher:
    """Centraliza el manejo de comandos recibidos via MQTT."""
    
    def __init__(self, config: dict, logger: StructuredLogger):
        self.config = config
        self.logger = logger
        self.handlers = {
            "restart_acquisition": self._cmd_restart_acquisition,
            "cleanup_files": self._cmd_cleanup_files,
            "get_status": self._cmd_get_status,
            # Agregar más comandos aquí
        }
    
    def dispatch(self, task_name: str, payload: dict, client) -> dict:
        """Ejecuta el handler correspondiente al comando."""
        handler = self.handlers.get(task_name)
        if handler:
            self.logger.info(f"[CMD_DISPATCH] Ejecutando: {task_name}")
            return handler(payload, client)
        else:
            self.logger.warning(f"[CMD_UNKNOWN] Comando no reconocido: {task_name}")
            return {"status": "error", "message": f"Unknown command: {task_name}"}
    
    def _cmd_restart_acquisition(self, payload: dict, client) -> dict:
        """Reinicia el proceso de adquisición."""
        # TODO: Implementar interacción con capa de adquisición
        return {"status": "pending", "message": "Not implemented yet"}
    
    def _cmd_cleanup_files(self, payload: dict, client) -> dict:
        """Limpieza de archivos temporales."""
        # TODO: Implementar limpieza
        return {"status": "pending", "message": "Not implemented yet"}
    
    def _cmd_get_status(self, payload: dict, client) -> dict:
        """Retorna estado actual del sistema."""
        return {
            "status": "ok",
            "uptime_s": int(time.time() - START_TIME),
            "timestamp": timestamp_iso()
        }

# ═══════════════════════════════════════════════════════════════════════════
# CORRELACIÓN DE EVENTOS (PLACEHOLDER)
# ═══════════════════════════════════════════════════════════════════════════

class EventCorrelator:
    """Placeholder para lógica de correlación regional."""
    
    def __init__(self, config: dict, logger: StructuredLogger):
        self.config = config
        self.logger = logger
        self.recent_events = []  # Buffer de eventos recientes
    
    def on_regional_event(self, station_id: str, event_data: dict):
        """Procesa detección de otra estación."""
        self.logger.info(f"[EVENT_REGIONAL] Recibido de {station_id}")
        self.recent_events.append({
            "station": station_id,
            "data": event_data,
            "received_at": timestamp_iso()
        })
        # TODO: Implementar lógica de correlación con módulo externo

# ═══════════════════════════════════════════════════════════════════════════
# PUBLICACIÓN DE TELEMETRÍA
# ═══════════════════════════════════════════════════════════════════════════

def publicar_state(client, config: dict, estado: str, logger: StructuredLogger):
    """Publica estado operacional (online/offline/on)."""
    topic = resolver_topico(config, "telemetry_state")
    payload = {"status": estado, "timestamp": timestamp_iso()}
    qos = config["qos"]["telemetry"]
    retain = config["retain"]["telemetry_state"]
    result = client.publish(topic, json.dumps(payload), qos=qos, retain=retain)
    logger.mqtt_publish(topic, "ok" if result.rc == 0 else "fail")

def obtener_metricas_hardware() -> dict:
    """Obtiene métricas de hardware de Raspberry Pi."""
    metricas = {}
    
    # 1. Porcentaje de disco en uso
    try:
        statvfs = os.statvfs('/')
        total = statvfs.f_blocks * statvfs.f_frsize
        free = statvfs.f_bavail * statvfs.f_frsize
        metricas["disk_percent"] = round(((total - free) / total) * 100, 1)
    except:
        metricas["disk_percent"] = -1
    
    # 2. Porcentaje de RAM en uso
    try:
        with open('/proc/meminfo', 'r') as f:
            mem_total = None
            mem_available = None
            for line in f:
                if line.startswith('MemTotal:'):
                    mem_total = int(line.split()[1])
                elif line.startswith('MemAvailable:'):
                    mem_available = int(line.split()[1])
                if mem_total and mem_available:
                    break
        if mem_total and mem_available:
            metricas["ram_percent"] = round(((mem_total - mem_available) / mem_total) * 100, 1)
        else:
            metricas["ram_percent"] = -1
    except:
        metricas["ram_percent"] = -1
    
    # 3. Load average 15 minutos
    try:
        metricas["load_avg_15m"] = round(os.getloadavg()[2], 2)
    except:
        metricas["load_avg_15m"] = -1
    
    # 4. Temperatura CPU (Raspberry Pi)
    try:
        import subprocess
        result = subprocess.run(
            ['vcgencmd', 'measure_temp'],
            capture_output=True, text=True, timeout=5
        )
        # Formato: temp=52.3'C
        temp_str = result.stdout.strip().split('=')[1].split("'")[0]
        metricas["cpu_temp_c"] = float(temp_str)
    except:
        metricas["cpu_temp_c"] = -1
    
    # 5. Estado de throttling (Raspberry Pi)
    try:
        import subprocess
        result = subprocess.run(
            ['vcgencmd', 'get_throttled'],
            capture_output=True, text=True, timeout=5
        )
        # Formato: throttled=0x0
        throttled_hex = result.stdout.strip().split('=')[1]
        metricas["throttled"] = throttled_hex
    except:
        metricas["throttled"] = "unknown"
    
    return metricas

def publicar_health(client, config: dict, logger: StructuredLogger):
    """Publica métricas de hardware cada HEALTH_INTERVAL segundos."""
    topic = resolver_topico(config, "telemetry_health")
    
    metricas = obtener_metricas_hardware()
    metricas["timestamp"] = timestamp_iso()
    metricas["uptime_s"] = int(time.time() - START_TIME)
    
    qos = config["qos"]["telemetry"]
    retain = config["retain"]["telemetry_health"]
    client.publish(topic, json.dumps(metricas), qos=qos, retain=retain)

# ═══════════════════════════════════════════════════════════════════════════
# CALLBACKS MQTT
# ═══════════════════════════════════════════════════════════════════════════

def on_connect(client, userdata, flags, rc, properties=None):
    """Callback de conexión al broker."""
    logger = userdata["logger"]
    config = userdata["config"]
    
    if rc == 0:
        logger.mqtt_connect(config["broker"]["address"], "ok")
        
        # Suscribirse a tópicos configurados
        for sub_key in config["subscriptions"]:
            topic = resolver_topico(config, sub_key)
            client.subscribe(topic, qos=config["qos"].get("commands", 1))
            logger.mqtt_subscribe(topic, 1)
        
        # Publicar estado online
        publicar_state(client, config, "online", logger)
        userdata["is_disconnected_logged"] = False
    else:
        logger.mqtt_error("connect", f"Código de error: {rc}")

def on_disconnect(client, userdata, flags, rc=None, properties=None):
    """Callback de desconexión del broker."""
    logger = userdata["logger"]
    # En v1, flags es el código de retorno (rc). En v2, rc es el reason_code.
    real_rc = rc if rc is not None else flags
    
    if real_rc != 0 and not userdata.get("is_disconnected_logged", False):
        logger.mqtt_disconnect(f"Inesperada, código: {real_rc}")
        userdata["is_disconnected_logged"] = True

def on_message(client, userdata, msg):
    """Callback para mensajes recibidos."""
    logger = userdata["logger"]
    config = userdata["config"]
    dispatcher = userdata["dispatcher"]
    correlator = userdata["correlator"]
    
    topic = msg.topic
    try:
        payload = json.loads(msg.payload.decode())
    except json.JSONDecodeError:
        logger.mqtt_error("parse", f"JSON inválido en {topic}")
        return
    
    # Detectar tipo de mensaje por el tópico
    if "/cmd/" in topic:
        # Extraer nombre del comando del tópico
        task_name = topic.split("/cmd/")[-1]
        response = dispatcher.dispatch(task_name, payload, client)
        
        # Publicar respuesta
        res_topic = resolver_topico(config, "cmd_response", task_name=task_name)
        client.publish(res_topic, json.dumps(response), qos=1)
        
    elif "/events/detected" in topic and config["id"] not in topic:
        # Evento de otra estación (correlación regional)
        station_id = topic.split("/")[3]  # Extraer ID de estación
        correlator.on_regional_event(station_id, payload)
    
    elif "/config/set" in topic:
        # Configuración dinámica (placeholder)
        logger.info(f"[CONFIG_SET] Recibido: {payload}")

# ═══════════════════════════════════════════════════════════════════════════
# INICIALIZACIÓN Y LOOP PRINCIPAL
# ═══════════════════════════════════════════════════════════════════════════

def iniciar_cliente(config: dict, logger: StructuredLogger):
    """Inicializa y configura el cliente MQTT."""
    dispatcher = CommandDispatcher(config, logger)
    correlator = EventCorrelator(config, logger)
    
    userdata = {
        "config": config,
        "logger": logger,
        "dispatcher": dispatcher,
        "correlator": correlator,
        "is_disconnected_logged": False
    }
    
    try:
        # Soporta Paho-MQTT v2.x con Callback API Version 2
        client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, userdata=userdata)
    except AttributeError:
        # Soporta Paho-MQTT v1.x
        client = mqtt.Client(userdata=userdata)
    client.on_connect = on_connect
    client.on_disconnect = on_disconnect
    client.on_message = on_message
    
    # Configurar LWT
    lwt_topic = resolver_topico(config, "telemetry_state")
    lwt_payload = json.dumps({"status": "offline", "timestamp": timestamp_iso()})
    client.will_set(lwt_topic, lwt_payload, qos=1, retain=True)
    
    # Conectar
    broker = config["broker"]
    client.username_pw_set(broker["username"], broker["password"])
    client.connect(broker["address"], broker["port"], keepalive=60)
    
    return client

def main():
    # Obtiene la variable de entorno para definir la raíz del proyecto local
    project_local_root = os.getenv("PROJECT_LOCAL_ROOT")
    if not project_local_root:
        print("La variable de entorno PROJECT_LOCAL_ROOT no está definida.")
        return

    # Definir rutas de configuración y logs siguiendo el estándar del proyecto
    CONFIG_PATH = os.path.join(project_local_root, "configuracion", "configuracion_mqtt.json")
    ENV_PATH = os.path.join(project_local_root, "configuracion", ".env")
    LOG_DIR = os.path.join(project_local_root, "log-files")
    
    # Cargar configuración
    config = cargar_configuracion(CONFIG_PATH, ENV_PATH)
    
    # Inicializar logger
    logger = StructuredLogger(
        id_estacion=config["id"],
        log_directory=LOG_DIR,
        log_filename="mqtt_coordinator.log",
        verbosity="INFO"
    )
    logger.init({"component": "mqtt_coordinator", "version": "1.0.0"})
    
    # Iniciar cliente
    client = iniciar_cliente(config, logger)
    client.loop_start()
    
    # Publicar estado inicial
    publicar_state(client, config, "on", logger)
    
    # Loop principal con timers de telemetría
    last_health = 0
    
    try:
        while True:
            now = time.time()
            
            if now - last_health >= HEALTH_INTERVAL:
                publicar_health(client, config, logger)
                last_health = now
            
            time.sleep(1)
            
    except KeyboardInterrupt:
        logger.info("[SHUTDOWN] Deteniendo coordinador...")
        publicar_state(client, config, "offline", logger)
        client.loop_stop()
        client.disconnect()

if __name__ == "__main__":
    main()

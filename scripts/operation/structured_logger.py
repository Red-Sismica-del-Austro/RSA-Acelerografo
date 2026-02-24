import logging
import os
from logging.handlers import RotatingFileHandler

class StructuredLogger:
    def __init__(self, id_estacion, log_directory, log_filename, verbosity="SUMMARY", max_bytes=5*1024*1024, backup_count=3):
        self.id_estacion = id_estacion
        self.log_directory = log_directory
        self.log_filename = log_filename
        self.verbosity = verbosity.upper()
        
        # Mapeo de verbosidad a niveles de logging estándar
        # SUMMARY es un nivel personalizado que manejamos nosotros
        self.numeric_level = logging.DEBUG
        
        # Asegurar que el directorio existe
        if not os.path.exists(log_directory):
            os.makedirs(log_directory, exist_ok=True)
            
        log_path = os.path.join(log_directory, log_filename)
        
        # Configurar logger
        self.logger = logging.getLogger(f"{id_estacion}_{log_filename}")
        self.logger.setLevel(logging.DEBUG)
        
        # Evitar duplicar handlers
        if not self.logger.handlers:
            handler = RotatingFileHandler(log_path, maxBytes=max_bytes, backupCount=backup_count)
            formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
            handler.setFormatter(formatter)
            self.logger.addHandler(handler)
            
    def _should_log(self, msg_level):
        """Determina si un mensaje debe ser logueado basado en la verbosidad configurada"""
        levels = {"DEBUG": 0, "INFO": 1, "SUMMARY": 2}
        config_level = levels.get(self.verbosity, 2)
        msg_lvl = levels.get(msg_level, 1)
        return msg_lvl >= config_level

    def _log_structured(self, level, tag, name, details=None):
        """Método interno para loguear con formato estándar [TAG] type | name | details"""
        if not self._should_log(level):
            return
        
        msg = f"[{tag}]"
        if name:
            msg += f" {name}"
        
        if details:
            if isinstance(details, dict):
                details_str = " | ".join([f"{k}={v}" for k, v in details.items()])
            else:
                details_str = str(details)
            msg += f" | {details_str}"
            
        if level == "DEBUG":
            self.logger.debug(msg)
        elif level == "INFO":
            self.logger.info(msg)
        elif level == "WARNING":
            self.logger.warning(msg)
        elif level == "ERROR":
            self.logger.error(msg)
        else: # DEFAULT SUMMARY -> INFO
            self.logger.info(msg)

    def init(self, details):
        self._log_structured("SUMMARY", "INIT", None, details)

    def upload_ok(self, type_file, name_file, **kwargs):
        self._log_structured("INFO", "UPLOAD_OK", f"{type_file} | {name_file}", kwargs)

    def upload_fail(self, type_file, name_file, error):
        self._log_structured("SUMMARY", "UPLOAD_FAIL", f"{type_file} | {name_file}", {"error": error})

    def delete_age(self, type_file, name_file, age):
        self._log_structured("INFO", "DELETE_AGE", f"{type_file} | {name_file}", {"age": f"{age}d"})

    def delete_space(self, type_file, name_file, free):
        self._log_structured("SUMMARY", "DELETE_SPACE", f"{type_file} | {name_file}", {"reason": free})

    def protected(self, type_file, name_file, reason):
        self._log_structured("INFO", "PROTECTED", f"{type_file} | {name_file}", {"reason": reason})

    def skip(self, type_file, name_file, reason):
        self._log_structured("DEBUG", "SKIP", f"{type_file} | {name_file}", {"reason": reason})

    def summary(self, **kwargs):
        self._log_structured("SUMMARY", "SUMMARY", None, kwargs)

    def error(self, operation, error=None):
        """
        Registra un error. Compatible con ambas firmas:
        - error(mensaje)           # Estilo logging estándar
        - error(operation, error)  # Estilo estructurado
        """
        if error is None:
            # Llamada con un solo argumento (estilo estándar)
            # Usar 'operation' como mensaje de error
            details = {"error": operation}
            self._log_structured("SUMMARY", "ERROR", None, details)
        else:
            # Llamada con dos argumentos (estilo estructurado)
            self._log_structured("SUMMARY", "ERROR", None, {"operation": operation, "error": error})

    def info(self, msg):
        if self._should_log("INFO"):
            self.logger.info(msg)

    def warning(self, msg):
        if self._should_log("SUMMARY"):
            self.logger.warning(msg)

    # --- Métodos específicos para conversión (mseed) ---

    def convert_start(self, modo, nombre):
        """[CONVERT_START] Inicio de conversión de archivo"""
        self._log_structured("INFO", "CONVERT_START", nombre, {"modo": modo})

    def convert_ok(self, nombre_bin, nombre_mseed, tiempo):
        """[CONVERT_OK] Conversión exitosa"""
        self._log_structured("SUMMARY", "CONVERT_OK", nombre_bin, {"mseed": nombre_mseed, "tiempo": f"{tiempo:.2f}s"})

    def convert_fail(self, nombre, error):
        """[CONVERT_FAIL] Conversión fallida"""
        self._log_structured("SUMMARY", "CONVERT_FAIL", nombre, {"error": error})

    def read_ok(self, nombre, tiempo=None):
        """[READ_OK] Archivo binario leído"""
        self._log_structured("DEBUG", "READ_OK", nombre, {"status": "ok", "tiempo": f"{tiempo:.2f}s" if tiempo else "N/A"})

    def data_warning(self, nombre, tipo_warning, detalles):
        """[DATA_WARNING] Problemas en datos: tramas inválidas, segundos faltantes"""
        self._log_structured("INFO", "DATA_WARNING", nombre, {"tipo": tipo_warning, "info": detalles})

    def config_error(self, componente, mensaje):
        """[CONFIG_ERROR] Errores de configuración"""
        self._log_structured("SUMMARY", "CONFIG_ERROR", componente, {"msg": mensaje})

    # --- Métodos específicos para MQTT ---

    def mqtt_connect(self, broker: str, status: str):
        """[MQTT_CONNECT] Conexión/reconexión al broker"""
        self._log_structured("SUMMARY", "MQTT_CONNECT", broker, {"status": status})

    def mqtt_disconnect(self, reason: str):
        """[MQTT_DISCONNECT] Desconexión del broker"""
        self._log_structured("SUMMARY", "MQTT_DISCONNECT", None, {"reason": reason})

    def mqtt_publish(self, topic: str, status: str = "ok"):
        """[MQTT_PUBLISH] Mensaje publicado"""
        self._log_structured("DEBUG", "MQTT_PUBLISH", topic, {"status": status})

    def mqtt_subscribe(self, topic: str, qos: int):
        """[MQTT_SUBSCRIBE] Suscripción a tópico"""
        self._log_structured("INFO", "MQTT_SUBSCRIBE", topic, {"qos": qos})

    def mqtt_error(self, operation: str, error: str):
        """[MQTT_ERROR] Error en operación MQTT"""
        self._log_structured("SUMMARY", "MQTT_ERROR", operation, {"error": error})

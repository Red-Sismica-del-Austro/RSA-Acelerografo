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

    def _format_msg(self, tag, type_file, name_file, details=None):
        if details:
            return f"{tag} {type_file} | {name_file} | {details}"
        return f"{tag} {type_file} | {name_file}"

    def init(self, details):
        if self._should_log("SUMMARY"):
            self.logger.info(f"[INIT] {details}")

    def upload_ok(self, type_file, name_file, **kwargs):
        if self._should_log("INFO"):
            details = " | ".join([f"{k}={v}" for k, v in kwargs.items()])
            self.logger.info(self._format_msg("[UPLOAD_OK]", type_file, name_file, details))

    def upload_fail(self, type_file, name_file, error):
        if self._should_log("SUMMARY"):
            self.logger.error(self._format_msg("[UPLOAD_FAIL]", type_file, name_file, f"error={error}"))

    def delete_age(self, type_file, name_file, age):
        if self._should_log("INFO"):
            self.logger.info(self._format_msg("[DELETE_AGE]", type_file, name_file, f"age={age}d"))

    def delete_space(self, type_file, name_file, free):
        if self._should_log("SUMMARY"):
            self.logger.warning(self._format_msg("[DELETE_SPACE]", type_file, name_file, f"free={free}%"))

    def protected(self, type_file, name_file, reason):
        if self._should_log("INFO"):
            self.logger.info(self._format_msg("[PROTECTED]", type_file, name_file, f"reason={reason}"))

    def skip(self, type_file, name_file, reason):
        if self._should_log("DEBUG"):
            self.logger.debug(self._format_msg("[SKIP]", type_file, name_file, f"reason={reason}"))

    def summary(self, **kwargs):
        if self._should_log("SUMMARY"):
            details = " | ".join([f"{k}={v}" for k, v in kwargs.items()])
            self.logger.info(f"[SUMMARY] {details}")

    def error(self, operation, error):
        if self._should_log("SUMMARY"):
            self.logger.error(f"[ERROR] operation={operation} | error={error}")

    def info(self, msg):
        """Mensaje genérico de información"""
        if self._should_log("INFO"):
            self.logger.info(msg)

    def warning(self, msg):
        """Mensaje genérico de advertencia"""
        if self._should_log("SUMMARY"):
            self.logger.warning(msg)

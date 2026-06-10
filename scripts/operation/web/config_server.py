#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
config_server.py — Servidor Web de Configuración del Acelerógrafo (RSA)

Panel Flask que expone una API REST para leer, validar y aplicar la
configuración maestra de la estación. Al aplicar cambios ejecuta
hidratar_configuracion.py y reinicia los servicios necesarios.

Seguridad:
  - Escucha exclusivamente en 127.0.0.1:5000 (acceso vía túnel SSH).
  - Todos los inputs se validan antes de cualquier operación en disco.
  - Los subprocesos usan rutas absolutas hardcodeadas (allow-list).
  - Se realiza backup automático antes de sobrescribir la configuración.
  - Cabeceras HTTP de seguridad aplicadas en cada respuesta.
  - No se utiliza autenticación en esta fase (protección provista por SSH).
    TODO(security): Implementar autenticación HTTP (Basic Auth o Bearer token)
    cuando se cambie el bind address a 0.0.0.0 para acceso vía WiFi AP.
  - No se usan cookies de sesión, por lo que CSRF no aplica en esta fase.
    TODO(security): Agregar CSRF tokens si en el futuro se implementa auth por cookies.

Inicio:
  PROJECT_LOCAL_ROOT=/ruta/local python3 config_server.py
"""

import os
import re
import sys
import json
import shutil
import logging
import subprocess
import fcntl
from datetime import datetime
from pathlib import Path

from flask import Flask, jsonify, request, send_from_directory, abort

# ---------------------------------------------------------------------------
# Resolución de rutas
# ---------------------------------------------------------------------------

PROJECT_LOCAL_ROOT = os.getenv("PROJECT_LOCAL_ROOT")
if not PROJECT_LOCAL_ROOT:
    print("ERROR CRÍTICO: La variable PROJECT_LOCAL_ROOT no está definida.", file=sys.stderr)
    sys.exit(1)

PROJECT_GIT_ROOT = os.getenv("PROJECT_GIT_ROOT", "")

LOCAL_CONFIG_DIR  = os.path.join(PROJECT_LOCAL_ROOT, "configuracion")
MASTER_CONFIG     = os.path.join(LOCAL_CONFIG_DIR, "configuracion_maestra.json")
LOG_DIR           = os.path.join(PROJECT_LOCAL_ROOT, "log-files")

# Ruta al script de hidratación (en el Git root si está disponible,
# fallback al mismo directorio de este script para compatibilidad)
if PROJECT_GIT_ROOT:
    HYDRATE_SCRIPT = os.path.join(PROJECT_GIT_ROOT, "scripts", "setup", "hidratar_configuracion.py")
else:
    HYDRATE_SCRIPT = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "..", "..", "setup", "hidratar_configuracion.py"
    )

# Ruta al directorio de templates/static (junto a este script)
SCRIPT_DIR   = os.path.dirname(os.path.abspath(__file__))
TEMPLATE_DIR = os.path.join(SCRIPT_DIR, "templates")
STATIC_DIR   = os.path.join(SCRIPT_DIR, "static")

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

os.makedirs(LOG_DIR, exist_ok=True)
log_path = os.path.join(LOG_DIR, "config_server.log")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(log_path, encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger("config_server")

# ---------------------------------------------------------------------------
# Aplicación Flask
# ---------------------------------------------------------------------------

app = Flask(__name__, template_folder=TEMPLATE_DIR, static_folder=STATIC_DIR)

# ---------------------------------------------------------------------------
# Cabeceras de seguridad HTTP en todas las respuestas
# ---------------------------------------------------------------------------

@app.after_request
def apply_security_headers(response):
    """Agrega cabeceras de seguridad a todas las respuestas HTTP."""
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; "
        "script-src 'self'; "
        "style-src 'self'; "
        "img-src 'self' data:; "
        "object-src 'none'; "
        "frame-ancestors 'none';"
    )
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    # Evita que respuestas de API sean cacheadas por el navegador
    if request.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store"
    return response

# ---------------------------------------------------------------------------
# Métodos HTTP permitidos (allow-list)
# ---------------------------------------------------------------------------
# Solo GET y POST son necesarios; el resto se deniega con 405.
app.config["ALLOWED_METHODS"] = {"GET", "POST"}

@app.before_request
def restrict_http_methods():
    if request.method not in app.config["ALLOWED_METHODS"]:
        abort(405)

# ---------------------------------------------------------------------------
# Validación de la configuración maestra
# ---------------------------------------------------------------------------

_ESTACION_ID_RE = re.compile(r'^[A-Z]{3}\d$')
_MODO_ADQUISICION_VALS = {"online", "offline"}
_FUENTE_RELOJ_VALS     = {"0", "1"}
_SI_NO_VALS            = {"si", "no"}


def _validar_configuracion(data: dict) -> list[str]:
    """
    Valida el payload de configuración maestra.
    Retorna lista de errores (vacía si es válida).

    Aplica allow-list en cada campo para prevenir inyección de datos.
    """
    errores = []

    # --- Campos de primer nivel obligatorios ---
    required = ["estacion_id", "nombre", "coordenadas", "adquisicion", "drive_folder_ids"]
    for campo in required:
        if campo not in data:
            errores.append(f"Campo obligatorio faltante: '{campo}'")

    if errores:
        return errores  # No continuar si faltan claves raíz

    # --- estacion_id ---
    eid = data.get("estacion_id", "")
    if not isinstance(eid, str) or not _ESTACION_ID_RE.match(eid):
        errores.append(
            f"'estacion_id' debe cumplir el formato RSA: 3 letras mayúsculas + 1 dígito (ej: NOM0). Recibido: '{eid}'"
        )

    # --- nombre (debe ser todo en mayúsculas) ---
    nombre_val = data.get("nombre", "")
    if not isinstance(nombre_val, str) or not nombre_val.strip():
        errores.append("'nombre' no puede estar vacío.")
    elif len(nombre_val) > 200:
        errores.append("'nombre' supera los 200 caracteres.")
    elif nombre_val != nombre_val.upper():
        errores.append("'nombre' debe estar todo en mayúsculas (Ej: CHANLUD CIMA).")

    # --- coordenadas ---
    coords = data.get("coordenadas", {})
    if not isinstance(coords, dict):
        errores.append("'coordenadas' debe ser un objeto JSON.")
    else:
        lat = coords.get("latitud")
        lon = coords.get("longitud")
        alt = coords.get("altitud")
        if not isinstance(lat, (int, float)) or not (-90.0 <= lat <= 90.0):
            errores.append("'coordenadas.latitud' debe ser un número entre -90 y 90.")
        if not isinstance(lon, (int, float)) or not (-180.0 <= lon <= 180.0):
            errores.append("'coordenadas.longitud' debe ser un número entre -180 y 180.")
        if not isinstance(alt, (int, float)) or alt < 0:
            errores.append("'coordenadas.altitud' debe ser un número >= 0.")

    # --- adquisicion ---
    adq = data.get("adquisicion", {})
    if not isinstance(adq, dict):
        errores.append("'adquisicion' debe ser un objeto JSON.")
    else:
        if adq.get("fuente_reloj") not in _FUENTE_RELOJ_VALS:
            errores.append("'adquisicion.fuente_reloj' debe ser '0' (RPi) o '1' (GPS).")
        if adq.get("modo_adquisicion") not in _MODO_ADQUISICION_VALS:
            errores.append("'adquisicion.modo_adquisicion' debe ser 'online' u 'offline'.")
        if adq.get("deteccion_eventos") not in _SI_NO_VALS:
            errores.append("'adquisicion.deteccion_eventos' debe ser 'si' o 'no'.")
        if adq.get("publicar_eventos") not in _SI_NO_VALS:
            errores.append("'adquisicion.publicar_eventos' debe ser 'si' o 'no'.")

    # --- drive_folder_ids ---
    drive = data.get("drive_folder_ids", {})
    if not isinstance(drive, dict):
        errores.append("'drive_folder_ids' debe ser un objeto JSON.")
    else:
        for key in ("continuos_id", "mseed_id", "events_id", "tmp_id", "logs_id"):
            if key not in drive or not isinstance(drive[key], str):
                errores.append(f"'drive_folder_ids.{key}' debe ser una cadena de texto.")

    return errores


# ---------------------------------------------------------------------------
# Ejecución segura de subprocesos (allow-list estricta)
# ---------------------------------------------------------------------------

def _ejecutar_subproceso(cmd: list[str], descripcion: str) -> tuple[bool, str]:
    """
    Ejecuta un subproceso de forma segura.
    Los argumentos son una lista fija (sin shell=True).
    Retorna (éxito: bool, salida: str).
    """
    try:
        logger.info("[SUBPROCESO] Iniciando: %s", descripcion)
        resultado = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=60,
            env={**os.environ, "PROJECT_LOCAL_ROOT": PROJECT_LOCAL_ROOT, "PROJECT_GIT_ROOT": PROJECT_GIT_ROOT},
        )
        if resultado.returncode == 0:
            logger.info("[SUBPROCESO] OK: %s", descripcion)
            return True, resultado.stdout
        else:
            logger.error("[SUBPROCESO] ERROR: %s | stderr: %s", descripcion, resultado.stderr[:500])
            return False, resultado.stderr
    except subprocess.TimeoutExpired:
        logger.error("[SUBPROCESO] TIMEOUT: %s", descripcion)
        return False, "Timeout al ejecutar el comando."
    except Exception as exc:
        logger.error("[SUBPROCESO] EXCEPCIÓN: %s | %s", descripcion, exc)
        return False, str(exc)


# Rutas absolutas hardcodeadas para comandos permitidos (allow-list)
_PYTHON_BIN     = os.path.join(PROJECT_LOCAL_ROOT, ".venv", "bin", "python3")
_REGISTROCONT   = "/usr/local/bin/registrocontinuo"
_SUPERVISORCTL  = "/usr/bin/supervisorctl"


def _hidratar():
    return _ejecutar_subproceso(
        [_PYTHON_BIN, HYDRATE_SCRIPT],
        "Hidratación de configuración"
    )


def _reiniciar_registro_continuo():
    return _ejecutar_subproceso(
        ["sudo", _REGISTROCONT, "restart"],
        "Reiniciar registro_continuo"
    )


def _reiniciar_mqtt():
    return _ejecutar_subproceso(
        ["sudo", _SUPERVISORCTL, "restart", "mqtt_coordinator"],
        "Reiniciar mqtt_coordinator"
    )


def _estado_registro_continuo() -> bool:
    try:
        r = subprocess.run(
            ["pgrep", "-f", "registro_continuo"],
            capture_output=True, timeout=5
        )
        return r.returncode == 0
    except Exception:
        return False


def _estado_mqtt() -> str:
    try:
        r = subprocess.run(
            ["sudo", _SUPERVISORCTL, "status", "mqtt_coordinator"],
            capture_output=True, text=True, timeout=10
        )
        # supervisorctl devuelve líneas como: "mqtt_coordinator   RUNNING   pid 1234..."
        for linea in r.stdout.splitlines():
            if "mqtt_coordinator" in linea:
                partes = linea.split()
                return partes[1] if len(partes) > 1 else "DESCONOCIDO"
        return "DESCONOCIDO"
    except Exception:
        return "ERROR"


# ---------------------------------------------------------------------------
# Endpoints de la API
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    """Sirve la página principal del panel de configuración."""
    return send_from_directory(TEMPLATE_DIR, "index.html")


@app.route("/api/config", methods=["GET"])
def get_config():
    """
    Retorna la configuración maestra actual.
    Lee el archivo JSON del sistema local.
    """
    if not os.path.exists(MASTER_CONFIG):
        logger.error("Archivo de configuración maestra no encontrado: %s", MASTER_CONFIG)
        return jsonify({"error": "Archivo de configuración no encontrado."}), 404

    try:
        with open(MASTER_CONFIG, "r", encoding="utf-8") as f:
            config = json.load(f)
        return jsonify(config), 200
    except json.JSONDecodeError as exc:
        logger.error("Error al decodificar configuracion_maestra.json: %s", exc)
        return jsonify({"error": "El archivo de configuración está corrupto."}), 500


@app.route("/api/config", methods=["POST"])
def post_config():
    """
    Valida y aplica una nueva configuración maestra.

    Flujo:
      1. Validar Content-Type y payload JSON.
      2. Validar todos los campos (allow-list de valores).
      3. Crear backup .bak del archivo actual.
      4. Escribir nueva configuración con file lock.
      5. Ejecutar hidratar_configuracion.py.
      6. Reiniciar registro_continuo y mqtt_coordinator.
      7. Ante cualquier fallo en 5-6, restaurar backup.
    """
    # 1. Validar Content-Type
    if not request.is_json:
        return jsonify({"error": "Content-Type debe ser application/json."}), 415

    try:
        data = request.get_json(force=False, silent=False)
    except Exception:
        return jsonify({"error": "JSON inválido en el cuerpo de la solicitud."}), 400

    if not isinstance(data, dict):
        return jsonify({"error": "El cuerpo debe ser un objeto JSON."}), 400

    # 2. Validar campos
    errores = _validar_configuracion(data)
    if errores:
        logger.warning("Configuración rechazada por errores de validación: %s", errores)
        return jsonify({"error": "Configuración inválida.", "detalles": errores}), 422

    # Crear directorio si no existe
    os.makedirs(LOCAL_CONFIG_DIR, exist_ok=True)

    backup_path = MASTER_CONFIG + ".bak"
    config_anterior_existe = os.path.exists(MASTER_CONFIG)

    # 3. Backup del archivo actual
    if config_anterior_existe:
        try:
            shutil.copy2(MASTER_CONFIG, backup_path)
            logger.info("Backup creado: %s", backup_path)
        except Exception as exc:
            logger.error("No se pudo crear backup: %s", exc)
            return jsonify({"error": "No se pudo crear el backup de seguridad."}), 500

    # 4. Escribir nueva configuración con file lock
    try:
        with open(MASTER_CONFIG, "w", encoding="utf-8") as f:
            fcntl.flock(f, fcntl.LOCK_EX)
            json.dump(data, f, ensure_ascii=False, indent=4)
            fcntl.flock(f, fcntl.LOCK_UN)
        logger.info("configuracion_maestra.json actualizado para estacion_id='%s'", data.get("estacion_id"))
    except Exception as exc:
        logger.error("Error al escribir configuracion_maestra.json: %s", exc)
        return jsonify({"error": "No se pudo guardar la configuración."}), 500

    # 5. Hidratar
    ok_hidratacion, salida_hidratacion = _hidratar()
    if not ok_hidratacion:
        logger.error("Hidratación fallida. Restaurando backup.")
        if config_anterior_existe:
            shutil.copy2(backup_path, MASTER_CONFIG)
        return jsonify({
            "error": "Fallo en la hidratación de configuración. Se restauró la configuración anterior.",
            "detalle": salida_hidratacion[:500],  # Truncar para no exponer rutas internas
        }), 500

    # 6. Reiniciar servicios (errores no críticos: se reportan pero no se hace rollback)
    errores_servicios = []

    ok_rc, _ = _reiniciar_registro_continuo()
    if not ok_rc:
        errores_servicios.append("registro_continuo no pudo reiniciarse.")

    ok_mqtt, _ = _reiniciar_mqtt()
    if not ok_mqtt:
        errores_servicios.append("mqtt_coordinator no pudo reiniciarse.")

    respuesta = {
        "status": "ok",
        "message": "Configuración aplicada exitosamente.",
        "estacion_id": data.get("estacion_id"),
        "timestamp": datetime.now().isoformat(),
    }
    if errores_servicios:
        respuesta["advertencias"] = errores_servicios

    return jsonify(respuesta), 200


@app.route("/api/status", methods=["GET"])
def get_status():
    """
    Retorna el estado de los servicios del acelerógrafo y la sincronización
    de la configuración.
    """
    rc_running = _estado_registro_continuo()
    mqtt_status = _estado_mqtt()

    # Verificar si configuracion_maestra.json existe y es válido
    config_ok = False
    ultima_mod = None
    if os.path.exists(MASTER_CONFIG):
        try:
            with open(MASTER_CONFIG, "r", encoding="utf-8") as f:
                json.load(f)
            config_ok = True
            mtime = os.path.getmtime(MASTER_CONFIG)
            ultima_mod = datetime.fromtimestamp(mtime).isoformat()
        except Exception:
            config_ok = False

    return jsonify({
        "registro_continuo": {"running": rc_running},
        "mqtt_coordinator":  {"status": mqtt_status},
        "config_maestra":    {"valida": config_ok, "ultima_modificacion": ultima_mod},
    }), 200


# ---------------------------------------------------------------------------
# Punto de entrada
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    logger.info("=== Iniciando config_server.py ===")
    logger.info("PROJECT_LOCAL_ROOT: %s", PROJECT_LOCAL_ROOT)
    logger.info("Configuración maestra: %s", MASTER_CONFIG)
    logger.info("Script de hidratación: %s", HYDRATE_SCRIPT)

    # El servidor escucha en 0.0.0.0 para permitir acceso vía WiFi AP en wlan0.
    # El puerto 5000 se protege contra accesos externos vía eth0 mediante reglas de iptables
    # aplicadas por el script wifiap al activar el AP.
    # TODO(security): Implementar autenticación HTTP (Basic Auth o Bearer token)
    # para proteger adicionalmente la interfaz web.
    app.run(host="0.0.0.0", port=5000, debug=False)

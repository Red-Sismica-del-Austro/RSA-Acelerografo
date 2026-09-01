"""
Módulo orquestador para la extracción de eventos sísmicos y su subida a Drive.

Ejecuta extract_segment.py dentro del entorno virtual (.venv) y subir_archivo.py
con el Python del sistema, como subprocesos independientes.

No debe importarse ninguna dependencia de ObsPy aquí — el aislamiento se garantiza
mediante subprocess.
"""

import os
import re
import sys
import subprocess
import json
import shutil
from datetime import datetime, timedelta
from typing import Optional


# ============================================================================
# RESOLUCIÓN DE RUTAS
# ============================================================================

def _resolver_rutas() -> dict:
    """
    Resuelve dinámicamente las rutas de los scripts y del entorno virtual,
    basándose en PROJECT_LOCAL_ROOT y en la ubicación de este archivo.

    Returns:
        dict con claves: venv_python, extract_script, upload_script
    
    Raises:
        EnvironmentError: Si PROJECT_LOCAL_ROOT no está definida
        FileNotFoundError: Si alguna ruta requerida no existe
    """
    project_local_root = os.getenv("PROJECT_LOCAL_ROOT")
    if not project_local_root:
        raise EnvironmentError("La variable de entorno PROJECT_LOCAL_ROOT no está definida.")

    # Directorio raíz de scripts/operation (este archivo está en mqtt/)
    operation_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    rutas = {
        "venv_python":     os.path.join(project_local_root, ".venv", "bin", "python3"),
        "extract_script":  os.path.join(operation_dir, "mseed", "extract_segment.py"),
        "upload_script":   os.path.join(operation_dir, "drive", "subir_archivo.py"),
    }

    # Validar existencia
    for nombre, ruta in rutas.items():
        if not os.path.exists(ruta):
            raise FileNotFoundError(f"Ruta requerida no encontrada [{nombre}]: {ruta}")

    return rutas


# ============================================================================
# PARSING DE SALIDA
# ============================================================================

def _parsear_archivo_generado(stdout: str) -> Optional[str]:
    """
    Extrae el nombre del archivo de salida del stdout de extract_segment.py.

    La línea buscada tiene el formato:
        Archivo:  /ruta/completa/NOM00_20260510_143045.mseed

    Args:
        stdout: Salida estándar del proceso de extracción

    Returns:
        Nombre del archivo (sin ruta), o None si no se encuentra
    """
    for linea in stdout.splitlines():
        match = re.search(r'Archivo:\s+(.+\.mseed)', linea)
        if match:
            return os.path.basename(match.group(1).strip())
    return None


# ============================================================================
# EXTRACTOR DESDE RING BUFFER
# ============================================================================

def _leer_config_dispositivo(project_local_root: str) -> Optional[dict]:
    config_path = os.path.join(project_local_root, "configuracion", "configuracion_dispositivo.json")
    try:
        with open(config_path, "r") as f:
            return json.load(f)
    except Exception:
        return None


def _obtener_codigo_estacion(project_local_root: str) -> str:
    config_mseed_file = os.path.join(project_local_root, "configuracion", "configuracion_mseed.json")
    try:
        with open(config_mseed_file, "r") as f:
            config = json.load(f)
        return config.get("CODIGO(1)", "Unknown")
    except Exception:
        return "Unknown"


def _intentar_extraer_desde_ring_buffer(
    start_str: str,
    duration: float,
    logger
) -> Optional[str]:
    """
    Intenta extraer un segmento desde el ring buffer en disco.

    Returns:
        Ruta absoluta del archivo .mseed generado en el directorio de eventos extraídos,
        o None si falla o si el rango no está disponible en el ring buffer.
    """
    def _log(level: str, msg: str):
        if logger:
            if hasattr(logger, level):
                getattr(logger, level)(msg)
            elif hasattr(logger, "info"):
                logger.info(f"[{level.upper()}] {msg}")

    # 1. Obtener PROJECT_LOCAL_ROOT
    project_local_root = os.getenv("PROJECT_LOCAL_ROOT")
    if not project_local_root:
        _log("error", "[EVENT_EXTRACTOR] PROJECT_LOCAL_ROOT no definida al consultar ring buffer")
        return None

    # 2. Leer configuracion_dispositivo.json
    config = _leer_config_dispositivo(project_local_root)
    if not config:
        _log("error", "[EVENT_EXTRACTOR] No se pudo leer configuracion_dispositivo.json para ring buffer")
        return None

    # 3. Validar si el streaming está habilitado
    streaming_config = config.get("streaming", {})
    if not streaming_config.get("habilitado", False):
        _log("info", "[EVENT_EXTRACTOR] Streaming no habilitado en configuración; omitiendo ring buffer")
        return None

    ring_config = streaming_config.get("ring_buffer", {})
    dir_ring = ring_config.get("directorio", "/home/rsa/data/ring-buffer/")
    max_size_mb = ring_config.get("max_size_mb", 500)
    archivo_duracion_s = ring_config.get("archivo_duracion_min", 5) * 60

    # 4. Parsear start_str a datetime
    time_str = start_str.replace('Z', ' ')
    try:
        start_dt = datetime.strptime(time_str, "%Y-%m-%d %H:%M:%S.%f")
    except ValueError:
        try:
            start_dt = datetime.strptime(time_str, "%Y-%m-%d %H:%M:%S")
        except ValueError as e:
            _log("error", f"[EVENT_EXTRACTOR] Formato de start time inválido '{start_str}': {e}")
            return None

    end_dt = start_dt + timedelta(seconds=duration)

    # 5. Instanciar RingBufferStore en modo lectura
    operation_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if operation_dir not in sys.path:
        sys.path.insert(0, operation_dir)

    try:
        from streaming.ring_buffer_store import RingBufferStore
    except ImportError as e:
        _log("error", f"[EVENT_EXTRACTOR] No se pudo importar RingBufferStore: {e}")
        return None

    _log("info", f"[EVENT_EXTRACTOR] Abriendo RingBufferStore en {dir_ring} para verificar rango [{start_dt} a {end_dt}]")
    try:
        store = RingBufferStore(
            directorio=dir_ring,
            max_size_mb=max_size_mb,
            archivo_duracion_s=archivo_duracion_s,
            usar_fecha_filename=True
        )
    except Exception as e:
        _log("error", f"[EVENT_EXTRACTOR] Falló instanciar RingBufferStore: {e}")
        return None

    try:
        # Verificar si el rango está disponible
        time_range = store.get_time_range()
        if not time_range:
            _log("info", "[EVENT_EXTRACTOR] Ring buffer vacío; recurriendo a archivos mseed horarios")
            store.close()
            return None

        oldest_ts, newest_ts = time_range
        # Añadimos un pequeño margen por el jitter de las tramas
        if start_dt < oldest_ts or end_dt > newest_ts:
            _log("info", f"[EVENT_EXTRACTOR] Rango solicitado [{start_dt} a {end_dt}] fuera de la cobertura del ring buffer [{oldest_ts} a {newest_ts}]")
            store.close()
            return None

        # Extraer tramas crudas
        _log("info", f"[EVENT_EXTRACTOR] Rango disponible en ring buffer. Consultando tramas...")
        raw_frames = store.query_raw(start_dt, end_dt)
        store.close()

        if not raw_frames:
            _log("info", "[EVENT_EXTRACTOR] No se encontraron tramas en la consulta del ring buffer")
            return None

        _log("info", f"[EVENT_EXTRACTOR] Se obtuvieron {len(raw_frames)} tramas del ring buffer. Escribiendo archivo binario temporal...")

        # 6. Determinar directorios y nombres de archivos
        codigo_estacion = _obtener_codigo_estacion(project_local_root)
        path_eventos_extraidos = config.get("directorios", {}).get("eventos_extraidos", "")
        path_archivos_mseed = config.get("directorios", {}).get("archivos_mseed", "")

        if not path_eventos_extraidos or not path_archivos_mseed:
            _log("error", "[EVENT_EXTRACTOR] Directorios de configuración vacíos en configuracion_dispositivo.json")
            return None

        # Nombre de archivo temporal que cumple con el patrón CODIGO_AAMMDD-HHMMSS.dat
        temp_bin_name = f"{codigo_estacion}_{start_dt.strftime('%y%m%d-%H%M%S')}.dat"
        temp_bin_path = os.path.join(path_eventos_extraidos, temp_bin_name)

        # Escribir tramas al archivo temporal
        os.makedirs(path_eventos_extraidos, exist_ok=True)
        with open(temp_bin_path, "wb") as f:
            for frame in raw_frames:
                f.write(frame)

        _log("info", f"[EVENT_EXTRACTOR] Archivo binario temporal creado en {temp_bin_path}. Convirtiendo a miniSEED...")

        # 7. Ejecutar binary_to_mseed.py modo 3 (--file) sobre el archivo temporal
        binary_to_mseed_script = os.path.join(operation_dir, "mseed", "binary_to_mseed.py")
        venv_python = os.path.join(project_local_root, ".venv", "bin", "python3")

        if not os.path.exists(venv_python):
            _log("error", f"[EVENT_EXTRACTOR] No se encontró el Python del venv en {venv_python}")
            try:
                os.remove(temp_bin_path)
            except OSError:
                pass
            return None

        cmd_convert = [
            venv_python,
            binary_to_mseed_script,
            "--file", temp_bin_path
        ]

        _log("info", f"[EVENT_EXTRACTOR] Ejecutando: {' '.join(cmd_convert)}")
        resultado_conversion = subprocess.run(
            cmd_convert,
            capture_output=True,
            text=True,
            timeout=120
        )

        # Borrar el archivo temporal binario .dat de inmediato
        try:
            os.remove(temp_bin_path)
            _log("debug", f"[EVENT_EXTRACTOR] Archivo binario temporal {temp_bin_path} eliminado")
        except Exception as e:
            _log("warning", f"[EVENT_EXTRACTOR] No se pudo eliminar archivo binario temporal {temp_bin_path}: {e}")

        if resultado_conversion.returncode != 0:
            _log("error", f"[EVENT_EXTRACTOR] binary_to_mseed.py falló (código {resultado_conversion.returncode}): {resultado_conversion.stderr}")
            return None

        # Parsear stdout de binary_to_mseed.py para obtener la ruta del mseed generado
        mseed_generado_path = None
        for line in resultado_conversion.stdout.splitlines():
            match = re.search(r'output\s*:\s*(.+\.mseed)', line)
            if match:
                mseed_generado_path = match.group(1).strip()
                break

        if not mseed_generado_path or not os.path.exists(mseed_generado_path):
            _log("error", f"[EVENT_EXTRACTOR] No se pudo determinar el archivo mseed generado o el archivo no existe. stdout: {resultado_conversion.stdout}")
            return None

        # 8. Mover el archivo .mseed generado a la carpeta de eventos extraídos
        mseed_filename = os.path.basename(mseed_generado_path)
        mseed_destino_path = os.path.join(path_eventos_extraidos, mseed_filename)

        _log("info", f"[EVENT_EXTRACTOR] Moviendo {mseed_generado_path} a {mseed_destino_path}")
        shutil.move(mseed_generado_path, mseed_destino_path)

        return mseed_destino_path

    except Exception as e:
        _log("error", f"[EVENT_EXTRACTOR] Error durante extracción desde ring buffer: {e}")
        import traceback
        _log("error", traceback.format_exc())
        return None


# ============================================================================
# FUNCIÓN PRINCIPAL DEL MÓDULO
# ============================================================================

def extraer_y_subir_evento(
    start: str,
    duration: float,
    upload: bool = True,
    delete_after_upload: bool = False,
    logger=None
) -> dict:
    """
    Orquesta la extracción de un segmento miniSEED y su subida opcional a Drive.

    Ejecuta:
      1. extract_segment.py  →  usando el Python del venv (.venv/bin/python3)
      2. subir_archivo.py    →  usando el Python del sistema (sys.executable)

    Args:
        start:                Tiempo de inicio en formato ISO UTC con 'Z'
                              (ej: "2026-05-10Z14:30:45.250")
        duration:             Duración en segundos (float)
        upload:               Si True, sube el archivo extraído a Drive
        delete_after_upload:  Si True, borra el archivo local tras subida exitosa
        logger:               Instancia de StructuredLogger (opcional)

    Returns:
        dict con los campos:
            status:       "completed" | "error"
            output_file:  Nombre del archivo generado (si exitoso)
            uploaded:     bool indicando si se subió a Drive
            phase:        "extraction" | "upload" | "pipeline" (solo en error)
            message:      Descripción del resultado
    """
    import time

    def _log(level: str, msg: str):
        if logger:
            if hasattr(logger, level):
                getattr(logger, level)(msg)
            elif hasattr(logger, "info"):
                logger.info(f"[{level.upper()}] {msg}")

    # ------------------------------------------------------------------
    # Espera preventiva en tiempo real (si la ventana termina en el futuro)
    # ------------------------------------------------------------------
    time_str = start.replace('Z', ' ').replace('T', ' ').strip()
    try:
        start_dt = datetime.strptime(time_str, "%Y-%m-%d %H:%M:%S.%f")
    except ValueError:
        try:
            start_dt = datetime.strptime(time_str, "%Y-%m-%d %H:%M:%S")
        except ValueError:
            start_dt = None

    if start_dt is not None:
        end_dt = start_dt + timedelta(seconds=duration)
        ahora_utc = datetime.utcnow()
        segundos_restantes = (end_dt - ahora_utc).total_seconds()
        
        if segundos_restantes > 0:
            margen_seguridad = 3.0
            tiempo_espera = segundos_restantes + margen_seguridad
            # Limitar la espera máxima por seguridad
            limite_espera = duration + 10.0
            if tiempo_espera > limite_espera:
                tiempo_espera = limite_espera
                
            _log("info", f"[EVENT_EXTRACTOR] El rango solicitado finaliza en el futuro real. "
                         f"Esperando {tiempo_espera:.1f} segundos a que se completen los datos en adquisición...")
            time.sleep(tiempo_espera)

    # ------------------------------------------------------------------
    # Resolver rutas
    # ------------------------------------------------------------------
    try:
        rutas = _resolver_rutas()
    except (EnvironmentError, FileNotFoundError) as e:
        _log("error", f"[EVENT_EXTRACTOR] Error de configuración: {e}")
        return {
            "status": "error",
            "output_file": None,
            "uploaded": False,
            "phase": "pipeline",
            "source": "mseed_archive",
            "message": str(e)
        }

    # ------------------------------------------------------------------
    # Fase 0: Intentar extracción desde ring buffer (más rápida)
    # ------------------------------------------------------------------
    ring_result_path = _intentar_extraer_desde_ring_buffer(start, duration, logger)
    source = "mseed_archive"  # Por defecto fallback
    output_file = None

    if ring_result_path is not None:
        output_file = os.path.basename(ring_result_path)
        source = "ring_buffer"
        _log("info", f"[EVENT_EXTRACTOR] Extracción desde ring buffer exitosa → {output_file}")
    else:
        # ------------------------------------------------------------------
        # Fase 1: Extracción tradicional
        # ------------------------------------------------------------------
        _log("info", f"[EVENT_EXTRACTOR] Iniciando extracción desde mseed horarios → start={start}, duration={duration}s")

        cmd_extract = [
            rutas["venv_python"],
            rutas["extract_script"],
            "--start", start,
            "--duration", str(duration)
        ]

        try:
            resultado_extraccion = subprocess.run(
                cmd_extract,
                capture_output=True,
                text=True,
                timeout=180  # 3 minutos máximo
            )
        except subprocess.TimeoutExpired:
            msg = "Timeout durante la extracción del segmento (>180s)"
            _log("error", f"[EVENT_EXTRACTOR] {msg}")
            return {
                "status": "error",
                "output_file": None,
                "uploaded": False,
                "phase": "extraction",
                "source": "mseed_archive",
                "message": msg
            }
        except Exception as e:
            msg = f"Error inesperado al ejecutar extract_segment.py: {e}"
            _log("error", f"[EVENT_EXTRACTOR] {msg}")
            return {
                "status": "error",
                "output_file": None,
                "uploaded": False,
                "phase": "extraction",
                "source": "mseed_archive",
                "message": msg
            }

        # Verificar código de retorno
        if resultado_extraccion.returncode != 0:
            stderr_msg = resultado_extraccion.stderr.strip().splitlines()[-1] if resultado_extraccion.stderr else "sin detalle"
            msg = f"extract_segment.py falló (código {resultado_extraccion.returncode}): {stderr_msg}"
            _log("error", f"[EVENT_EXTRACTOR] {msg}")
            return {
                "status": "error",
                "output_file": None,
                "uploaded": False,
                "phase": "extraction",
                "source": "mseed_archive",
                "message": msg
            }

        # Obtener nombre del archivo generado
        output_file = _parsear_archivo_generado(resultado_extraccion.stdout)
        if not output_file:
            msg = "No se pudo determinar el nombre del archivo extraído desde el stdout"
            _log("error", f"[EVENT_EXTRACTOR] {msg}")
            _log("error", f"[EVENT_EXTRACTOR] stdout completo: {resultado_extraccion.stdout}")
            return {
                "status": "error",
                "output_file": None,
                "uploaded": False,
                "phase": "extraction",
                "source": "mseed_archive",
                "message": msg
            }

        _log("info", f"[EVENT_EXTRACTOR] Extracción exitosa → archivo: {output_file}")

    # ------------------------------------------------------------------
    # Fase 2: Subida a Drive (opcional)
    # ------------------------------------------------------------------
    uploaded = False

    if upload:
        _log("info", f"[EVENT_EXTRACTOR] Iniciando subida a Drive → {output_file}")

        cmd_upload = [
            sys.executable,          # Python del sistema (el mismo del coordinador)
            rutas["upload_script"],
            "--event", output_file
        ]
        if delete_after_upload:
            cmd_upload.append("--delete")

        try:
            resultado_subida = subprocess.run(
                cmd_upload,
                capture_output=True,
                text=True,
                timeout=600  # 10 minutos máximo (archivos grandes, red lenta)
            )
        except subprocess.TimeoutExpired:
            msg = f"Timeout durante la subida a Drive del archivo {output_file} (>600s)"
            _log("error", f"[EVENT_EXTRACTOR] {msg}")
            return {
                "status": "error",
                "output_file": output_file,
                "uploaded": False,
                "phase": "upload",
                "source": source,
                "message": msg
            }
        except Exception as e:
            msg = f"Error inesperado al ejecutar subir_archivo.py: {e}"
            _log("error", f"[EVENT_EXTRACTOR] {msg}")
            return {
                "status": "error",
                "output_file": output_file,
                "uploaded": False,
                "phase": "upload",
                "source": source,
                "message": msg
            }

        if resultado_subida.returncode != 0:
            stderr_msg = resultado_subida.stderr.strip().splitlines()[-1] if resultado_subida.stderr else "sin detalle"
            msg = f"subir_archivo.py falló (código {resultado_subida.returncode}): {stderr_msg}"
            _log("error", f"[EVENT_EXTRACTOR] {msg}")
            return {
                "status": "error",
                "output_file": output_file,
                "uploaded": False,
                "phase": "upload",
                "source": source,
                "message": msg
            }

        uploaded = True
        _log("info", f"[EVENT_EXTRACTOR] Subida exitosa → {output_file}")

    # ------------------------------------------------------------------
    # Resultado final
    # ------------------------------------------------------------------
    msg_partes = [f"Segmento extraído: {output_file}"]
    if upload:
        msg_partes.append("subido a Drive" if uploaded else "subida omitida por error")
    if delete_after_upload and uploaded:
        msg_partes.append("archivo local eliminado")

    return {
        "status": "completed",
        "output_file": output_file,
        "uploaded": uploaded,
        "phase": None,
        "source": source,
        "message": "; ".join(msg_partes)
    }

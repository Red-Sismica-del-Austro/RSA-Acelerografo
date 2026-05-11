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

    def _log(level: str, msg: str):
        if logger:
            getattr(logger, level)(msg)

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
            "message": str(e)
        }

    # ------------------------------------------------------------------
    # Fase 1: Extracción
    # ------------------------------------------------------------------
    _log("info", f"[EVENT_EXTRACTOR] Iniciando extracción → start={start}, duration={duration}s")

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
        "message": "; ".join(msg_partes)
    }

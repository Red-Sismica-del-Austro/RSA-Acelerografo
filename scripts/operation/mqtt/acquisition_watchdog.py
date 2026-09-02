"""
acquisition_watchdog.py — Monitor de latencia y salud de adquisición para el Acelerógrafo RSA.

Audita periódicamente el Ring Buffer en disco para determinar la frescura de los datos
adquiridos. Si la última trama tiene una antigüedad superior al umbral (default: 300 s),
genera una alerta de estancamiento para su publicación en el broker MQTT.

Payloads emitidos:
- Estado nominal (status='ok'):
    {
        "status": "ok",
        "last_frame_utc": "2026-09-02T15:30:01Z",
        "age_seconds": 2.1,
        "station_id": "DEV0",
        "timestamp": "2026-09-02T15:30:03Z"
    }
- Alerta por datos estancados (status='warning'):
    {
        "status": "warning",
        "reason": "stale_data",
        "last_frame_utc": "2026-08-27T19:46:03Z",
        "age_seconds": 432000.0,
        "threshold_seconds": 300,
        "station_id": "DEV0",
        "timestamp": "2026-09-01T10:48:00Z"
    }
- Error de disponibilidad (status='error'):
    {
        "status": "error",
        "reason": "ring_buffer_dir_not_found" | "no_data_available",
        "station_id": "DEV0",
        "timestamp": "2026-09-02T15:30:03Z"
    }
"""

import os
import sys
import glob
import logging
from datetime import datetime, timezone
from typing import Optional, Dict, Any

# Agregar el directorio scripts/operation al path para importar módulos core
_OPERATION_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _OPERATION_DIR not in sys.path:
    sys.path.insert(0, _OPERATION_DIR)

from core.frame_decoder import FRAME_SIZE, decode_timestamp

DEFAULT_RING_DIR = "/home/rsa/data/ring-buffer/"
DEFAULT_CHECK_INTERVAL_S = 60
DEFAULT_STALE_THRESHOLD_S = 300  # 5 minutos


class AcquisitionWatchdog:
    """
    Monitor de latencia de adquisición que inspecciona el Ring Buffer en disco.
    """

    def __init__(
        self,
        ring_dir: str = DEFAULT_RING_DIR,
        stale_threshold_s: float = DEFAULT_STALE_THRESHOLD_S,
        usar_fecha_filename: bool = True,
        logger: Optional[Any] = None,
    ):
        """
        Args:
            ring_dir:           Ruta al directorio de archivos .bin del Ring Buffer.
            stale_threshold_s:  Umbral en segundos para considerar estancada la adquisición.
            usar_fecha_filename: Si True, mitiga bugs de fecha usando el nombre de archivo.
            logger:             Instancia de StructuredLogger o logging.Logger.
        """
        self.ring_dir = ring_dir
        self.stale_threshold_s = stale_threshold_s
        self.usar_fecha_filename = usar_fecha_filename
        self.logger = logger or logging.getLogger(__name__)

    def obtener_ultima_trama_timestamp(self) -> Optional[datetime]:
        """
        Lee el timestamp de la última trama válida almacenada en el Ring Buffer.

        Busca en orden cronológico inverso desde el archivo más reciente.

        Returns:
            datetime en UTC de la última trama, o None si no hay datos disponibles.
        """
        if not os.path.isdir(self.ring_dir):
            return None

        archivos = sorted(glob.glob(os.path.join(self.ring_dir, "ring_*.bin")))
        if not archivos:
            return None

        # Revisar desde el último archivo hacia atrás por robustez
        for filepath in reversed(archivos):
            try:
                size = os.path.getsize(filepath)
                if size < FRAME_SIZE:
                    continue

                frame_count = size // FRAME_SIZE
                with open(filepath, "rb") as f:
                    f.seek((frame_count - 1) * FRAME_SIZE)
                    raw = f.read(FRAME_SIZE)
                    if len(raw) < FRAME_SIZE:
                        continue

                filename = os.path.basename(filepath)
                ts = decode_timestamp(
                    raw,
                    usar_fecha_filename=self.usar_fecha_filename,
                    filename=filename,
                )

                # Asegurar objeto timezone-aware en UTC
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=timezone.utc)

                return ts
            except Exception as e:
                if self.logger:
                    self.logger.warning(
                        f"[WATCHDOG] Error leyendo última trama de {filepath}: {e}"
                    )
                continue

        return None

    def evaluar_salud(
        self,
        station_id: str,
        now_utc: Optional[datetime] = None
    ) -> Dict[str, Any]:
        """
        Evalúa el estado de la adquisición y retorna el payload estructurado para MQTT.

        Args:
            station_id: Identificador de la estación (ej. 'DEV0').
            now_utc:    Timestamp de referencia para la auditoría (default: datetime actual UTC).

        Returns:
            Dict con los campos del estado de adquisición.
        """
        if now_utc is None:
            now_utc = datetime.now(timezone.utc)
        elif now_utc.tzinfo is None:
            now_utc = now_utc.replace(tzinfo=timezone.utc)

        ts_iso = now_utc.strftime("%Y-%m-%dT%H:%M:%SZ")

        if not os.path.isdir(self.ring_dir):
            return {
                "status": "error",
                "reason": "ring_buffer_dir_not_found",
                "station_id": station_id,
                "timestamp": ts_iso,
            }

        last_ts = self.obtener_ultima_trama_timestamp()
        if last_ts is None:
            return {
                "status": "error",
                "reason": "no_data_available",
                "station_id": station_id,
                "timestamp": ts_iso,
            }

        age_seconds = max(0.0, (now_utc - last_ts).total_seconds())
        last_frame_iso = last_ts.strftime("%Y-%m-%dT%H:%M:%SZ")

        if age_seconds > self.stale_threshold_s:
            return {
                "status": "warning",
                "reason": "stale_data",
                "last_frame_utc": last_frame_iso,
                "age_seconds": round(age_seconds, 1),
                "threshold_seconds": self.stale_threshold_s,
                "station_id": station_id,
                "timestamp": ts_iso,
            }

        return {
            "status": "ok",
            "last_frame_utc": last_frame_iso,
            "age_seconds": round(age_seconds, 1),
            "station_id": station_id,
            "timestamp": ts_iso,
        }

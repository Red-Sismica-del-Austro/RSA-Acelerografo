"""
event_logger.py — Registro CSV thread-safe de detecciones sísmicas GPD.

Módulo compartido entre gpd_stream_worker.py y mqtt_coordinator.py.
Mantiene un archivo CSV mensual en:
    /home/rsa/data/eventos-detectados/YYYY-MM_detecciones.csv

Cada fila representa una detección (o evento externo) con su estado de
confirmación. El acceso concurrente desde múltiples hilos está serializado
mediante un threading.Lock.

Columnas del CSV:
    timestamp_centro  — ISO8601 UTC del centro de la ventana evaluada por GPD
    fase              — "P", "S", "EXTERNAL" o "N/A"
    probabilidad      — float [0.0, 1.0] (0.0 para eventos externos)
    timestamp_local   — ISO8601 UTC del momento de grabación en el sistema
    confirmado        — bool: True si fue validado/extraído, False si pendiente
    archivo_mseed     — nombre del archivo MiniSEED generado (vacío si no extraído)
    metodo            — "local_gpd" (detección propia) o "network_cmd" (comando regional)

Dependencias: stdlib únicamente (csv, os, threading, datetime).
"""

import csv
import os
import shutil
import tempfile
import threading
from datetime import datetime, timezone
from typing import Optional


# ---------------------------------------------------------------------------
# Constantes
# ---------------------------------------------------------------------------

DEFAULT_CSV_DIR = "/home/rsa/data/eventos-detectados"

CSV_HEADERS = [
    "timestamp_centro",
    "fase",
    "probabilidad",
    "timestamp_local",
    "confirmado",
    "archivo_mseed",
    "metodo",
]


# ---------------------------------------------------------------------------
# Clase principal
# ---------------------------------------------------------------------------

class EventLogger:
    """
    Registra detecciones sísmicas GPD en un CSV mensual thread-safe.

    Uso básico:
        logger = EventLogger(csv_dir="/home/rsa/data/eventos-detectados")

        # Al detectar una fase (worker GPD):
        logger.registrar_deteccion(
            timestamp_centro="2026-07-06T15:30:00.000Z",
            fase="P",
            probabilidad=0.9854,
        )

        # Al confirmar la extracción (mqtt_coordinator):
        logger.actualizar_confirmacion(
            timestamp_centro="2026-07-06T15:30:00.000Z",
            confirmado=True,
            archivo_mseed="DEV00_260706-153000.mseed",
        )

        # Al recibir un comando de red sin detección local previa:
        logger.registrar_evento_externo(
            timestamp_centro="2026-07-06T16:45:12.000Z",
            archivo_mseed="DEV00_260706-164512.mseed",
        )
    """

    def __init__(self, csv_dir: str = DEFAULT_CSV_DIR, logger=None):
        """
        Inicializa el EventLogger.

        Args:
            csv_dir: Directorio donde se almacenan los CSVs mensuales.
                     Se crea automáticamente si no existe.
            logger:  Instancia de StructuredLogger (o compatible con .info/.warning/.error).
                     Si es None, los mensajes internos se silencian.
        """
        self._csv_dir = csv_dir
        self._logger = logger
        self._lock = threading.Lock()

    # -----------------------------------------------------------------------
    # API pública
    # -----------------------------------------------------------------------

    def registrar_deteccion(
        self,
        timestamp_centro: str,
        fase: str,
        probabilidad: float,
        confirmado: bool = False,
        archivo_mseed: str = "",
        metodo: str = "local_gpd",
    ) -> None:
        """
        Agrega una nueva fila al CSV mensual correspondiente al timestamp_centro.

        Crea el directorio y el archivo (con headers) si no existen.
        La operación es atómica desde el punto de vista del lock: ningún otro
        hilo puede leer o escribir el CSV durante la operación.

        Args:
            timestamp_centro: ISO8601 UTC del centro de la ventana evaluada por GPD.
                              Ejemplo: "2026-07-06T15:30:00.000Z"
            fase:             Tipo de fase detectada: "P", "S", "EXTERNAL" o "N/A".
            probabilidad:     Probabilidad asignada por el modelo [0.0, 1.0].
            confirmado:       True si la detección ya fue validada/extraída.
                              Por defecto False (pendiente de confirmación).
            archivo_mseed:    Nombre del archivo MiniSEED (sin ruta). Vacío si aún
                              no se ha extraído el evento.
            metodo:           "local_gpd" para detecciones propias,
                              "network_cmd" para comandos de red.
        """
        timestamp_local = _iso_now()
        csv_path = self._csv_path_from_iso(timestamp_centro)

        with self._lock:
            try:
                os.makedirs(self._csv_dir, exist_ok=True)
                archivo_existe = os.path.isfile(csv_path)

                with open(csv_path, "a", newline="", encoding="utf-8") as f:
                    writer = csv.DictWriter(f, fieldnames=CSV_HEADERS)
                    if not archivo_existe:
                        writer.writeheader()
                    writer.writerow({
                        "timestamp_centro": timestamp_centro,
                        "fase": fase,
                        "probabilidad": round(float(probabilidad), 4),
                        "timestamp_local": timestamp_local,
                        "confirmado": str(confirmado),
                        "archivo_mseed": archivo_mseed,
                        "metodo": metodo,
                    })

                if self._logger:
                    self._logger.info(
                        f"[EVENT_LOGGER] Detección registrada — "
                        f"fase={fase} prob={probabilidad:.4f} ts={timestamp_centro} "
                        f"csv={os.path.basename(csv_path)}"
                    )

            except OSError as exc:
                if self._logger:
                    self._logger.error(
                        f"[EVENT_LOGGER] Error al registrar detección en {csv_path}: {exc}"
                    )

    def actualizar_confirmacion(
        self,
        timestamp_centro: str,
        confirmado: bool = True,
        archivo_mseed: str = "",
    ) -> bool:
        """
        Busca un registro por timestamp_centro y actualiza 'confirmado' y 'archivo_mseed'.

        Lee el CSV completo del mes correspondiente, modifica la primera fila que
        coincida con timestamp_centro, y reescribe el archivo atómicamente (usando
        un fichero temporal para evitar pérdidas ante un crash).

        Args:
            timestamp_centro: ISO8601 UTC a buscar (debe coincidir exactamente).
            confirmado:       Nuevo valor del campo 'confirmado'.
            archivo_mseed:    Nuevo valor del campo 'archivo_mseed'.

        Returns:
            True  — si se encontró y actualizó al menos un registro.
            False — si no se encontró ningún registro con ese timestamp_centro.
        """
        csv_path = self._csv_path_from_iso(timestamp_centro)

        with self._lock:
            if not os.path.isfile(csv_path):
                if self._logger:
                    self._logger.warning(
                        f"[EVENT_LOGGER] CSV no encontrado para actualizar: {csv_path}"
                    )
                return False

            try:
                filas = []
                encontrado = False

                with open(csv_path, "r", newline="", encoding="utf-8") as f:
                    reader = csv.DictReader(f)
                    for fila in reader:
                        if fila["timestamp_centro"] == timestamp_centro and not encontrado:
                            # Actualizar primera coincidencia
                            fila["confirmado"] = str(confirmado)
                            if archivo_mseed:
                                fila["archivo_mseed"] = archivo_mseed
                            encontrado = True
                        filas.append(fila)

                if not encontrado:
                    if self._logger:
                        self._logger.warning(
                            f"[EVENT_LOGGER] No se encontró registro con "
                            f"timestamp_centro={timestamp_centro} en {os.path.basename(csv_path)}"
                        )
                    return False

                # Reescritura atómica usando fichero temporal en el mismo directorio
                fd, tmp_path = tempfile.mkstemp(dir=self._csv_dir, suffix=".tmp")
                try:
                    with os.fdopen(fd, "w", newline="", encoding="utf-8") as f:
                        writer = csv.DictWriter(f, fieldnames=CSV_HEADERS)
                        writer.writeheader()
                        writer.writerows(filas)
                    shutil.move(tmp_path, csv_path)
                except Exception:
                    # Limpiar el temporal si algo falló
                    try:
                        os.unlink(tmp_path)
                    except OSError:
                        pass
                    raise

                if self._logger:
                    self._logger.info(
                        f"[EVENT_LOGGER] Confirmación actualizada — "
                        f"ts={timestamp_centro} confirmado={confirmado} "
                        f"archivo={archivo_mseed} csv={os.path.basename(csv_path)}"
                    )

                return True

            except OSError as exc:
                if self._logger:
                    self._logger.error(
                        f"[EVENT_LOGGER] Error al actualizar {csv_path}: {exc}"
                    )
                return False

    def registrar_evento_externo(
        self,
        timestamp_centro: str,
        archivo_mseed: str = "",
    ) -> None:
        """
        Registra un evento disparado por un comando de red externo.

        Crea un registro con:
            fase        = "EXTERNAL"
            probabilidad = 0.0
            confirmado  = True
            metodo      = "network_cmd"

        Usado por mqtt_coordinator cuando recibe un /cmd/extract_event de la red
        y la estación no tiene detección local previa para ese timestamp.

        Args:
            timestamp_centro: ISO8601 UTC del evento (generalmente el 'start'
                              del comando de extracción).
            archivo_mseed:    Nombre del archivo MiniSEED generado.
        """
        self.registrar_deteccion(
            timestamp_centro=timestamp_centro,
            fase="EXTERNAL",
            probabilidad=0.0,
            confirmado=True,
            archivo_mseed=archivo_mseed,
            metodo="network_cmd",
        )

    # -----------------------------------------------------------------------
    # Utilidades internas
    # -----------------------------------------------------------------------

    def _csv_path(self, dt: Optional[datetime] = None) -> str:
        """
        Retorna la ruta del CSV mensual para la fecha dada (o el mes actual).

        Args:
            dt: datetime con timezone. Si es None, usa UTC ahora.

        Returns:
            Ruta absoluta al archivo CSV mensual.
        """
        if dt is None:
            dt = datetime.now(timezone.utc)
        filename = f"{dt.strftime('%Y-%m')}_detecciones.csv"
        return os.path.join(self._csv_dir, filename)

    def _csv_path_from_iso(self, timestamp_iso: str) -> str:
        """
        Deriva la ruta del CSV mensual a partir de un timestamp ISO8601.

        Parsea solo el año y mes del string. Acepta formatos:
            "2026-07-06T15:30:00.000Z"
            "2026-07-06T15:30:00Z"

        Si el formato es inválido, usa el mes UTC actual.

        Args:
            timestamp_iso: Timestamp en formato ISO8601 UTC.

        Returns:
            Ruta absoluta al archivo CSV mensual.
        """
        try:
            # Parsear solo YYYY-MM del inicio del string
            year_month = timestamp_iso[:7]  # "2026-07"
            dt = datetime.strptime(year_month, "%Y-%m").replace(tzinfo=timezone.utc)
        except (ValueError, IndexError):
            if self._logger:
                self._logger.warning(
                    f"[EVENT_LOGGER] Timestamp inválido '{timestamp_iso}'. "
                    "Usando mes UTC actual."
                )
            dt = datetime.now(timezone.utc)

        return self._csv_path(dt)


# ---------------------------------------------------------------------------
# Utilidades de módulo
# ---------------------------------------------------------------------------

def _iso_now() -> str:
    """Retorna el timestamp UTC actual en formato ISO8601 con milisegundos."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"

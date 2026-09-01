"""
ring_buffer_store.py — Almacén de tramas binarias en disco con rotación FIFO.

Mantiene un directorio de archivos .bin rotativos que almacenan tramas crudas
de 2506 bytes del acelerógrafo. Permite consultar tramas por rango temporal
y aplica una política de retención FIFO por tamaño total en disco.

Organización en disco:
    ring_YYYYMMDD_HHMMSS.bin  →  concatenación de tramas de 2506 bytes
    Cada archivo cubre una ventana de tiempo configurable (default: 5 min)
    El directorio se mantiene por debajo de max_size_mb (default: 500 MB ≈ 11 h)

Uso:
    from streaming.ring_buffer_store import RingBufferStore

    store = RingBufferStore(
        directorio="/home/rsa/data/ring-buffer/",
        max_size_mb=500,
        archivo_duracion_s=300
    )

    # Escritura (desde stream_processor)
    store.write_frame(raw_bytes_2506, timestamp)

    # Consulta (desde event_extractor)
    frames = store.query(start_dt, end_dt)         # Lista de FrameData
    raws   = store.query_raw(start_dt, end_dt)     # Lista de bytes crudos

    store.close()

Compatibilidad:
    Los archivos .bin son directamente legibles por binary_to_mseed.py,
    ya que son concatenaciones de tramas de 2506 bytes sin header adicional.
"""

import os
import glob
import time
import threading
import datetime
import logging
from dataclasses import dataclass
from typing import List, Optional, Tuple

import sys
# Agregar el directorio scripts/operation al path para importar módulos del proyecto
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.frame_decoder import (
    FrameData,
    FRAME_SIZE,
    decode_frame,
    decode_timestamp,
)


# ---------------------------------------------------------------------------
# Constantes
# ---------------------------------------------------------------------------

# Patrón de nombre de archivo del ring buffer
_RING_FILE_GLOB = "ring_*.bin"
_RING_FILE_PREFIX = "ring_"
_RING_FILE_EXT = ".bin"
_RING_FILE_FORMAT = "ring_{}{}"  # ring_YYYYMMDD_HHMMSS.bin


# ---------------------------------------------------------------------------
# Estructura del índice en memoria
# ---------------------------------------------------------------------------

@dataclass
class RingFileEntry:
    """Entrada del índice en memoria que describe un archivo .bin del ring buffer."""
    filepath: str           # Ruta absoluta del archivo
    start_time: datetime.datetime  # Timestamp de la primera trama
    end_time: datetime.datetime    # Timestamp de la última trama
    frame_count: int        # Número de tramas en el archivo
    size_bytes: int         # Tamaño del archivo en bytes


# ---------------------------------------------------------------------------
# Clase principal
# ---------------------------------------------------------------------------

class RingBufferStore:
    """
    Almacén de tramas binarias en disco con rotación FIFO.

    Organización en disco:
    - Archivos de duración configurable (default: 5 min = 300 tramas × 2506B ≈ 752 KB)
    - Naming: ring_{YYYYMMDD}_{HHMMSS}.bin
    - Eliminación FIFO cuando el directorio supera max_size_mb

    Thread-safe: escritura y consultas pueden ejecutarse desde distintos hilos.
    El archivo activo en escritura es siempre el último del índice.

    Compatibilidad con binary_to_mseed.py:
    Los archivos .bin son concatenaciones directas de tramas de 2506 bytes
    sin ningún header adicional. Son directamente legibles por el script
    de conversión si se requiere recuperar datos de forma manual.
    """

    def __init__(
        self,
        directorio: str,
        max_size_mb: int = 500,
        archivo_duracion_s: int = 300,
        usar_fecha_filename: bool = True,
        logger=None
    ):
        """
        Args:
            directorio:         Ruta del directorio para archivos del ring buffer.
                                Se crea automáticamente si no existe.
            max_size_mb:        Tamaño máximo en MB antes de aplicar eliminación FIFO.
                                Default 500 MB ≈ 11 horas de datos continuos.
            archivo_duracion_s: Segundos de datos por archivo antes de rotar.
                                Default 300 s = 5 minutos.
            usar_fecha_filename: Si True (default), extrae la fecha del nombre del archivo
                                 al reconstruir el índice (mitigación del bug de fecha del dsPIC).
            logger:             Instancia de StructuredLogger del proyecto. Opcional;
                                si no se provee, se usará logging estándar.
        """
        self._directorio = os.path.abspath(directorio)
        self._max_size_bytes = max_size_mb * 1024 * 1024
        self._archivo_duracion_s = archivo_duracion_s
        self._usar_fecha_filename = usar_fecha_filename
        self._logger = logger

        # Estado del archivo activo en escritura
        self._archivo_activo: Optional[object] = None   # file handle
        self._archivo_activo_path: Optional[str] = None
        self._archivo_activo_inicio: Optional[datetime.datetime] = None
        self._archivo_activo_inicio_mono: Optional[float] = None  # time.monotonic() al abrir
        self._archivo_activo_frame_count: int = 0

        # Índice en memoria (lista ordenada por start_time)
        self._index: List[RingFileEntry] = []

        # Mutex para todas las operaciones sobre el índice y el archivo activo
        self._lock = threading.Lock()

        # Inicialización
        self._init_directorio()
        self._rebuild_index()

    # -----------------------------------------------------------------------
    # API pública — Escritura
    # -----------------------------------------------------------------------

    def write_frame(self, raw_frame: bytes, timestamp: datetime.datetime) -> None:
        """
        Escribe una trama cruda de 2506 bytes al archivo activo del ring buffer.

        Rota automáticamente el archivo si se alcanza archivo_duracion_s desde
        el inicio del archivo actual. Aplica la política de retención FIFO si
        el tamaño total supera max_size_mb.

        Args:
            raw_frame:  Exactamente FRAME_SIZE (2506) bytes crudos del pipe o sensor.
            timestamp:  Timestamp de la trama (para naming del archivo y el índice).

        Raises:
            ValueError: Si len(raw_frame) != FRAME_SIZE.
            IOError:    Si no se puede escribir en el archivo activo.
        """
        if len(raw_frame) != FRAME_SIZE:
            raise ValueError(
                f"Se requieren exactamente {FRAME_SIZE} bytes por trama, "
                f"recibidos: {len(raw_frame)}"
            )

        with self._lock:
            # Verificar si debe rotar el archivo
            if self._debe_rotar(timestamp):
                self._rotate_file(timestamp)

            # Escribir trama al archivo activo
            self._archivo_activo.write(raw_frame)
            self._archivo_activo.flush()
            self._archivo_activo_frame_count += 1

            # Actualizar la entrada del índice para el archivo activo
            if self._index:
                entry = self._index[-1]
                entry.end_time = timestamp
                entry.frame_count = self._archivo_activo_frame_count
                entry.size_bytes += FRAME_SIZE

        # Verificar retención fuera del lock para minimizar tiempo de bloqueo
        with self._lock:
            self._enforce_retention()

    # -----------------------------------------------------------------------
    # API pública — Consulta
    # -----------------------------------------------------------------------

    def query(
        self,
        start: datetime.datetime,
        end: datetime.datetime
    ) -> List[FrameData]:
        """
        Consulta tramas decodificadas en un rango temporal [start, end].

        Decodifica cada trama cruda usando frame_decoder.decode_frame().
        Para consultas de gran volumen, considerar query_raw() + decodificación
        diferida para mayor rendimiento.

        Args:
            start: Inicio del rango temporal (inclusivo).
            end:   Fin del rango temporal (inclusivo).

        Returns:
            Lista de FrameData ordenada cronológicamente.
            Lista vacía si el rango no tiene datos disponibles en el buffer.

        Raises:
            ValueError: Si start > end.
        """
        if start > end:
            raise ValueError(f"start ({start}) debe ser <= end ({end})")

        raw_frames = self.query_raw(start, end)
        results: List[FrameData] = []

        for i, raw in enumerate(raw_frames):
            try:
                # Extraer nombre del archivo de la primera trama del bloque
                # para el modo usar_fecha_filename (si está activo)
                frame_data = decode_frame(
                    raw,
                    usar_fecha_filename=False  # En query, los bytes ya tienen fecha correcta
                )
                results.append(frame_data)
            except ValueError as e:
                self._log_warning(f"Trama inválida en consulta (índice {i}): {e}")

        return results

    def query_raw(
        self,
        start: datetime.datetime,
        end: datetime.datetime
    ) -> List[bytes]:
        """
        Consulta tramas crudas (sin decodificar) en un rango temporal [start, end].

        Retorna bloques de FRAME_SIZE bytes directamente legibles por
        binary_to_mseed.py para reconversión a miniSEED.

        Args:
            start: Inicio del rango temporal (inclusivo).
            end:   Fin del rango temporal (inclusivo).

        Returns:
            Lista de bloques de 2506 bytes en orden cronológico.
            Lista vacía si el rango no tiene datos disponibles.

        Raises:
            ValueError: Si start > end.
        """
        if start > end:
            raise ValueError(f"start ({start}) debe ser <= end ({end})")

        results: List[bytes] = []

        with self._lock:
            # Identificar los archivos que se solapan con el rango [start, end]
            archivos_relevantes = [
                entry for entry in self._index
                if entry.start_time <= end and entry.end_time >= start
            ]

        for entry in archivos_relevantes:
            try:
                tramas = self._leer_tramas_en_rango(entry, start, end)
                results.extend(tramas)
            except (IOError, OSError) as e:
                self._log_warning(f"Error leyendo {entry.filepath}: {e}")

        return results

    def get_time_range(self) -> Optional[Tuple[datetime.datetime, datetime.datetime]]:
        """
        Retorna el rango temporal disponible en el ring buffer.

        Returns:
            Tupla (oldest_timestamp, newest_timestamp), o None si el buffer
            está vacío.
        """
        with self._lock:
            if not self._index:
                return None
            oldest = self._index[0].start_time
            newest = self._index[-1].end_time
            return oldest, newest

    def get_disk_usage_mb(self) -> float:
        """
        Retorna el espacio en disco actualmente usado por el ring buffer en MB.

        Returns:
            Uso en MB como número de punto flotante.
        """
        with self._lock:
            total = sum(entry.size_bytes for entry in self._index)
        return total / (1024 * 1024)

    def close(self) -> None:
        """
        Cierra el archivo activo de forma limpia.

        Debe llamarse antes del shutdown del proceso para garantizar
        que el último archivo no quede truncado. Después de cerrar,
        el store no puede recibir más escrituras.
        """
        with self._lock:
            self._cerrar_archivo_activo()
        self._log_info("RingBufferStore cerrado limpiamente.")

    # -----------------------------------------------------------------------
    # Métodos privados — Gestión de archivos
    # -----------------------------------------------------------------------

    def _init_directorio(self) -> None:
        """Crea el directorio del ring buffer si no existe."""
        os.makedirs(self._directorio, exist_ok=True)
        self._log_info(f"Ring buffer directory: {self._directorio}")

    def _debe_rotar(self, timestamp: datetime.datetime) -> bool:
        """
        Determina si el archivo activo debe rotar.

        Retorna True si:
        - No hay archivo activo (primera escritura), o
        - El tiempo real transcurrido desde la apertura supera archivo_duracion_s
          (criterio primario — inmune al bug de fecha del dsPIC en cambio de día), o
        - El timestamp de la trama retrocede respecto al inicio del archivo
          (regresión temporal: indica cruce de día con fecha aún en el día anterior).

        NOTA: Se usa time.monotonic() como criterio primario de rotación en lugar
        del delta entre timestamps de tramas. Esto evita que un timestamp negativo
        (causado por el bug del dsPIC al cruzar medianoche, donde la fecha del día
        sigue siendo la del día anterior mientras la hora ya es 00:00:xx) bloquee
        indefinidamente la rotación.
        """
        if self._archivo_activo is None:
            self._log_debug("[RING_DEBE_ROTAR] True: _archivo_activo es None (primera escritura)")
            return True
        if self._archivo_activo_inicio is None or self._archivo_activo_inicio_mono is None:
            self._log_debug("[RING_DEBE_ROTAR] True: metadata del archivo activo está incompleta")
            return True

        # Criterio 1 (primario): tiempo real transcurrido desde apertura del archivo.
        # Inmune al bug de fecha del dsPIC porque no depende de los timestamps de tramas.
        tiempo_real_s = time.monotonic() - self._archivo_activo_inicio_mono
        if tiempo_real_s >= self._archivo_duracion_s:
            self._log_debug(
                f"[RING_DEBE_ROTAR] True: Criterio 1 (tiempo real). "
                f"Transcurrido: {tiempo_real_s:.1f}s >= Límite: {self._archivo_duracion_s}s"
            )
            return True

        # Criterio 2: regresión temporal explícita.
        # Si el timestamp de la trama es anterior al inicio del archivo activo,
        # significa que hay un problema de fecha (ej. cambio de día con dsPIC aún
        # reportando el día anterior), pero la hora ya avanzó más allá de la duración.
        # En ese caso, verificar también por delta de timestamps como señal secundaria
        # para no rotar innecesariamente ante timestamps idénticos al inicio.
        delta_ts = (timestamp - self._archivo_activo_inicio).total_seconds()
        if delta_ts < 0 and tiempo_real_s >= self._archivo_duracion_s * 0.9:
            self._log_debug(
                f"[RING_DEBE_ROTAR] True: Criterio 2 (regresión temporal). "
                f"delta_ts: {delta_ts:.1f}s, tiempo_real_s: {tiempo_real_s:.1f}s "
                f"(>= {self._archivo_duracion_s * 0.9:.1f}s)"
            )
            # Regresión + tiempo real casi cumplido → rotar
            return True

        return False

    def _rotate_file(self, timestamp: datetime.datetime) -> None:
        """
        Cierra el archivo activo y abre uno nuevo con el timestamp dado.

        El nombre del nuevo archivo es: ring_YYYYMMDD_HHMMSS.bin

        Precondición: debe llamarse dentro del contexto de self._lock.
        """
        old_path = self._archivo_activo_path
        self._cerrar_archivo_activo()

        # Generar nombre del nuevo archivo.
        # Corrección por bug dsPIC en cambio de día: si el timestamp de la trama
        # tiene 1 o más días de atraso respecto al reloj UTC del sistema
        # (cruce de medianoche o días acumulados donde dsPIC aún reporta el día anterior),
        # se usa utcnow() para que el nombre del archivo refleje la fecha real.
        # Para discrepancias menores (datos históricos, tests) se usa el timestamp.
        ahora_utc = datetime.datetime.utcnow()
        diff_dias = (ahora_utc.date() - timestamp.date()).days
        ts_nombre = ahora_utc if diff_dias >= 1 else timestamp
        ts_str = ts_nombre.strftime("%Y%m%d_%H%M%S")
        nombre = f"ring_{ts_str}.bin"
        nuevo_path = os.path.join(self._directorio, nombre)

        # Evitar colisión de nombres (protección ante edge cases)
        if os.path.exists(nuevo_path):
            for i in range(1, 1000):
                nombre_alt = f"ring_{ts_str}_{i:03d}.bin"
                path_alt = os.path.join(self._directorio, nombre_alt)
                if not os.path.exists(path_alt):
                    nuevo_path = path_alt
                    nombre = nombre_alt
                    break

        # Abrir nuevo archivo
        self._archivo_activo = open(nuevo_path, "wb")
        self._archivo_activo_path = nuevo_path
        self._archivo_activo_inicio = timestamp
        self._archivo_activo_inicio_mono = time.monotonic()
        self._archivo_activo_frame_count = 0

        # Agregar al índice
        nueva_entrada = RingFileEntry(
            filepath=nuevo_path,
            start_time=timestamp,
            end_time=timestamp,
            frame_count=0,
            size_bytes=0
        )
        self._index.append(nueva_entrada)

        # Log de rotación
        if old_path:
            self._log_ring_rotate(old_path, nuevo_path)
        else:
            self._log_info(f"[RING_ROTATE] Nuevo archivo: {nombre}")

    def _cerrar_archivo_activo(self) -> None:
        """Cierra el file handle del archivo activo de forma segura."""
        if self._archivo_activo is not None:
            try:
                self._archivo_activo.flush()
                self._archivo_activo.close()
            except OSError:
                pass
            finally:
                self._archivo_activo = None
                self._archivo_activo_path = None
                self._archivo_activo_inicio = None
                self._archivo_activo_inicio_mono = None

    def _enforce_retention(self) -> None:
        """
        Aplica la política de retención FIFO por tamaño.

        Elimina los archivos más antiguos del índice hasta que el tamaño
        total del directorio esté por debajo de max_size_bytes.

        Precondición: debe llamarse dentro del contexto de self._lock o
        de forma que el índice esté protegido.
        """
        # Evitar eliminar el archivo activo en escritura
        archivos_eliminados = 0
        bytes_liberados = 0

        while True:
            total_bytes = sum(e.size_bytes for e in self._index)
            if total_bytes <= self._max_size_bytes:
                break
            if len(self._index) <= 1:
                # No eliminar el único archivo (podría ser el activo)
                break

            # El archivo más antiguo es el primero
            entrada_antigua = self._index[0]

            # No eliminar el archivo activo (último del índice)
            if entrada_antigua.filepath == self._archivo_activo_path:
                break

            try:
                os.remove(entrada_antigua.filepath)
                bytes_liberados += entrada_antigua.size_bytes
                archivos_eliminados += 1
            except OSError as e:
                self._log_warning(f"Error eliminando {entrada_antigua.filepath}: {e}")

            # Remover del índice independientemente (el archivo puede ya no existir)
            self._index.pop(0)

        if archivos_eliminados > 0:
            self._log_ring_cleanup(archivos_eliminados, bytes_liberados / (1024 * 1024))

    def _rebuild_index(self) -> None:
        """
        Reconstruye el índice en memoria escaneando el directorio.

        Se llama al iniciar el servicio para recuperar el estado del ring buffer
        de una ejecución anterior. Escanea todos los archivos ring_*.bin y extrae
        sus rangos temporales leyendo la primera y última trama de cada uno.

        Los archivos con menos de FRAME_SIZE bytes son descartados (incompletos).
        """
        archivos = sorted(
            glob.glob(os.path.join(self._directorio, _RING_FILE_GLOB))
        )

        indice_recuperado: List[RingFileEntry] = []

        for filepath in archivos:
            try:
                entry = self._leer_metadata_archivo(filepath)
                if entry is not None:
                    indice_recuperado.append(entry)
            except Exception as e:
                self._log_warning(f"Error leyendo metadata de {filepath}: {e}")

        with self._lock:
            self._index = indice_recuperado

            # Reanudar escritura en el último archivo en modo append si existe
            if indice_recuperado:
                ultimo = indice_recuperado[-1]
                try:
                    self._archivo_activo = open(ultimo.filepath, "ab")
                    self._archivo_activo_path = ultimo.filepath
                    self._archivo_activo_inicio = ultimo.start_time
                    self._archivo_activo_inicio_mono = time.monotonic()
                    self._archivo_activo_frame_count = ultimo.frame_count
                    self._log_info(
                        f"[RING_REBUILD] Reanudando escritura en archivo activo: "
                        f"{os.path.basename(ultimo.filepath)} con {ultimo.frame_count} tramas."
                    )
                except Exception as e:
                    self._log_warning(
                        f"No se pudo abrir el último archivo {ultimo.filepath} "
                        f"para reanudación: {e}"
                    )

        if indice_recuperado:
            oldest = indice_recuperado[0].start_time
            newest = indice_recuperado[-1].end_time
            self._log_info(
                f"[RING_REBUILD] Índice reconstruido: {len(indice_recuperado)} archivos, "
                f"rango {oldest.strftime('%Y-%m-%d %H:%M:%S')} → "
                f"{newest.strftime('%Y-%m-%d %H:%M:%S')}"
            )
        else:
            self._log_info("[RING_REBUILD] Directorio vacío, sin archivos previos.")

    def _leer_metadata_archivo(self, filepath: str) -> Optional[RingFileEntry]:
        """
        Extrae los metadatos de un archivo .bin leyendo la primera y última trama.

        Args:
            filepath: Ruta absoluta del archivo .bin.

        Returns:
            RingFileEntry con los metadatos, o None si el archivo es inválido.
        """
        size_bytes = os.path.getsize(filepath)
        if size_bytes < FRAME_SIZE:
            return None

        frame_count = size_bytes // FRAME_SIZE
        filename = os.path.basename(filepath)

        with open(filepath, "rb") as f:
            # Leer primera trama
            primera = f.read(FRAME_SIZE)
            if len(primera) < FRAME_SIZE:
                return None

            # Leer última trama
            if frame_count > 1:
                f.seek((frame_count - 1) * FRAME_SIZE)
                ultima = f.read(FRAME_SIZE)
                if len(ultima) < FRAME_SIZE:
                    ultima = primera
            else:
                ultima = primera

        try:
            ts_inicio = decode_timestamp(
                primera,
                usar_fecha_filename=self._usar_fecha_filename,
                filename=filename
            )
            ts_final = decode_timestamp(
                ultima,
                usar_fecha_filename=self._usar_fecha_filename,
                filename=filename
            )
        except ValueError:
            # Si el timestamp es inválido, omitir este archivo
            return None

        return RingFileEntry(
            filepath=filepath,
            start_time=ts_inicio,
            end_time=ts_final,
            frame_count=frame_count,
            size_bytes=size_bytes
        )

    def _leer_tramas_en_rango(
        self,
        entry: RingFileEntry,
        start: datetime.datetime,
        end: datetime.datetime
    ) -> List[bytes]:
        """
        Lee las tramas de un archivo .bin que caen dentro del rango [start, end].

        Evalúa el timestamp de cada trama y filtra las que están dentro del rango.
        Solo lee tramas completas (múltiplos de FRAME_SIZE).

        Args:
            entry:  Entrada del índice con la ruta del archivo.
            start:  Inicio del rango (inclusivo).
            end:    Fin del rango (inclusivo).

        Returns:
            Lista de bloques de FRAME_SIZE bytes en orden cronológico.
        """
        resultados: List[bytes] = []
        filename = os.path.basename(entry.filepath)

        with open(entry.filepath, "rb") as f:
            while True:
                raw = f.read(FRAME_SIZE)
                if len(raw) < FRAME_SIZE:
                    break  # EOF o trama incompleta al final del archivo activo

                try:
                    ts = decode_timestamp(
                        raw,
                        usar_fecha_filename=self._usar_fecha_filename,
                        filename=filename
                    )
                except ValueError:
                    continue  # Trama con timestamp inválido, ignorar

                if ts < start:
                    continue
                if ts > end:
                    break  # Las tramas están ordenadas cronológicamente

                resultados.append(raw)

        return resultados

    # -----------------------------------------------------------------------
    # Métodos de logging (adapta a StructuredLogger o logging estándar)
    # -----------------------------------------------------------------------

    def _log_info(self, msg: str) -> None:
        if self._logger:
            self._logger.info(msg)
        else:
            logging.info(msg)

    def _log_warning(self, msg: str) -> None:
        if self._logger:
            self._logger.warning(msg)
        else:
            logging.warning(msg)

    def _log_debug(self, msg: str) -> None:
        if self._logger:
            self._logger.debug(msg)
        else:
            logging.debug(msg)

    def _log_ring_rotate(self, old_file: str, new_file: str) -> None:
        if self._logger and hasattr(self._logger, "ring_rotate"):
            self._logger.ring_rotate(
                os.path.basename(old_file),
                os.path.basename(new_file)
            )
        else:
            self._log_info(
                f"[RING_ROTATE] {os.path.basename(old_file)} → {os.path.basename(new_file)}"
            )

    def _log_ring_cleanup(self, deleted_count: int, freed_mb: float) -> None:
        if self._logger and hasattr(self._logger, "ring_cleanup"):
            self._logger.ring_cleanup(deleted_count, freed_mb)
        else:
            self._log_info(
                f"[RING_CLEANUP] Eliminados {deleted_count} archivos, "
                f"liberados {freed_mb:.1f} MB"
            )

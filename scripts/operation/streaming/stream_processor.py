"""
stream_processor.py — Daemon de lectura del named pipe al ring buffer.

Lee tramas de 2506 bytes desde /tmp/my_pipe y las almacena en el RingBufferStore
de forma continua. Diseñado para ejecutarse como proceso daemon en la Raspberry Pi.

Comportamiento del pipe:
    El programa C `registro_continuo_4.5.0.c` abre el pipe con O_WRONLY | O_NONBLOCK
    y escribe exactamente 2506 bytes por trama (1 segundo de datos), luego cierra.
    Usando O_RDWR en el lector, el fd permanece abierto y evita el ciclo EOF/close
    que produciría SIGPIPE al escritor.

Uso como daemon:
    python3 stream_processor.py [--pipe /tmp/my_pipe] [--buffer-dir /ruta/ring]
    python3 stream_processor.py --dry-run   # Modo de prueba: cuenta tramas sin guardar

Señales:
    SIGTERM / SIGINT → cierre limpio del ring buffer antes de terminar.

Configuración de log:
    El logger escribe en $PROJECT_LOCAL_ROOT/log-files/stream_processor.log
    con rotación cada 5 MB (máx. 3 backups). Si PROJECT_LOCAL_ROOT no está
    definido, usa el directorio temporal /tmp/rsa-stream-processor.log.
"""

import os
import sys
import signal
import logging
import argparse
import datetime
import time
import threading
from logging.handlers import RotatingFileHandler
from typing import Optional

# ---------------------------------------------------------------------------
# Resolver PROJECT_LOCAL_ROOT antes de importar módulos del proyecto
# ---------------------------------------------------------------------------

# Agregar el directorio scripts/operation al sys.path para importar módulos
_OPERATION_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _OPERATION_DIR not in sys.path:
    sys.path.insert(0, _OPERATION_DIR)

from streaming.ring_buffer_store import RingBufferStore
from core.frame_decoder import FRAME_SIZE, decode_timestamp, validate_timestamp


# ---------------------------------------------------------------------------
# Constantes de configuración
# ---------------------------------------------------------------------------

DEFAULT_PIPE_PATH = "/tmp/my_pipe"
DEFAULT_BUFFER_DIR = "/home/rsa/data/ring-buffer/"
DEFAULT_MAX_SIZE_MB = 500
DEFAULT_ARCHIVO_DURACION_S = 300   # 5 minutos por archivo
DEFAULT_USAR_FECHA_FILENAME = True  # Usa fecha del nombre del archivo (mitiga bug dsPIC)

# Timeout de lectura: si no llegan datos en N segundos, logear una advertencia.
# Con 250 Hz y 1 trama/seg, lo normal es recibir 1 trama por segundo.
READ_TIMEOUT_S = 10

# Log
LOG_FILENAME = "stream_processor.log"
LOG_MAX_BYTES = 5 * 1024 * 1024  # 5 MB
LOG_BACKUP_COUNT = 3


# ---------------------------------------------------------------------------
# Configuración de logging
# ---------------------------------------------------------------------------

def _setup_logger(project_root: Optional[str], verbose: bool) -> logging.Logger:
    """
    Configura el logger del proceso.

    Escribe en $PROJECT_LOCAL_ROOT/log-files/stream_processor.log con rotación.
    Si no está disponible, escribe en /tmp/rsa-stream-processor.log.
    En modo verbose añade un StreamHandler a stdout.

    Args:
        project_root:  Valor de PROJECT_LOCAL_ROOT (puede ser None).
        verbose:       Si True, añade salida a consola.

    Returns:
        Logger configurado con nombre 'stream_processor'.
    """
    if project_root:
        log_dir = os.path.join(project_root, "log-files")
        os.makedirs(log_dir, exist_ok=True)
        log_path = os.path.join(log_dir, LOG_FILENAME)
    else:
        log_path = f"/tmp/rsa-{LOG_FILENAME}"

    logger = logging.getLogger("stream_processor")
    logger.setLevel(logging.DEBUG if verbose else logging.INFO)

    if not logger.handlers:
        fmt = logging.Formatter("%(asctime)s - stream_processor - %(levelname)s - %(message)s")

        fh = RotatingFileHandler(log_path, maxBytes=LOG_MAX_BYTES, backupCount=LOG_BACKUP_COUNT)
        fh.setFormatter(fmt)
        logger.addHandler(fh)

        if verbose:
            ch = logging.StreamHandler(sys.stdout)
            ch.setFormatter(fmt)
            logger.addHandler(ch)

    return logger


# ---------------------------------------------------------------------------
# StreamProcessor
# ---------------------------------------------------------------------------

class StreamProcessor:
    """
    Daemon que lee tramas de 2506 bytes desde el named pipe y las escribe
    al RingBufferStore.

    El pipe se abre con O_RDWR para evitar bloqueos y el ciclo EOF/close
    que produciría el programa C al escribir con O_WRONLY | O_NONBLOCK.

    El procesador mantiene un acumulador interno para manejar correctamente
    lecturas parciales (el kernel puede entregar menos bytes que FRAME_SIZE
    en una sola llamada a os.read()).

    Atributos públicos (solo lectura):
        frames_procesados:  Número total de tramas escritas al ring buffer.
        frames_invalidos:   Número total de tramas descartadas por timestamp inválido.
        frames_error:       Número total de tramas con error de lectura/decodificación.
    """

    def __init__(
        self,
        pipe_path: str = DEFAULT_PIPE_PATH,
        buffer_dir: str = DEFAULT_BUFFER_DIR,
        max_size_mb: int = DEFAULT_MAX_SIZE_MB,
        archivo_duracion_s: int = DEFAULT_ARCHIVO_DURACION_S,
        usar_fecha_filename: bool = DEFAULT_USAR_FECHA_FILENAME,
        dry_run: bool = False,
        logger: Optional[logging.Logger] = None,
    ):
        """
        Args:
            pipe_path:           Ruta al named pipe (FIFO). Default: /tmp/my_pipe.
            buffer_dir:          Directorio del ring buffer en disco.
            max_size_mb:         Tamaño máximo del ring buffer en MB.
            archivo_duracion_s:  Segundos de datos por archivo del ring buffer.
            usar_fecha_filename: Si True, extrae la fecha del nombre de archivo
                                 al escribir en el ring buffer (mitiga bug dsPIC).
            dry_run:             Si True, lee del pipe pero NO escribe al buffer.
                                 Útil para diagnóstico y pruebas.
            logger:              Logger externo. Si None, usa logging.getLogger(__name__).
        """
        self._pipe_path = pipe_path
        self._buffer_dir = buffer_dir
        self._max_size_mb = max_size_mb
        self._archivo_duracion_s = archivo_duracion_s
        self._usar_fecha_filename = usar_fecha_filename
        self._dry_run = dry_run
        self._logger = logger or logging.getLogger(__name__)

        # Estado interno
        self._fd: Optional[int] = None          # file descriptor del pipe (O_RDWR)
        self._ring_store: Optional[RingBufferStore] = None
        self._running = False                    # flag de bucle principal
        self._acumulador = bytearray()           # buffer para lecturas parciales

        # Estadísticas
        self.frames_procesados: int = 0
        self.frames_invalidos: int = 0
        self.frames_error: int = 0

    # -----------------------------------------------------------------------
    # API pública
    # -----------------------------------------------------------------------

    def run(self) -> None:
        """
        Inicia el daemon. Bloquea hasta recibir SIGTERM/SIGINT o que ocurra
        un error fatal irrecuperable.

        El flujo es:
        1. Registrar manejadores de señales.
        2. Abrir el ring buffer store.
        3. Abrir el named pipe con O_RDWR.
        4. Bucle de lectura: leer → acumular → procesar tramas completas.
        5. Al recibir señal de parada: cerrar pipe y ring buffer limpiamente.
        """
        # Registrar señales solo si estamos en el hilo principal.
        # En hilos secundarios (ej. tests), signal.signal() lanzaría ValueError.
        if threading.current_thread() is threading.main_thread():
            self._registrar_señales()

        self._running = True

        self._logger.info(
            f"[STREAM_START] pipe={self._pipe_path} | "
            f"buffer={self._buffer_dir} | "
            f"dry_run={self._dry_run}"
        )

        try:
            if not self._dry_run:
                self._ring_store = RingBufferStore(
                    directorio=self._buffer_dir,
                    max_size_mb=self._max_size_mb,
                    archivo_duracion_s=self._archivo_duracion_s,
                    usar_fecha_filename=self._usar_fecha_filename,
                    logger=None,  # Usamos nuestro propio logger
                )

            self._abrir_pipe()
            self._bucle_lectura()

        except KeyboardInterrupt:
            self._logger.info("[STREAM_STOP] Interrupción por teclado.")
        except Exception as e:
            self._logger.error(f"[STREAM_FATAL] Error irrecuperable: {e}", exc_info=True)
            raise
        finally:
            self._cerrar_recursos()

    def stop(self) -> None:
        """
        Solicita la detención ordenada del daemon.

        Puede llamarse desde un hilo externo o un manejador de señal.
        El bucle principal detectará el flag y ejecutará el cierre limpio.
        """
        self._running = False

    # -----------------------------------------------------------------------
    # Gestión de señales
    # -----------------------------------------------------------------------

    def _registrar_señales(self) -> None:
        """Registra manejadores para SIGTERM y SIGINT."""
        signal.signal(signal.SIGTERM, self._signal_handler)
        signal.signal(signal.SIGINT, self._signal_handler)

    def _signal_handler(self, signum: int, frame) -> None:
        """Manejador de SIGTERM/SIGINT: solicita parada ordenada."""
        nombre = signal.Signals(signum).name
        self._logger.info(f"[STREAM_SIGNAL] Señal recibida: {nombre}. Iniciando cierre limpio.")
        self.stop()

    # -----------------------------------------------------------------------
    # Gestión del pipe
    # -----------------------------------------------------------------------

    def _abrir_pipe(self) -> None:
        """
        Abre el named pipe con O_RDWR | O_NONBLOCK.

        - O_RDWR: evita el EOF en el lado lector cuando no hay escritor activo,
          ya que el proceso mismo mantiene el extremo de escritura abierto.
          Esto es la "Opción B" documentada en prompts_temporales.md.
        - O_NONBLOCK: hace que os.read() levante BlockingIOError (EAGAIN) en
          lugar de bloquearse cuando no hay datos. Esto permite que el bucle
          compruebe self._running y responda a stop() sin demora.

        Raises:
            FileNotFoundError: Si el pipe no existe en la ruta configurada.
            OSError:           Si no se puede abrir por otro motivo.
        """
        if not os.path.exists(self._pipe_path):
            raise FileNotFoundError(
                f"Named pipe no encontrado: {self._pipe_path}. "
                f"¿Está corriendo registro_continuo?"
            )

        self._fd = os.open(self._pipe_path, os.O_RDWR | os.O_NONBLOCK)
        self._logger.info(f"[PIPE_OPEN] Pipe abierto: {self._pipe_path} (fd={self._fd}, O_RDWR|O_NONBLOCK)")

    def _cerrar_pipe(self) -> None:
        """Cierra el file descriptor del pipe de forma segura."""
        if self._fd is not None:
            try:
                os.close(self._fd)
                self._logger.info(f"[PIPE_CLOSE] Pipe cerrado: {self._pipe_path}")
            except OSError:
                pass
            finally:
                self._fd = None

    # -----------------------------------------------------------------------
    # Bucle principal de lectura
    # -----------------------------------------------------------------------

    def _bucle_lectura(self) -> None:
        """
        Bucle principal: lee bytes del pipe y acumula hasta tener una trama completa.

        Estrategia de lectura parcial:
            os.read() puede retornar menos bytes de los solicitados. El acumulador
            bytearray garantiza que siempre procesamos tramas completas de FRAME_SIZE.

        Manejo de datos vacíos:
            Si os.read() retorna b'' (EOF) en modo O_RDWR, puede indicar que el
            escritor cerró y aún no ha reabierto. Se duerme brevemente y se continúa.
        """
        ultimo_frame_time = time.monotonic()
        advertencia_timeout_enviada = False

        self._logger.info("[STREAM_LOOP] Iniciando bucle de lectura.")

        while self._running:
            try:
                # Intentar leer hasta completar FRAME_SIZE bytes
                bytes_faltantes = FRAME_SIZE - len(self._acumulador)
                chunk = os.read(self._fd, bytes_faltantes)

                if not chunk:
                    # EOF transitorio (escritor cerró temporalmente): esperar y continuar
                    ahora = time.monotonic()
                    if not advertencia_timeout_enviada and (ahora - ultimo_frame_time) > READ_TIMEOUT_S:
                        self._logger.warning(
                            f"[STREAM_TIMEOUT] Sin datos en >{READ_TIMEOUT_S}s. "
                            f"¿Está corriendo registro_continuo?"
                        )
                        advertencia_timeout_enviada = True
                    time.sleep(0.01)
                    continue

                self._acumulador.extend(chunk)
                advertencia_timeout_enviada = False

                # Procesar todas las tramas completas acumuladas
                while len(self._acumulador) >= FRAME_SIZE:
                    raw_frame = bytes(self._acumulador[:FRAME_SIZE])
                    del self._acumulador[:FRAME_SIZE]
                    self._procesar_trama(raw_frame)
                    ultimo_frame_time = time.monotonic()

            except BlockingIOError:
                # O_RDWR + O_NONBLOCK: no hay datos disponibles, esperar
                time.sleep(0.005)
                continue
            except OSError as e:
                if self._running:
                    self._logger.error(f"[PIPE_READ_ERROR] Error leyendo pipe: {e}")
                    self.frames_error += 1
                    time.sleep(0.1)
                break

        self._logger.info(
            f"[STREAM_LOOP] Bucle finalizado. "
            f"Procesadas={self.frames_procesados} | "
            f"Inválidas={self.frames_invalidos} | "
            f"Errores={self.frames_error}"
        )

    # -----------------------------------------------------------------------
    # Procesamiento de trama individual
    # -----------------------------------------------------------------------

    def _procesar_trama(self, raw_frame: bytes) -> None:
        """
        Valida el timestamp de una trama y la escribe al ring buffer.

        Tramas con timestamp inválido (hora>23, min>59, seg>59) son descartadas
        con un log WARNING, conforme a la especificación de la Fase 3.

        Args:
            raw_frame: Exactamente FRAME_SIZE (2506) bytes de la trama.
        """
        try:
            timestamp = decode_timestamp(
                raw_frame,
                usar_fecha_filename=False,  # No hay filename en el pipe
            )
        except ValueError as e:
            self.frames_invalidos += 1
            self._logger.warning(
                f"[FRAME_INVALID] Trama descartada: timestamp inválido. "
                f"frames_invalidos={self.frames_invalidos} | error={e}"
            )
            return

        if self._dry_run:
            self._logger.debug(
                f"[DRY_RUN] Trama válida: ts={timestamp.strftime('%Y-%m-%d %H:%M:%S')} | "
                f"total_procesadas={self.frames_procesados + 1}"
            )
            self.frames_procesados += 1
            return

        try:
            self._ring_store.write_frame(raw_frame, timestamp)
            self.frames_procesados += 1

            if self.frames_procesados % 300 == 0:
                # Log de progreso cada 300 tramas (≈5 minutos)
                self._logger.info(
                    f"[STREAM_PROGRESS] frames_procesados={self.frames_procesados} | "
                    f"invalidos={self.frames_invalidos} | "
                    f"uso_disco_mb={self._ring_store.get_disk_usage_mb():.1f}"
                )
        except Exception as e:
            self.frames_error += 1
            self._logger.error(
                f"[FRAME_WRITE_ERROR] Error escribiendo trama al ring buffer: {e}"
            )

    # -----------------------------------------------------------------------
    # Cierre limpio
    # -----------------------------------------------------------------------

    def _cerrar_recursos(self) -> None:
        """Cierra el pipe y el ring buffer en orden correcto."""
        self._cerrar_pipe()
        if self._ring_store is not None:
            try:
                self._ring_store.close()
                self._logger.info("[RING_CLOSE] RingBufferStore cerrado limpiamente.")
            except Exception as e:
                self._logger.error(f"[RING_CLOSE_ERROR] Error cerrando ring buffer: {e}")
            finally:
                self._ring_store = None

        self._logger.info(
            f"[STREAM_EXIT] Daemon finalizado. "
            f"procesados={self.frames_procesados} | "
            f"invalidos={self.frames_invalidos} | "
            f"errores={self.frames_error}"
        )


# ---------------------------------------------------------------------------
# Punto de entrada CLI
# ---------------------------------------------------------------------------

def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "stream_processor — Daemon de lectura del named pipe al ring buffer RSA.\n"
            "Lee tramas de 2506 bytes desde /tmp/my_pipe y las almacena en disco."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--pipe",
        default=DEFAULT_PIPE_PATH,
        metavar="RUTA",
        help=f"Ruta al named pipe FIFO (default: {DEFAULT_PIPE_PATH})",
    )
    parser.add_argument(
        "--buffer-dir",
        default=DEFAULT_BUFFER_DIR,
        metavar="DIR",
        help=f"Directorio del ring buffer (default: {DEFAULT_BUFFER_DIR})",
    )
    parser.add_argument(
        "--max-size-mb",
        type=int,
        default=DEFAULT_MAX_SIZE_MB,
        metavar="MB",
        help=f"Tamaño máximo del ring buffer en MB (default: {DEFAULT_MAX_SIZE_MB})",
    )
    parser.add_argument(
        "--duracion-archivo",
        type=int,
        default=DEFAULT_ARCHIVO_DURACION_S,
        metavar="SEG",
        help=f"Segundos de datos por archivo del ring buffer (default: {DEFAULT_ARCHIVO_DURACION_S})",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Leer del pipe sin escribir al ring buffer (modo diagnóstico).",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Mostrar logs también en stdout.",
    )
    return parser.parse_args()


def main() -> None:
    """Punto de entrada principal del daemon."""
    args = _parse_args()

    project_root = os.getenv("PROJECT_LOCAL_ROOT")
    logger = _setup_logger(project_root, verbose=args.verbose)

    processor = StreamProcessor(
        pipe_path=args.pipe,
        buffer_dir=args.buffer_dir,
        max_size_mb=args.max_size_mb,
        archivo_duracion_s=args.duracion_archivo,
        usar_fecha_filename=DEFAULT_USAR_FECHA_FILENAME,
        dry_run=args.dry_run,
        logger=logger,
    )

    processor.run()


if __name__ == "__main__":
    main()

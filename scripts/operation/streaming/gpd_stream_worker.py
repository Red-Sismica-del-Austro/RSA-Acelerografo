"""
gpd_stream_worker.py — Worker de inferencia GPD en tiempo real.

Daemon consumidor que:
1. Lee tramas decodificadas desde memoria compartida (/dev/shm/) mediante SharedMemoryReader.
2. Resamplea de 250 Hz a 100 Hz con SignalPreprocessor.
3. Acumula un buffer circular de 800 muestras (8 s a 100 Hz) como padding.
4. Cada 1 segundo (1 trama), extrae la ventana central de 400 muestras (4 s),
   aplica filtrado + normalización y ejecuta inferencia TFLite.
5. Si P > umbral_p o S > umbral_s y no hay cooldown activo, publica la detección en MQTT.

Configuración esperada (sección 'gpd' de configuracion_dispositivo.json):
{
    "habilitado": true,
    "modelo_ruta": "models/gpd.tflite",
    "umbral_p": 0.95,
    "umbral_s": 0.95,
    "cooldown_s": 30,
    "ventana_pre_evento_s": 60,
    "ventana_post_evento_s": 60,
    "auto_extract": true,
    "auto_upload": true,
    "filtro": {
        "habilitado": true,
        "freq_min_hz": 3.0,
        "freq_max_hz": 20.0
    }
}

Uso como script principal:
    python3 gpd_stream_worker.py [--config <ruta>] [--station <id>] [--log-dir <dir>]
"""

import argparse
import json
import logging
import os
import signal
import sys
import threading
import time
from collections import deque
from datetime import datetime, timedelta, timezone
from typing import Optional

import numpy as np

# Añadir directorio padre al path para importar módulos del proyecto
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_OPERATION_DIR = os.path.dirname(_SCRIPT_DIR)
if _OPERATION_DIR not in sys.path:
    sys.path.insert(0, _OPERATION_DIR)

from streaming.shared_memory_publisher import SharedMemoryReader, SHM_PATH
from core.signal_preprocessor import SignalPreprocessor
from core.event_logger import EventLogger

# Importación condicional del extractor de eventos (solo necesario en modo offline)
try:
    from mqtt.event_extractor import extraer_y_subir_evento
    _EXTRACTOR_AVAILABLE = True
except ImportError:
    _EXTRACTOR_AVAILABLE = False

# Importación condicional de tflite_runtime para facilitar tests sin el runtime instalado
try:
    from tflite_runtime.interpreter import Interpreter as TFLiteInterpreter
    _TFLITE_AVAILABLE = True
except ImportError:
    TFLiteInterpreter = None
    _TFLITE_AVAILABLE = False

# Importación condicional de paho-mqtt
try:
    import paho.mqtt.client as mqtt_client
    _MQTT_AVAILABLE = True
except ImportError:
    mqtt_client = None
    _MQTT_AVAILABLE = False

# ---------------------------------------------------------------------------
# Constantes del pipeline GPD
# ---------------------------------------------------------------------------

# Muestras de datos crudos resampleadas a 100 Hz necesarias para llenar el buffer
_GPD_WINDOW_SAMPLES = 400       # 4 s a 100 Hz — ventana de inferencia del modelo
_GPD_BUFFER_SAMPLES = 800       # 8 s a 100 Hz — buffer con padding (Opción A)
_GPD_SAMPLES_PER_FRAME = 100    # 100 muestras por trama a 100 Hz (1 s de datos)
_GPD_AXES = 3                   # Canales: N, E, Z

# Valores por defecto de configuración
_DEFAULT_UMBRAL_P = 0.95
_DEFAULT_UMBRAL_S = 0.95
_DEFAULT_COOLDOWN_S = 30.0
_DEFAULT_MODELO_RUTA = "models/gpd.tflite"
_DEFAULT_TFLITE_THREADS = 2
_DEFAULT_STATS_INTERVAL = 100   # Reportar estadísticas cada N inferencias
_DEFAULT_SHM_RETRY_MAX = 30     # Segundos máximos de espera para el SHM al arrancar
_DEFAULT_POLL_SLEEP_S = 0.010   # 10 ms de sleep si no hay trama nueva


class GPDStreamWorker:
    """
    Worker de inferencia GPD en tiempo real.

    Lee tramas decodificadas desde la memoria compartida, acumula un buffer
    deslizante de 8 segundos (con padding) y ejecuta inferencia TFLite con un
    stride de 1 segundo. Publica detecciones de fases P/S vía MQTT.

    Diseñado para ejecutarse como servicio Supervisor en la RPi 3B+.
    """

    def __init__(self, config: dict, logger: logging.Logger, project_root: str = ""):
        """
        Inicializa el worker.

        Args:
            config:       Sección 'gpd' de configuracion_dispositivo.json.
            logger:       Logger del proceso (debe ser compatible con StructuredLogger o logging.Logger).
            project_root: Directorio raíz del proyecto para resolver rutas relativas al modelo.
        """
        self._config = config
        self._logger = logger
        self._project_root = project_root

        # --- Parámetros de inferencia ---
        modelo_ruta_rel = config.get("modelo_ruta", _DEFAULT_MODELO_RUTA)
        if os.path.isabs(modelo_ruta_rel):
            self._model_path = modelo_ruta_rel
        else:
            self._model_path = os.path.join(project_root, modelo_ruta_rel) if project_root else modelo_ruta_rel

        self._umbral_p: float = float(config.get("umbral_p", _DEFAULT_UMBRAL_P))
        self._umbral_s: float = float(config.get("umbral_s", _DEFAULT_UMBRAL_S))
        self._cooldown_s: float = float(config.get("cooldown_s", _DEFAULT_COOLDOWN_S))
        self._station_id: str = config.get("station_id", "UNKNOWN")
        self._tflite_threads: int = int(config.get("tflite_threads", _DEFAULT_TFLITE_THREADS))

        # Parámetros del filtro (para SignalPreprocessor)
        filtro_cfg = config.get("filtro", {})
        self._filter_enabled: bool = filtro_cfg.get("habilitado", True)
        self._freq_min: float = float(filtro_cfg.get("freq_min_hz", 3.0))
        self._freq_max: float = float(filtro_cfg.get("freq_max_hz", 20.0))

        # Ruta del segmento de memoria compartida
        self._shm_path: str = config.get("shm_path", SHM_PATH)

        # --- Modo de adquisición (online/offline) ---
        self._modo_adquisicion: str = config.get("modo_adquisicion", "online")

        # --- Logger de eventos CSV ---
        csv_dir = config.get("csv_dir", "/home/rsa/data/eventos-detectados")
        self._event_logger = EventLogger(csv_dir=csv_dir, logger=logger)

        # --- Buffer circular (deque de filas de 100 muestras a 100 Hz) ---
        # maxlen = 8 para mantener exactamente 8 segundos (800 muestras acumuladas)
        self._buffer: deque = deque(maxlen=8)

        # --- Estado interno ---
        self._running: bool = False
        self._last_seq: int = -1                     # Último sequence_number leído
        self._last_detection_time: float = 0.0       # Timestamp de la última detección publicada

        # --- Objetos que se inicializan en run() ---
        self._shm_reader: Optional[SharedMemoryReader] = None
        self._preprocessor: Optional[SignalPreprocessor] = None
        self._interpreter = None                     # TFLite Interpreter
        self._mqtt: Optional[object] = None          # Cliente MQTT

        # --- Estadísticas ---
        self.inferencias_total: int = 0
        self.detecciones_p: int = 0
        self.detecciones_s: int = 0

    # -----------------------------------------------------------------------
    # API pública
    # -----------------------------------------------------------------------

    def run(self) -> None:
        """
        Bucle principal del worker.

        Flujo:
        1. Registrar handlers de señal SIGTERM/SIGINT.
        2. Inicializar SignalPreprocessor.
        3. Cargar modelo TFLite.
        4. Conectar cliente MQTT (si está disponible).
        5. Esperar a que el SHM esté disponible (retry con backoff).
        6. Bucle de polling:
            a. Leer sequence_number.
            b. Si hay trama nueva → resamplear, acumular en buffer.
            c. Si buffer ≥ 800 muestras → inferir y evaluar.
            d. Si no hay trama nueva → sleep(10 ms).
        7. Cierre limpio al recibir señal de parada.
        """
        self._running = True

        # Registrar señales POSIX
        signal.signal(signal.SIGTERM, self._handle_signal)
        signal.signal(signal.SIGINT, self._handle_signal)

        self._logger.info("[GPD_INIT] Iniciando GPDStreamWorker.")

        try:
            # Inicializar preprocesador
            self._preprocessor = SignalPreprocessor(
                filter_enabled=self._filter_enabled,
                freq_min=self._freq_min,
                freq_max=self._freq_max,
            )
            self._logger.info(
                f"[GPD_INIT] SignalPreprocessor listo — "
                f"filtro={'sí' if self._filter_enabled else 'no'} "
                f"[{self._freq_min}-{self._freq_max} Hz]"
            )

            # Cargar modelo TFLite
            self._cargar_modelo()

            # Conectar MQTT
            self._conectar_mqtt()

            # Esperar y abrir el SHM con retry.
            # Si el SHM no aparece en el tiempo límite, se registra el error y
            # el worker termina limpiamente (sin propagar la excepción al exterior).
            try:
                self._abrir_shm_con_retry()
            except RuntimeError as exc:
                self._logger.error(f"[GPD_SHM_FAIL] No se pudo abrir el SHM al arrancar: {exc}. Terminando.")
                self._running = False
                return

            # --- Bucle principal ---
            self._logger.info("[GPD_START] Bucle de inferencia iniciado.")
            while self._running:
                try:
                    self._ciclo_inferencia()
                except OSError as exc:
                    # El SHM puede desaparecer si stream_processor se reinicia
                    self._logger.warning(f"[GPD_SHM_LOST] SHM no disponible: {exc}. Reintentando...")
                    time.sleep(2.0)
                    try:
                        self._abrir_shm_con_retry()
                    except RuntimeError:
                        self._logger.error("[GPD_SHM_FAIL] No se pudo reconectar al SHM. Terminando.")
                        break
                except Exception as exc:  # pylint: disable=broad-except
                    self._logger.error(f"[GPD_ERROR] Error inesperado en ciclo: {exc}", exc_info=True)
                    time.sleep(1.0)

        finally:
            self._cerrar_recursos()
            self._log_estadisticas_finales()
            self._logger.info("[GPD_STOP] GPDStreamWorker detenido.")

    def stop(self) -> None:
        """Solicita la detención ordenada del worker."""
        self._logger.info("[GPD_STOP_REQ] Solicitud de parada recibida.")
        self._running = False

    # -----------------------------------------------------------------------
    # Inicialización
    # -----------------------------------------------------------------------

    def _cargar_modelo(self) -> None:
        """
        Carga el intérprete TFLite y configura el tensor de entrada para batch=1.

        Eleva RuntimeError si tflite_runtime no está instalado o el modelo no existe.
        """
        if not _TFLITE_AVAILABLE:
            raise RuntimeError(
                "tflite_runtime no está instalado. "
                "Instálalo con: pip install tflite-runtime"
            )

        if not os.path.exists(self._model_path):
            raise FileNotFoundError(
                f"Modelo TFLite no encontrado en: {self._model_path}"
            )

        t0 = time.monotonic()
        self._interpreter = TFLiteInterpreter(
            model_path=self._model_path,
            num_threads=self._tflite_threads,
        )

        # Configurar tensor de entrada: (1, 400, 3) float32
        input_details = self._interpreter.get_input_details()
        self._interpreter.resize_tensor_input(input_details[0]["index"], [1, _GPD_WINDOW_SAMPLES, _GPD_AXES])
        self._interpreter.allocate_tensors()

        # Cachear detalles de entrada/salida para el bucle
        self._input_details = self._interpreter.get_input_details()
        self._output_details = self._interpreter.get_output_details()

        load_time = time.monotonic() - t0
        self._logger.info(
            f"[GPD_LOAD] Modelo TFLite cargado: {self._model_path} "
            f"en {load_time:.2f}s con {self._tflite_threads} hilo(s)."
        )

    def _conectar_mqtt(self) -> None:
        """
        Conecta el cliente MQTT al broker para publicar detecciones.

        Si MQTT no está disponible o la conexión falla, el worker continúa sin MQTT
        (las detecciones se loguean pero no se publican).
        """
        if not _MQTT_AVAILABLE:
            self._logger.warning(
                "[GPD_MQTT] paho-mqtt no disponible. Las detecciones solo se registrarán en el log."
            )
            return

        broker = self._config.get("mqtt_broker", "localhost")
        port = int(self._config.get("mqtt_port", 1883))
        client_id = f"gpd_worker_{self._station_id}_{os.getpid()}"

        try:
            self._mqtt = mqtt_client.Client(client_id=client_id)
            self._mqtt.connect(broker, port, keepalive=60)
            self._mqtt.loop_start()
            self._logger.info(f"[GPD_MQTT] Conectado al broker {broker}:{port} (client_id={client_id}).")
        except Exception as exc:  # pylint: disable=broad-except
            self._logger.warning(
                f"[GPD_MQTT_WARN] No se pudo conectar al broker MQTT ({broker}:{port}): {exc}. "
                "Las detecciones solo se registrarán en el log."
            )
            self._mqtt = None

    def _abrir_shm_con_retry(self) -> None:
        """
        Intenta abrir la memoria compartida con backoff exponencial.

        Espera hasta _DEFAULT_SHM_RETRY_MAX segundos antes de lanzar RuntimeError.
        """
        wait = 0.5
        elapsed = 0.0

        while self._running:
            try:
                if self._shm_reader is not None:
                    try:
                        self._shm_reader.close()
                    except Exception:  # pylint: disable=broad-except
                        pass
                self._shm_reader = SharedMemoryReader(shm_path=self._shm_path)
                self._last_seq = -1  # Reiniciar para procesar la primera trama disponible
                self._logger.info(f"[GPD_SHM_OK] SHM abierto: {self._shm_path}")
                return
            except FileNotFoundError:
                self._logger.warning(
                    f"[GPD_SHM_WAIT] SHM no disponible ({self._shm_path}). "
                    f"Reintentando en {wait:.1f}s... ({elapsed:.0f}/{_DEFAULT_SHM_RETRY_MAX}s)"
                )
                time.sleep(wait)
                elapsed += wait
                wait = min(wait * 2, 8.0)  # Backoff exponencial hasta 8 s

                if elapsed >= _DEFAULT_SHM_RETRY_MAX:
                    raise RuntimeError(
                        f"SHM no disponible tras {_DEFAULT_SHM_RETRY_MAX}s de espera: {self._shm_path}"
                    )

        raise RuntimeError("Worker detenido antes de abrir el SHM.")

    # -----------------------------------------------------------------------
    # Ciclo principal
    # -----------------------------------------------------------------------

    def _ciclo_inferencia(self) -> None:
        """
        Ejecuta un ciclo del bucle principal de inferencia.

        Si hay una trama nueva en el SHM:
            1. Lee la trama completa.
            2. Resamplea de 250 Hz a 100 Hz.
            3. Agrega al buffer circular.
            4. Si el buffer está lleno (≥ 800 muestras), ejecuta inferencia.
        Si no hay trama nueva, duerme 10 ms.
        """
        current_seq = self._shm_reader.get_sequence_number()

        if current_seq == self._last_seq:
            # Sin trama nueva
            time.sleep(_DEFAULT_POLL_SLEEP_S)
            return

        # Hay una trama nueva — leer datos completos
        seq, timestamp, samples_250x3, _clock = self._shm_reader.read()

        # Evitar procesar la misma trama dos veces en caso de lectura doble
        if seq == self._last_seq:
            return

        self._last_seq = seq

        # Resamplear de 250 Hz a 100 Hz → (100, 3) float64
        resampled = self._preprocessor.resample_frame(samples_250x3)

        # Acumular en el buffer circular de 8 tramas (800 muestras)
        self._buffer.append(resampled)

        # Solo ejecutar inferencia cuando el buffer tiene 8 tramas completas (8 s)
        if len(self._buffer) < 8:
            self._logger.info(
                f"[GPD_BUF] Llenando buffer: {len(self._buffer)}/8 tramas ({len(self._buffer)} s)"
            ) if len(self._buffer) == 1 else None
            return

        # Construir ventana de 800 muestras concatenando las 8 tramas del buffer
        window_800 = np.concatenate(list(self._buffer), axis=0)  # (800, 3) float64

        # Preprocesar: filtro + extracción central 400 muestras + normalización → (1, 400, 3) float32
        ventana_lista = self._preprocessor.prepare_window(window_800)

        # Ejecutar inferencia TFLite
        probabilidades = self._ejecutar_inferencia(ventana_lista)  # ndarray (3,)
        self.inferencias_total += 1

        prob_noise = float(probabilidades[0])
        prob_p = float(probabilidades[1])
        prob_s = float(probabilidades[2])

        self._logger.debug(
            f"[GPD_INFER] noise={prob_noise:.3f} P={prob_p:.3f} S={prob_s:.3f} | "
            f"seq={seq} total={self.inferencias_total}"
        )

        # Reportar estadísticas periódicas
        if self.inferencias_total % _DEFAULT_STATS_INTERVAL == 0:
            self._log_estadisticas_periodicas()

        # Evaluar si se supera el umbral y no hay cooldown
        deteccion = self._evaluar_deteccion(prob_noise, prob_p, prob_s, timestamp)
        if deteccion is not None:
            self._publicar_deteccion(deteccion)

    # -----------------------------------------------------------------------
    # Inferencia TFLite
    # -----------------------------------------------------------------------

    def _ejecutar_inferencia(self, ventana: np.ndarray) -> np.ndarray:
        """
        Ejecuta inferencia TFLite sobre una ventana preprocesada.

        Args:
            ventana: ndarray (1, 400, 3) float32 — tensor listo para el modelo.

        Returns:
            ndarray (3,) float32 — probabilidades [noise, P, S].

        Raises:
            RuntimeError: Si el intérprete no está cargado.
        """
        if self._interpreter is None:
            raise RuntimeError("Intérprete TFLite no inicializado.")

        # Asegurar dtype correcto (el modelo espera float32)
        input_data = ventana.astype(np.float32)

        self._interpreter.set_tensor(self._input_details[0]["index"], input_data)
        self._interpreter.invoke()
        output = self._interpreter.get_tensor(self._output_details[0]["index"])  # (1, 3)

        return output[0]  # (3,) — [noise, P, S]

    # -----------------------------------------------------------------------
    # Evaluación de detecciones
    # -----------------------------------------------------------------------

    def _evaluar_deteccion(
        self,
        prob_noise: float,
        prob_p: float,
        prob_s: float,
        timestamp: float,
    ) -> Optional[dict]:
        """
        Evalúa si las probabilidades superan los umbrales y si no hay cooldown activo.

        Prioridad: fase P > fase S (si ambas superan el umbral en la misma inferencia,
        se reporta P).

        Args:
            prob_noise: Probabilidad de ruido.
            prob_p:     Probabilidad de fase P.
            prob_s:     Probabilidad de fase S.
            timestamp:  Unix timestamp de la trama más reciente en el buffer.

        Returns:
            dict con la detección si se supera umbral, o None.
        """
        ahora = time.time()
        cooldown_restante = (self._last_detection_time + self._cooldown_s) - ahora

        # Determinar la fase con mayor probabilidad que supere su umbral
        fase_detectada = None
        prob_detectada = 0.0

        if prob_p >= self._umbral_p:
            fase_detectada = "P"
            prob_detectada = prob_p

        if prob_s >= self._umbral_s and prob_s > prob_detectada:
            fase_detectada = "S"
            prob_detectada = prob_s

        if fase_detectada is None:
            return None

        # Verificar cooldown
        if cooldown_restante > 0:
            self._logger.debug(
                f"[GPD_COOLDOWN] Detección {fase_detectada} ({prob_detectada:.3f}) ignorada — "
                f"cooldown activo: {cooldown_restante:.1f}s restantes."
            )
            return None

        # Registrar tiempo de detección y actualizar contadores
        self._last_detection_time = ahora
        if fase_detectada == "P":
            self.detecciones_p += 1
        else:
            self.detecciones_s += 1

        # El timestamp de la trama corresponde al FINAL de la ventana de 1 s más reciente.
        # La ventana inferida cubre los 4 s centrales del buffer de 8 s.
        # Centro de la ventana = timestamp - 3 s (mitad de la ventana de 4 s pasados los 2 s de cola)
        centro_ventana = timestamp - 2.0   # 2 s antes del borde final del buffer
        inicio_ventana = centro_ventana - 2.0
        fin_ventana = centro_ventana + 2.0

        def _ts_iso(t: float) -> str:
            return datetime.fromtimestamp(t, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"

        deteccion = {
            "type": fase_detectada,
            "probability": round(prob_detectada, 4),
            "timestamp": _ts_iso(centro_ventana),
            "window_start": _ts_iso(inicio_ventana),
            "window_end": _ts_iso(fin_ventana),
            "station_id": self._station_id,
            "model": os.path.basename(self._model_path),
            "source": "streaming",
        }

        self._logger.info(
            f"[GPD_DETECTION] Fase {fase_detectada} detectada — "
            f"prob={prob_detectada:.4f} ts={deteccion['timestamp']} "
            f"(P_total={self.detecciones_p}, S_total={self.detecciones_s})"
        )

        return deteccion

    # -----------------------------------------------------------------------
    # Publicación / despacho de detecciones
    # -----------------------------------------------------------------------

    def _publicar_deteccion(self, deteccion: dict) -> None:
        """
        Procesa una detección de fase sísmica según el modo de adquisición.

        Ambos modos registran la detección en el CSV mensual (confirmado=False).
        - ONLINE:  Publica en MQTT para que mqtt_coordinator coordine la extracción
                   con la validación regional.
        - OFFLINE: Lanza la extracción local en un hilo separado, sin pasar por MQTT.
        """
        # 1. Registrar en CSV (siempre, en ambos modos)
        try:
            self._event_logger.registrar_deteccion(
                timestamp_centro=deteccion["timestamp"],
                fase=deteccion["type"],
                probabilidad=deteccion["probability"],
                confirmado=False,
                metodo="local_gpd",
            )
        except Exception as exc:  # pylint: disable=broad-except
            self._logger.warning(f"[GPD_CSV_WARN] Error al registrar detección en CSV: {exc}")

        if self._modo_adquisicion == "offline":
            # Modo OFFLINE: extracción autónoma local en hilo separado
            self._lanzar_extraccion_offline(deteccion)
        else:
            # Modo ONLINE: publicar en MQTT para validación regional
            self._publicar_mqtt(deteccion)

    def _publicar_mqtt(self, deteccion: dict) -> None:
        """
        Publica la detección en el tópico MQTT <station_id>/events/detected.

        Si el cliente MQTT no está disponible, solo se registra en el log.
        """
        payload = json.dumps(deteccion, ensure_ascii=False)
        topic = f"{self._station_id}/events/detected"

        if self._mqtt is not None:
            try:
                result = self._mqtt.publish(topic, payload, qos=1, retain=False)
                if result.rc == 0:
                    self._logger.debug(f"[GPD_MQTT_PUB] Publicado en '{topic}': {payload}")
                else:
                    self._logger.warning(
                        f"[GPD_MQTT_PUB_WARN] Publicación en '{topic}' retornó rc={result.rc}."
                    )
            except Exception as exc:  # pylint: disable=broad-except
                self._logger.warning(f"[GPD_MQTT_PUB_ERROR] Error publicando detección: {exc}")
        else:
            self._logger.info(f"[GPD_DETECTION_LOG] (sin MQTT) topic={topic} payload={payload}")

    def _lanzar_extraccion_offline(self, deteccion: dict) -> None:
        """
        Lanza la extracción del evento en un hilo separado (modo offline).

        Calcula el rango de extracción usando ventana_pre_evento_s y
        ventana_post_evento_s de la configuración. Si event_extractor no está
        disponible (ImportError), loguea un warning y no crashea.
        """
        if not _EXTRACTOR_AVAILABLE:
            self._logger.warning(
                "[GPD_OFFLINE] Módulo event_extractor no disponible. "
                "No se puede extraer automáticamente."
            )
            return

        ventana_pre = int(self._config.get("ventana_pre_evento_s", 60))
        ventana_post = int(self._config.get("ventana_post_evento_s", 60))
        ts_centro = deteccion["timestamp"]  # ISO8601 UTC con 'Z'

        try:
            dt_centro = datetime.fromisoformat(ts_centro.replace("Z", "+00:00"))
        except ValueError as exc:
            self._logger.error(
                f"[GPD_OFFLINE_ERR] Timestamp de detección inválido '{ts_centro}': {exc}"
            )
            return

        dt_start = dt_centro - timedelta(seconds=ventana_pre)
        start_str = dt_start.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
        duration = ventana_pre + ventana_post

        self._logger.info(
            f"[GPD_OFFLINE_EXTRACT] Lanzando extracción autónoma — "
            f"start={start_str} duration={duration}s ts_deteccion={ts_centro}"
        )

        hilo = threading.Thread(
            target=self._run_extraccion_offline,
            args=(deteccion, start_str, duration),
            daemon=True,
        )
        hilo.start()

    def _run_extraccion_offline(self, deteccion: dict, start: str, duration: float) -> None:
        """
        Pipeline de extracción offline ejecutado en hilo separado.

        Invoca extraer_y_subir_evento() con upload=False (no sube a Drive en modo
        offline) y actualiza el CSV a confirmado=True si la extracción es exitosa.
        """
        try:
            resultado = extraer_y_subir_evento(
                start=start,
                duration=duration,
                upload=False,            # Modo offline: no subir a Drive
                delete_after_upload=False,
                logger=self._logger,
            )

            if resultado.get("status") == "completed":
                archivo = resultado.get("output_file", "")
                try:
                    self._event_logger.actualizar_confirmacion(
                        timestamp_centro=deteccion["timestamp"],
                        confirmado=True,
                        archivo_mseed=archivo,
                    )
                except Exception as exc:  # pylint: disable=broad-except
                    self._logger.warning(
                        f"[GPD_CSV_WARN] No se pudo actualizar CSV tras extracción: {exc}"
                    )
                self._logger.info(
                    f"[GPD_OFFLINE_OK] Extracción completada → archivo={archivo}"
                )
            else:
                self._logger.warning(
                    f"[GPD_OFFLINE_FAIL] Extracción fallida: {resultado.get('message')}"
                )

        except Exception as exc:  # pylint: disable=broad-except
            self._logger.error(f"[GPD_OFFLINE_ERROR] Error inesperado en extracción offline: {exc}")

    # -----------------------------------------------------------------------
    # Cierre y estadísticas
    # -----------------------------------------------------------------------

    def _cerrar_recursos(self) -> None:
        """Cierra el cliente MQTT y el lector SHM de forma ordenada."""
        if self._mqtt is not None:
            try:
                self._mqtt.loop_stop()
                self._mqtt.disconnect()
                self._logger.info("[GPD_MQTT] Cliente MQTT desconectado.")
            except Exception as exc:  # pylint: disable=broad-except
                self._logger.warning(f"[GPD_MQTT_CLOSE_WARN] Error al cerrar MQTT: {exc}")
            self._mqtt = None

        if self._shm_reader is not None:
            try:
                self._shm_reader.close()
                self._logger.info("[GPD_SHM_CLOSE] Lector SHM cerrado.")
            except Exception as exc:  # pylint: disable=broad-except
                self._logger.warning(f"[GPD_SHM_CLOSE_WARN] Error al cerrar SHM: {exc}")
            self._shm_reader = None

    def _log_estadisticas_periodicas(self) -> None:
        """Registra estadísticas de inferencia acumuladas."""
        self._logger.info(
            f"[GPD_STATS] inferencias={self.inferencias_total} "
            f"detecciones_P={self.detecciones_p} detecciones_S={self.detecciones_s}"
        )

    def _log_estadisticas_finales(self) -> None:
        """Registra las estadísticas finales al cierre del worker."""
        self._logger.info(
            f"[GPD_STATS_FINAL] Total inferencias={self.inferencias_total} | "
            f"Detecciones P={self.detecciones_p} | Detecciones S={self.detecciones_s}"
        )

    # -----------------------------------------------------------------------
    # Handlers de señal
    # -----------------------------------------------------------------------

    def _handle_signal(self, signum: int, frame) -> None:
        """Handler de SIGTERM/SIGINT para parada ordenada."""
        sig_name = "SIGTERM" if signum == signal.SIGTERM else "SIGINT"
        self._logger.info(f"[GPD_SIGNAL] {sig_name} recibido. Iniciando parada ordenada...")
        self._running = False


# ---------------------------------------------------------------------------
# Función principal (entry point del daemon)
# ---------------------------------------------------------------------------

def _configurar_logger(log_dir: str, station_id: str) -> logging.Logger:
    """Configura un logger estándar para el worker cuando se ejecuta como script."""
    os.makedirs(log_dir, exist_ok=True)
    log_path = os.path.join(log_dir, "gpd_stream_worker.log")

    logger = logging.getLogger(f"gpd_worker_{station_id}")
    logger.setLevel(logging.DEBUG)

    if not logger.handlers:
        # Handler de archivo con rotación
        from logging.handlers import RotatingFileHandler
        fh = RotatingFileHandler(log_path, maxBytes=5 * 1024 * 1024, backupCount=3)
        fh.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
        logger.addHandler(fh)

        # Handler de consola para desarrollo
        ch = logging.StreamHandler(sys.stdout)
        ch.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
        logger.addHandler(ch)

    return logger


def main() -> None:
    """Entry point principal del daemon GPD Stream Worker."""
    parser = argparse.ArgumentParser(
        description="GPD Stream Worker — daemon de inferencia sísmica en tiempo real."
    )
    parser.add_argument(
        "--config",
        default=None,
        help="Ruta al archivo configuracion_dispositivo.json. "
             "Si no se especifica, se busca en PROJECT_LOCAL_ROOT/configuration/.",
    )
    parser.add_argument(
        "--station",
        default=None,
        help="ID de estación (sobreescribe el valor del JSON de configuración).",
    )
    parser.add_argument(
        "--log-dir",
        default=None,
        help="Directorio de logs. Por defecto: PROJECT_LOCAL_ROOT/log-files/.",
    )
    args = parser.parse_args()

    # Resolver PROJECT_LOCAL_ROOT
    project_root = os.environ.get("PROJECT_LOCAL_ROOT", "")

    # Resolver ruta de configuración
    if args.config:
        config_path = args.config
    elif project_root:
        config_path = os.path.join(project_root, "configuration", "configuracion_dispositivo.json")
    else:
        # Fallback: buscar relativo al directorio del script
        script_dir = os.path.dirname(os.path.abspath(__file__))
        config_path = os.path.join(script_dir, "..", "..", "..", "configuration", "configuracion_dispositivo.json")
        config_path = os.path.normpath(config_path)

    # Cargar configuración
    if not os.path.exists(config_path):
        print(f"[ERROR] Archivo de configuración no encontrado: {config_path}", file=sys.stderr)
        sys.exit(1)

    with open(config_path, "r", encoding="utf-8") as f:
        full_config = json.load(f)

    station_id = args.station or full_config.get("id", "UNKNOWN")

    # Resolver directorio de logs
    if args.log_dir:
        log_dir = args.log_dir
    elif project_root:
        log_dir = os.path.join(project_root, "log-files")
    else:
        log_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "log-files")
        log_dir = os.path.normpath(log_dir)

    logger = _configurar_logger(log_dir, station_id)

    # Extraer y completar configuración de la sección 'gpd'
    gpd_config = full_config.get("streaming", {}).get("gpd", {})
    if not gpd_config:
        logger.warning(
            "[GPD_INIT] Sección 'streaming.gpd' no encontrada en configuración. "
            "Se usarán valores por defecto."
        )

    # Propagar station_id, modo_adquisicion y MQTT al sub-diccionario gpd_config
    gpd_config["station_id"] = station_id
    gpd_config["modo_adquisicion"] = (
        full_config.get("dispositivo", {}).get("modo_adquisicion", "online")
    )
    mqtt_cfg = full_config.get("mqtt", {})
    gpd_config.setdefault("mqtt_broker", mqtt_cfg.get("broker", "localhost"))
    gpd_config.setdefault("mqtt_port", mqtt_cfg.get("port", 1883))

    # Verificar que GPD esté habilitado
    if not gpd_config.get("habilitado", True):
        logger.info("[GPD_INIT] GPD deshabilitado en configuración. Terminando.")
        sys.exit(0)

    # Crear y ejecutar el worker
    worker = GPDStreamWorker(config=gpd_config, logger=logger, project_root=project_root)
    worker.run()


if __name__ == "__main__":
    main()

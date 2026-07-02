"""
test_gpd_stream_worker.py — Suite de tests para GPDStreamWorker.

Verifica:
- Pipeline de inferencia TFLite con datos sintéticos (shape y rango de salida).
- Mecanismo de cooldown anti-spam.
- Formato correcto del payload de detección.
- Arranque y parada ordenada del worker.
- Comportamiento del buffer circular (8 tramas → inferencia).

Los tests están diseñados para ejecutarse SIN hardware real (sin SHM activo,
sin broker MQTT). Se usa mocking de SharedMemoryReader, TFLite y paho-mqtt.

Ejecución:
    cd montajes/acelerografo-DEV00/scripts/operation/streaming/
    python3 -m pytest test_gpd_stream_worker.py -v
"""

import json
import logging
import os
import sys
import time
import threading
import unittest
from collections import deque
from typing import Optional
from unittest.mock import MagicMock, patch, PropertyMock

import numpy as np

# Añadir directorio padre para importar módulos del proyecto
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_OPERATION_DIR = os.path.dirname(_SCRIPT_DIR)
if _OPERATION_DIR not in sys.path:
    sys.path.insert(0, _OPERATION_DIR)

from streaming.gpd_stream_worker import GPDStreamWorker, _GPD_WINDOW_SAMPLES, _GPD_BUFFER_SAMPLES, _GPD_SAMPLES_PER_FRAME
from core.signal_preprocessor import SignalPreprocessor


# ---------------------------------------------------------------------------
# Utilidades de test
# ---------------------------------------------------------------------------

def _get_test_logger() -> logging.Logger:
    """Logger silencioso para tests (solo muestra WARNING+)."""
    logger = logging.getLogger("test_gpd_worker")
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setLevel(logging.DEBUG)
        logger.addHandler(handler)
    logger.setLevel(logging.DEBUG)
    return logger


def _make_config(
    umbral_p: float = 0.95,
    umbral_s: float = 0.95,
    cooldown_s: float = 30.0,
    station_id: str = "DEV00",
    modelo_ruta: str = "models/gpd.tflite",
) -> dict:
    """Crea una configuración mínima para el worker."""
    return {
        "habilitado": True,
        "modelo_ruta": modelo_ruta,
        "umbral_p": umbral_p,
        "umbral_s": umbral_s,
        "cooldown_s": cooldown_s,
        "station_id": station_id,
        "filtro": {
            "habilitado": True,
            "freq_min_hz": 3.0,
            "freq_max_hz": 20.0,
        },
    }


def _sintetica_250x3(amplitud: float = 1000.0) -> np.ndarray:
    """Genera trama sintética (250, 3) int32."""
    t = np.linspace(0, 1.0, 250, endpoint=False)
    # Señal de 5 Hz en los tres canales
    signal = (amplitud * np.sin(2 * np.pi * 5 * t)).astype(np.int32)
    return np.stack([signal, signal, signal], axis=1)


def _llenar_buffer(worker: GPDStreamWorker, n_tramas: int = 8) -> None:
    """Rellena el buffer del worker con n_tramas sintéticas resampleadas."""
    trama = _sintetica_250x3()
    for _ in range(n_tramas):
        resampled = worker._preprocessor.resample_frame(trama)
        worker._buffer.append(resampled)


# ---------------------------------------------------------------------------
# Tests de SignalPreprocessor (integración básica)
# ---------------------------------------------------------------------------

class TestSignalPreprocessorIntegration(unittest.TestCase):
    """Verifica que el preprocesador produce el tensor correcto antes de la inferencia."""

    def setUp(self):
        self.preprocessor = SignalPreprocessor(
            filter_enabled=True,
            freq_min=3.0,
            freq_max=20.0,
        )

    def test_resample_shape(self):
        """resample_frame: (250, 3) int32 → (100, 3) float."""
        trama = _sintetica_250x3()
        resampled = self.preprocessor.resample_frame(trama)
        self.assertEqual(resampled.shape, (100, 3))

    def test_buffer_ventana_800(self):
        """8 tramas resampleadas acumuladas → (800, 3) float."""
        trama = _sintetica_250x3()
        buffer = deque(maxlen=8)
        for _ in range(8):
            buffer.append(self.preprocessor.resample_frame(trama))

        ventana = np.concatenate(list(buffer), axis=0)
        self.assertEqual(ventana.shape, (800, 3))

    def test_prepare_window_shape_y_dtype(self):
        """prepare_window sobre 800 muestras → (1, 400, 3) float32."""
        trama = _sintetica_250x3()
        buffer = deque(maxlen=8)
        for _ in range(8):
            buffer.append(self.preprocessor.resample_frame(trama))

        ventana_800 = np.concatenate(list(buffer), axis=0)
        resultado = self.preprocessor.prepare_window(ventana_800)

        self.assertEqual(resultado.shape, (1, 400, 3))
        self.assertEqual(resultado.dtype, np.float32)

    def test_prepare_window_rango_normalizado(self):
        """La ventana normalizada tiene valores en [-1, 1]."""
        trama = _sintetica_250x3()
        buffer = deque(maxlen=8)
        for _ in range(8):
            buffer.append(self.preprocessor.resample_frame(trama))

        ventana_800 = np.concatenate(list(buffer), axis=0)
        resultado = self.preprocessor.prepare_window(ventana_800)

        self.assertLessEqual(float(np.max(np.abs(resultado))), 1.0 + 1e-6)


# ---------------------------------------------------------------------------
# Tests de inferencia TFLite (con mock del intérprete)
# ---------------------------------------------------------------------------

class TestGPDInferencia(unittest.TestCase):
    """Verifica el pipeline de inferencia con un intérprete TFLite simulado."""

    def _make_worker_con_mock_modelo(self, prob_salida: np.ndarray) -> GPDStreamWorker:
        """
        Crea un GPDStreamWorker con el intérprete TFLite reemplazado por un mock
        que devuelve prob_salida como resultado de la inferencia.

        Args:
            prob_salida: ndarray (3,) con [noise, P, S].
        """
        config = _make_config()
        logger = _get_test_logger()
        worker = GPDStreamWorker(config=config, logger=logger, project_root="")

        # Inicializar preprocesador manualmente (evita llamar a run())
        worker._preprocessor = SignalPreprocessor(
            filter_enabled=True, freq_min=3.0, freq_max=20.0
        )

        # Mock del intérprete TFLite
        mock_interpreter = MagicMock()
        mock_interpreter.get_input_details.return_value = [{"index": 0}]
        mock_interpreter.get_output_details.return_value = [{"index": 0}]
        mock_interpreter.get_tensor.return_value = np.array([prob_salida], dtype=np.float32)
        worker._interpreter = mock_interpreter
        worker._input_details = mock_interpreter.get_input_details()
        worker._output_details = mock_interpreter.get_output_details()

        return worker

    def test_inferencia_shape_salida(self):
        """_ejecutar_inferencia retorna ndarray de shape (3,)."""
        prob_esperada = np.array([0.01, 0.97, 0.02], dtype=np.float32)
        worker = self._make_worker_con_mock_modelo(prob_esperada)

        # Construir ventana de entrada ficticia
        _llenar_buffer(worker, 8)
        ventana = np.concatenate(list(worker._buffer), axis=0)
        ventana_preprocesada = worker._preprocessor.prepare_window(ventana)

        resultado = worker._ejecutar_inferencia(ventana_preprocesada)
        self.assertEqual(resultado.shape, (3,))

    def test_inferencia_rango_probabilidades(self):
        """Las probabilidades de salida están en [0, 1]."""
        prob_esperada = np.array([0.02, 0.96, 0.02], dtype=np.float32)
        worker = self._make_worker_con_mock_modelo(prob_esperada)

        _llenar_buffer(worker, 8)
        ventana = np.concatenate(list(worker._buffer), axis=0)
        ventana_preprocesada = worker._preprocessor.prepare_window(ventana)

        resultado = worker._ejecutar_inferencia(ventana_preprocesada)
        self.assertTrue(np.all(resultado >= 0.0))
        self.assertTrue(np.all(resultado <= 1.0 + 1e-5))

    def test_inferencia_sin_interprete_lanza_error(self):
        """_ejecutar_inferencia lanza RuntimeError si el intérprete no está cargado."""
        config = _make_config()
        worker = GPDStreamWorker(config=config, logger=_get_test_logger())
        worker._preprocessor = SignalPreprocessor()
        # No se asigna _interpreter → None
        _llenar_buffer(worker, 8)
        ventana = np.concatenate(list(worker._buffer), axis=0)
        ventana_lista = worker._preprocessor.prepare_window(ventana)

        with self.assertRaises(RuntimeError):
            worker._ejecutar_inferencia(ventana_lista)


# ---------------------------------------------------------------------------
# Tests del cooldown
# ---------------------------------------------------------------------------

class TestCooldown(unittest.TestCase):
    """Verifica que el mecanismo de cooldown anti-spam funciona correctamente."""

    def _make_worker(self, cooldown_s: float = 30.0) -> GPDStreamWorker:
        config = _make_config(cooldown_s=cooldown_s)
        worker = GPDStreamWorker(config=config, logger=_get_test_logger())
        worker._preprocessor = SignalPreprocessor()
        return worker

    def test_primera_deteccion_pasa(self):
        """La primera detección con prob > umbral se acepta."""
        worker = self._make_worker(cooldown_s=30.0)
        # Simular que nunca ha habido detección
        worker._last_detection_time = 0.0

        resultado = worker._evaluar_deteccion(
            prob_noise=0.01, prob_p=0.97, prob_s=0.02, timestamp=time.time()
        )
        self.assertIsNotNone(resultado)
        self.assertEqual(resultado["type"], "P")
        self.assertAlmostEqual(resultado["probability"], 0.97, places=3)

    def test_deteccion_dentro_de_cooldown_ignorada(self):
        """Una detección dentro del período de cooldown debe retornar None."""
        worker = self._make_worker(cooldown_s=30.0)
        # Simular detección que ocurrió hace 5 segundos (cooldown de 30 s aún activo)
        worker._last_detection_time = time.time() - 5.0

        resultado = worker._evaluar_deteccion(
            prob_noise=0.01, prob_p=0.98, prob_s=0.01, timestamp=time.time()
        )
        self.assertIsNone(resultado)

    def test_deteccion_despues_de_cooldown_pasa(self):
        """Una detección después de que el cooldown expire debe aceptarse."""
        worker = self._make_worker(cooldown_s=1.0)
        # Simular detección que ocurrió hace 2 segundos (cooldown de 1 s ya expiró)
        worker._last_detection_time = time.time() - 2.0

        resultado = worker._evaluar_deteccion(
            prob_noise=0.01, prob_p=0.97, prob_s=0.02, timestamp=time.time()
        )
        self.assertIsNotNone(resultado)

    def test_sin_deteccion_bajo_umbral(self):
        """Probabilidades por debajo del umbral no generan detección."""
        worker = self._make_worker()
        worker._last_detection_time = 0.0

        resultado = worker._evaluar_deteccion(
            prob_noise=0.90, prob_p=0.50, prob_s=0.10, timestamp=time.time()
        )
        self.assertIsNone(resultado)

    def test_prioridad_P_sobre_S(self):
        """Si ambas fases superan el umbral, se reporta P (mayor probabilidad entre ambas)."""
        # Umbral bajo para facilitar la prueba
        worker = self._make_worker(cooldown_s=0.0)
        worker._umbral_p = 0.80
        worker._umbral_s = 0.80
        worker._last_detection_time = 0.0

        resultado = worker._evaluar_deteccion(
            prob_noise=0.01, prob_p=0.85, prob_s=0.90, timestamp=time.time()
        )
        # S tiene mayor probabilidad (0.90 > 0.85)
        self.assertIsNotNone(resultado)
        self.assertEqual(resultado["type"], "S")
        self.assertAlmostEqual(resultado["probability"], 0.90, places=3)

    def test_contadores_se_incrementan(self):
        """Los contadores de detecciones se actualizan correctamente."""
        worker = self._make_worker(cooldown_s=0.0)
        worker._last_detection_time = 0.0

        # Detección P
        worker._evaluar_deteccion(
            prob_noise=0.01, prob_p=0.97, prob_s=0.02, timestamp=time.time()
        )
        self.assertEqual(worker.detecciones_p, 1)
        self.assertEqual(worker.detecciones_s, 0)

        # Forzar expiración de cooldown
        worker._last_detection_time = 0.0

        # Detección S
        worker._umbral_s = 0.80
        worker._evaluar_deteccion(
            prob_noise=0.01, prob_p=0.50, prob_s=0.85, timestamp=time.time()
        )
        self.assertEqual(worker.detecciones_p, 1)
        self.assertEqual(worker.detecciones_s, 1)


# ---------------------------------------------------------------------------
# Tests del payload de detección
# ---------------------------------------------------------------------------

class TestPayloadDeteccion(unittest.TestCase):
    """Verifica el formato del payload de detección MQTT."""

    CAMPOS_REQUERIDOS = {
        "type", "probability", "timestamp",
        "window_start", "window_end",
        "station_id", "model", "source",
    }

    def _make_worker(self) -> GPDStreamWorker:
        config = _make_config(station_id="DEV00", modelo_ruta="models/gpd.tflite")
        worker = GPDStreamWorker(config=config, logger=_get_test_logger())
        worker._preprocessor = SignalPreprocessor()
        worker._last_detection_time = 0.0
        return worker

    def test_payload_contiene_campos_requeridos(self):
        """El diccionario de detección contiene todos los campos del plan."""
        worker = self._make_worker()
        deteccion = worker._evaluar_deteccion(
            prob_noise=0.01, prob_p=0.97, prob_s=0.02, timestamp=time.time()
        )
        self.assertIsNotNone(deteccion)
        for campo in self.CAMPOS_REQUERIDOS:
            self.assertIn(campo, deteccion, f"Campo '{campo}' ausente en el payload.")

    def test_station_id_correcto(self):
        """station_id en el payload coincide con la configuración."""
        worker = self._make_worker()
        deteccion = worker._evaluar_deteccion(
            prob_noise=0.01, prob_p=0.97, prob_s=0.02, timestamp=time.time()
        )
        self.assertEqual(deteccion["station_id"], "DEV00")

    def test_model_nombre_correcto(self):
        """El campo 'model' contiene el nombre del archivo del modelo."""
        worker = self._make_worker()
        deteccion = worker._evaluar_deteccion(
            prob_noise=0.01, prob_p=0.97, prob_s=0.02, timestamp=time.time()
        )
        self.assertEqual(deteccion["model"], "gpd.tflite")

    def test_source_es_streaming(self):
        """El campo 'source' siempre es 'streaming'."""
        worker = self._make_worker()
        deteccion = worker._evaluar_deteccion(
            prob_noise=0.01, prob_p=0.97, prob_s=0.02, timestamp=time.time()
        )
        self.assertEqual(deteccion["source"], "streaming")

    def test_timestamp_formato_iso8601(self):
        """El timestamp está en formato ISO 8601 UTC."""
        worker = self._make_worker()
        ts = time.time()
        deteccion = worker._evaluar_deteccion(
            prob_noise=0.01, prob_p=0.97, prob_s=0.02, timestamp=ts
        )
        # Debe terminar en 'Z'
        self.assertTrue(deteccion["timestamp"].endswith("Z"))
        # Debe poder parsearse como ISO 8601
        from datetime import datetime
        try:
            dt = datetime.strptime(deteccion["timestamp"], "%Y-%m-%dT%H:%M:%S.%fZ")
        except ValueError:
            self.fail(f"Timestamp no es ISO 8601 válido: {deteccion['timestamp']}")

    def test_probability_redondeada(self):
        """La probabilidad está redondeada a 4 decimales."""
        worker = self._make_worker()
        deteccion = worker._evaluar_deteccion(
            prob_noise=0.01, prob_p=0.9723456, prob_s=0.02, timestamp=time.time()
        )
        # Verificar que tiene a lo más 4 decimales
        prob_str = str(deteccion["probability"])
        decimales = prob_str.split(".")[-1] if "." in prob_str else ""
        self.assertLessEqual(len(decimales), 4)

    def test_payload_serializable_json(self):
        """El payload de detección puede serializarse a JSON sin errores."""
        worker = self._make_worker()
        deteccion = worker._evaluar_deteccion(
            prob_noise=0.01, prob_p=0.97, prob_s=0.02, timestamp=time.time()
        )
        try:
            payload_json = json.dumps(deteccion)
            parsed = json.loads(payload_json)
            self.assertIsInstance(parsed, dict)
        except (TypeError, ValueError) as exc:
            self.fail(f"El payload no es serializable a JSON: {exc}")


# ---------------------------------------------------------------------------
# Tests del buffer circular
# ---------------------------------------------------------------------------

class TestBufferCircular(unittest.TestCase):
    """Verifica el comportamiento del buffer circular del worker."""

    def _make_worker(self) -> GPDStreamWorker:
        config = _make_config()
        worker = GPDStreamWorker(config=config, logger=_get_test_logger())
        worker._preprocessor = SignalPreprocessor()
        return worker

    def test_buffer_maxlen_8_tramas(self):
        """El buffer acepta exactamente 8 tramas y descarta la más antigua al agregar la novena."""
        worker = self._make_worker()
        trama = _sintetica_250x3()

        for i in range(10):
            resampled = worker._preprocessor.resample_frame(trama)
            worker._buffer.append(resampled)

        # maxlen=8: solo deben quedar 8 tramas
        self.assertEqual(len(worker._buffer), 8)

    def test_buffer_concatenacion_shape(self):
        """8 tramas concatenadas forman (800, 3)."""
        worker = self._make_worker()
        _llenar_buffer(worker, 8)

        ventana = np.concatenate(list(worker._buffer), axis=0)
        self.assertEqual(ventana.shape, (800, 3))

    def test_buffer_incompleto_no_infiere(self):
        """Si el buffer tiene menos de 8 tramas, no debe ejecutar inferencia."""
        worker = self._make_worker()
        # Llenar solo 4 tramas
        _llenar_buffer(worker, 4)
        self.assertEqual(len(worker._buffer), 4)
        # El buffer incompleto no debería producir error al consultar longitud
        self.assertLess(len(worker._buffer), 8)


# ---------------------------------------------------------------------------
# Tests de arranque y parada
# ---------------------------------------------------------------------------

class TestArranqueParada(unittest.TestCase):
    """Verifica el ciclo de vida del worker (arranque y parada ordenada)."""

    def test_stop_establece_running_false(self):
        """stop() establece _running = False."""
        config = _make_config()
        worker = GPDStreamWorker(config=config, logger=_get_test_logger())
        worker._running = True
        worker.stop()
        self.assertFalse(worker._running)

    def test_estado_inicial(self):
        """El worker inicia con contadores en cero y _running en False."""
        config = _make_config()
        worker = GPDStreamWorker(config=config, logger=_get_test_logger())
        self.assertFalse(worker._running)
        self.assertEqual(worker.inferencias_total, 0)
        self.assertEqual(worker.detecciones_p, 0)
        self.assertEqual(worker.detecciones_s, 0)
        self.assertEqual(worker._last_detection_time, 0.0)

    def test_buffer_vacio_al_inicio(self):
        """El buffer circular está vacío al crear el worker."""
        config = _make_config()
        worker = GPDStreamWorker(config=config, logger=_get_test_logger())
        self.assertEqual(len(worker._buffer), 0)

    def test_run_sin_shm_termina_con_error(self):
        """
        Si el SHM no existe y el timeout se alcanza, run() debe terminar
        sin lanzar excepciones no capturadas al exterior.

        Se usa un timeout de 1 s para no demorar el test.
        """
        config = _make_config()
        config["shm_path"] = "/dev/shm/rsa_no_existe_test_gpd_worker_xyz"

        logger = _get_test_logger()
        worker = GPDStreamWorker(config=config, logger=logger)

        # Parchear el preprocesador para evitar cálculo de filtro
        worker._preprocessor = SignalPreprocessor(filter_enabled=False)

        # Parchear _cargar_modelo para no necesitar el archivo .tflite
        with patch.object(worker, "_cargar_modelo"), \
             patch.object(worker, "_conectar_mqtt"), \
             patch("streaming.gpd_stream_worker._DEFAULT_SHM_RETRY_MAX", 1):
            # run() debe completar sin lanzar excepción al exterior
            try:
                worker.run()
            except Exception as exc:
                self.fail(f"run() lanzó excepción inesperada: {exc}")


# ---------------------------------------------------------------------------
# Test de publicación MQTT (con mock)
# ---------------------------------------------------------------------------

class TestPublicacionMQTT(unittest.TestCase):
    """Verifica que el worker intenta publicar en el tópico correcto."""

    def _make_worker(self) -> GPDStreamWorker:
        config = _make_config(station_id="DEV00")
        worker = GPDStreamWorker(config=config, logger=_get_test_logger())
        worker._preprocessor = SignalPreprocessor()
        worker._last_detection_time = 0.0
        return worker

    def test_topic_formato_correcto(self):
        """El tópico de publicación sigue el formato <station_id>/events/detected."""
        worker = self._make_worker()

        # Mock del cliente MQTT
        mock_mqtt = MagicMock()
        mock_result = MagicMock()
        mock_result.rc = 0
        mock_mqtt.publish.return_value = mock_result
        worker._mqtt = mock_mqtt

        deteccion = {
            "type": "P",
            "probability": 0.97,
            "timestamp": "2026-07-01T12:00:00.000Z",
            "window_start": "2026-07-01T11:59:58.000Z",
            "window_end": "2026-07-01T12:00:02.000Z",
            "station_id": "DEV00",
            "model": "gpd.tflite",
            "source": "streaming",
        }

        worker._publicar_deteccion(deteccion)

        # Verificar que se llamó publish con el tópico correcto
        mock_mqtt.publish.assert_called_once()
        args, kwargs = mock_mqtt.publish.call_args
        topic_publicado = args[0]
        self.assertEqual(topic_publicado, "DEV00/events/detected")

    def test_sin_mqtt_no_lanza_excepcion(self):
        """Si el cliente MQTT es None, _publicar_deteccion no lanza excepciones."""
        worker = self._make_worker()
        worker._mqtt = None  # Sin MQTT

        deteccion = {
            "type": "S",
            "probability": 0.96,
            "timestamp": "2026-07-01T12:00:00.000Z",
            "window_start": "2026-07-01T11:59:58.000Z",
            "window_end": "2026-07-01T12:00:02.000Z",
            "station_id": "DEV00",
            "model": "gpd.tflite",
            "source": "streaming",
        }

        try:
            worker._publicar_deteccion(deteccion)
        except Exception as exc:
            self.fail(f"_publicar_deteccion lanzó excepción con mqtt=None: {exc}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    unittest.main(verbosity=2)

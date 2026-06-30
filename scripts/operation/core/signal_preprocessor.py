"""
signal_preprocessor.py — Módulo de preprocesamiento de señal para inferencia GPD.

Se encarga de transformar los datos crudos del acelerógrafo (250 Hz, int32)
al formato esperado por el modelo GPD (100 Hz, float32, normalizado).
Implementa downsampling polifásico (250 Hz -> 100 Hz), filtrado pasabanda
Butterworth y normalización por canal.
"""

import numpy as np
from scipy.signal import butter, sosfiltfilt, resample_poly
from typing import Optional

# Constantes del modelo GPD
GPD_SAMPLE_RATE = 100       # Hz
GPD_WINDOW_SAMPLES = 400    # 4 segundos
GPD_AXES = 3
RAW_SAMPLE_RATE = 250       # Hz


class SignalPreprocessor:
    """
    Preprocesador de señal para el pipeline GPD en tiempo real.
    """

    def __init__(
        self,
        raw_sample_rate: int = RAW_SAMPLE_RATE,
        target_sample_rate: int = GPD_SAMPLE_RATE,
        filter_enabled: bool = True,
        freq_min: float = 3.0,
        freq_max: float = 20.0,
        filter_order: int = 4,
    ):
        """
        Args:
            raw_sample_rate:    Frecuencia de muestreo de entrada (Hz).
            target_sample_rate: Frecuencia de muestreo de salida (Hz).
            filter_enabled:     Si True, aplica filtro pasabanda.
            freq_min:           Frecuencia mínima del pasabanda (Hz).
            freq_max:           Frecuencia máxima del pasabanda (Hz).
            filter_order:       Orden del filtro Butterworth.
        """
        self._raw_sample_rate = raw_sample_rate
        self._target_sample_rate = target_sample_rate
        self._filter_enabled = filter_enabled
        self._freq_min = freq_min
        self._freq_max = freq_max
        self._filter_order = filter_order

        # Inicializar coeficientes del filtro SOS si está habilitado
        if self._filter_enabled:
            nyquist = 0.5 * self._target_sample_rate
            low = self._freq_min / nyquist
            high = self._freq_max / nyquist

            # Validar frecuencias de corte
            if not (0 < low < 1) or not (0 < high < 1) or (low >= high):
                raise ValueError(
                    f"Frecuencias de filtro inválidas para Nyquist={nyquist} Hz: "
                    f"freq_min={freq_min}, freq_max={freq_max}"
                )

            # Usamos Second-Order Sections (SOS) por estabilidad numérica
            self._sos = butter(self._filter_order, [low, high], btype='band', output='sos')

    def resample_frame(self, samples: np.ndarray) -> np.ndarray:
        """
        Resamplea una trama de 250 muestras a 100 muestras por eje.
        Usa scipy.signal.resample_poly con factor up=2, down=5 (250 * 2/5 = 100).

        Args:
            samples: ndarray (250, 3) int32 — muestras crudas.

        Returns:
            ndarray (100, 3) float64 — muestras resampleadas a 100 Hz.
        """
        if samples.shape[0] != self._raw_sample_rate:
            # Si el tamaño de la trama no es exactamente 250, resample_poly sigue funcionando
            # pero calculamos los factores dinámicamente o alertamos.
            pass

        # up=2, down=5 para pasar de 250 Hz a 100 Hz
        return resample_poly(samples, 2, 5, axis=0)

    def apply_filter(self, data: np.ndarray) -> np.ndarray:
        """
        Aplica filtro pasabanda Butterworth SOS de fase cero (sosfiltfilt)
        a lo largo de las columnas (axis=0).

        Args:
            data: ndarray (N, 3) float — muestras a 100 Hz a filtrar.

        Returns:
            ndarray (N, 3) float — datos filtrados.
        """
        if not self._filter_enabled:
            return data

        # sosfiltfilt aplica el filtro hacia adelante y hacia atrás (fase cero)
        # para evitar retraso de grupo en los tiempos de arribo de fase.
        return sosfiltfilt(self._sos, data, axis=0)

    def normalize_window(self, window: np.ndarray) -> np.ndarray:
        """
        Normaliza una ventana de datos para la entrada del modelo GPD.
        Divide cada canal por su valor absoluto máximo (normalización per-channel)
        añadiendo un epsilon para evitar divisiones por cero.

        Args:
            window: ndarray (N, 3) float — ventana a normalizar.

        Returns:
            ndarray (N, 3) float32 — ventana normalizada.
        """
        max_vals = np.max(np.abs(window), axis=0, keepdims=True) + 1e-9
        normalized = window / max_vals
        return normalized.astype(np.float32)

    def prepare_window(self, window_raw_100hz: np.ndarray) -> np.ndarray:
        """
        Prepara la ventana completa para inferencia: filtrado pasabanda + normalización.

        Soporta la Opción A: Filtrar con padding.
        Si la entrada tiene 800 muestras (8 segundos a 100 Hz), filtra las 800 muestras
        completas y extrae las 400 muestras centrales (4 segundos) limpias de
        efectos transitorios de borde del filtro.

        Si tiene 400 muestras, aplica el filtro directamente sobre ellas.

        Args:
            window_raw_100hz: ndarray (N, 3) float — muestras acumuladas a 100 Hz.

        Returns:
            ndarray (1, 400, 3) float32 — tensor listo para inferencia TFLite.
        """
        n_samples = window_raw_100hz.shape[0]

        # 1. Aplicar filtro a toda la ventana acumulada
        if self._filter_enabled:
            filtered = self.apply_filter(window_raw_100hz)
        else:
            filtered = window_raw_100hz

        # 2. Recortar la ventana de inferencia de 400 muestras (4 segundos)
        if n_samples == 800:
            # Opción A: Extraer las 400 muestras centrales (segundos 2 a 6)
            # Evita los transitorios de borde al inicio (0-2s) y al final (6-8s)
            window = filtered[200:600, :]
        elif n_samples == 400:
            window = filtered
        else:
            if n_samples > GPD_WINDOW_SAMPLES:
                # Recorte central genérico
                start = (n_samples - GPD_WINDOW_SAMPLES) // 2
                window = filtered[start:start + GPD_WINDOW_SAMPLES, :]
            else:
                raise ValueError(
                    f"Se requieren al menos {GPD_WINDOW_SAMPLES} muestras para preparar la ventana, "
                    f"obtenidas: {n_samples}"
                )

        # 3. Normalizar por canal
        normalized = self.normalize_window(window)

        # 4. Añadir dimensión de batch: (1, 400, 3)
        return np.expand_dims(normalized, axis=0)

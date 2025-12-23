import numpy as np
import logging
import time
import gc
from tflite_runtime.interpreter import Interpreter
from obspy import Stream, Trace
from .seismic_pick import SeismicPick

class GPDInferenceEngine:
    """
    Motor de inferencia GPD (Generalized Phase Detection) optimizado para TFLite.
    Maneja el resampleo de 250Hz a 100Hz y la detección de fases P/S.
    """

    def __init__(self, model_path, config=None, logger=None):
        self.logger = logger or logging.getLogger(__name__)
        self.config = config or {}
        
        # Parámetros por defecto
        self.min_proba = self.config.get("min_probability", 0.95)
        self.freq_min = self.config.get("freq_min", 3.0)
        self.freq_max = self.config.get("freq_max", 20.0)
        self.batch_size = self.config.get("batch_size", 100)
        self.num_threads = self.config.get("num_threads", 2)
        
        # Parámetros del modelo (fijos para GPD v2)
        self.n_feat = 400
        self.n_shift = 10
        self.sampling_rate_model = 100.0
        
        # Inicializar intérprete TFLite
        self.logger.info(f"Cargando modelo GPD TFLite desde: {model_path}")
        try:
            self.interpreter = Interpreter(model_path=model_path, num_threads=self.num_threads)
            self.interpreter.allocate_tensors()
            self.input_details = self.interpreter.get_input_details()[0]
            self.output_details = self.interpreter.get_output_details()[0]
            
            # Ajustar tensor de entrada al batch_size
            self.interpreter.resize_tensor_input(self.input_details["index"], [self.batch_size, self.n_feat, 3])
            self.interpreter.allocate_tensors()
            self.input_details = self.interpreter.get_input_details()[0]
            self.output_details = self.interpreter.get_output_details()[0]
            
            self.logger.info(f"Modelo cargado OK. Input shape: {self.input_details['shape']}")
        except Exception as e:
            self.logger.error(f"Error cargando modelo TFLite: {e}")
            raise

    def pre_process(self, stream):
        """Pre-procesamiento: filtrado y resampleo a 100Hz"""
        st = stream.copy()
        
        # 1. Detrend y Filtro
        st.detrend('linear')
        st.filter('bandpass', freqmin=self.freq_min, freqmax=self.freq_max)
        
        # 2. Resampleo a 100Hz (requerido por GPD)
        for tr in st:
            if abs(tr.stats.sampling_rate - self.sampling_rate_model) > 0.1:
                tr.resample(self.sampling_rate_model)
        
        return st

    def _sliding_window(self, data, size, step):
        """Genera ventanas deslizantes eficientes"""
        if size > data.size:
            return np.array([])
        
        shape = (int((data.size - size) / step + 1), size)
        strides = (data.strides[0] * step, data.strides[0])
        return np.lib.stride_tricks.as_strided(data, shape=shape, strides=strides)

    def process_stream(self, stream):
        """
        Procesa un Stream de 3 canales y devuelve picks detectados.
        """
        if len(stream) != 3:
            self.logger.warning(f"Se esperaba stream de 3 canales, recibidos: {len(stream)}")
            return []

        # 1. Pre-procesar
        st_proc = self.pre_process(stream)
        
        # Sincronizar tiempos
        latest_start = max(tr.stats.starttime for tr in st_proc)
        earliest_stop = min(tr.stats.endtime for tr in st_proc)
        st_proc.trim(latest_start, earliest_stop)
        
        if st_proc[0].stats.npts < self.n_feat:
            return []

        # 2. Ventaneo
        data_N = self._sliding_window(st_proc[0].data, self.n_feat, self.n_shift)
        data_E = self._sliding_window(st_proc[1].data, self.n_feat, self.n_shift)
        data_Z = self._sliding_window(st_proc[2].data, self.n_feat, self.n_shift)
        
        num_windows = min(len(data_N), len(data_E), len(data_Z))
        if num_windows == 0:
            return []

        # 3. Inferencia por batches
        picks = []
        dt = 1.0 / self.sampling_rate_model
        
        # Buffer para batch
        batch_buf = np.zeros((self.batch_size, self.n_feat, 3), dtype=np.float32)
        
        for i in range(0, num_windows, self.batch_size):
            k = min(self.batch_size, num_windows - i)
            
            # Preparar batch y normalizar
            for j in range(k):
                win = np.stack([data_N[i+j], data_E[i+j], data_Z[i+j]], axis=-1).astype(np.float32)
                # Normalización estándar por ventana
                max_val = np.max(np.abs(win)) + 1e-9
                batch_buf[j] = win / max_val
            
            # Ejecutar modelo
            self.interpreter.set_tensor(self.input_details["index"], batch_buf)
            self.interpreter.invoke()
            output = self.interpreter.get_tensor(self.output_details["index"])
            
            # Analizar resultados del batch
            for j in range(k):
                prob_P = output[j, 0]
                prob_S = output[j, 1]
                
                # Tiempo del centro de la ventana
                # GPD v2 usa ventanas de 4s (400 muestras), el pick suele estar en el centro o final
                # Aquí usamos el tiempo relativo al inicio del stream
                time_offset = (i + j) * self.n_shift * dt + (self.n_feat / 2) * dt
                pick_time = latest_start + time_offset
                
                if prob_P > self.min_proba:
                    picks.append(SeismicPick(
                        network=st_proc[0].stats.network,
                        station=st_proc[0].stats.station,
                        phase='P',
                        time=pick_time,
                        probability=float(prob_P),
                        channel=st_proc[0].stats.channel
                    ))
                
                if prob_S > self.min_proba:
                    picks.append(SeismicPick(
                        network=st_proc[0].stats.network,
                        station=st_proc[0].stats.station,
                        phase='S',
                        time=pick_time,
                        probability=float(prob_S),
                        channel=st_proc[0].stats.channel
                    ))

        # Limpieza
        del st_proc, data_N, data_E, data_Z
        gc.collect()
        
        return self._filter_picks(picks)

    def _filter_picks(self, picks):
        """Simplifica picks cercanos (evita duplicados por ventana deslizante)"""
        if not picks:
            return []
        
        # Ordenar por tiempo
        picks.sort(key=lambda x: x.time)
        
        filtered = []
        if not picks: return []
        
        last_pick = picks[0]
        temp_group = [last_pick]
        
        for current in picks[1:]:
            # Si están a menos de 0.5s y son la misma fase, agrúpalos
            if (current.time - last_pick.time) < 0.5 and current.phase == last_pick.phase:
                temp_group.append(current)
            else:
                # Elegir el de mayor probabilidad del grupo anterior
                filtered.append(max(temp_group, key=lambda x: x.probability))
                temp_group = [current]
            last_pick = current
            
        filtered.append(max(temp_group, key=lambda x: x.probability))
        return filtered

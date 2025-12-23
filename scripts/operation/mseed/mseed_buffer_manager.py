"""
Sistema de gestión de buffer circular para datos sísmicos en formato miniSEED

Este script proporciona:
1. Lectura continua desde named pipe del sistema de registro continuo
2. Conversión de tramas binarias a formato miniSEED en memoria
3. Buffer circular thread-safe para almacenamiento temporal
4. Extracción de ventanas temporales configurables

EJEMPLOS DE USO:

1. Modo daemon (lectura continua):
   python3 mseed_buffer_manager.py --daemon

2. Modo daemon con configuración personalizada:
   python3 mseed_buffer_manager.py --daemon --buffer-size 3600 --window-duration 60

3. Modo extracción de ventana:
   python3 mseed_buffer_manager.py --extract-window 300 --output ventana_5min.mseed

CONFIGURACIÓN:

- buffer_size: Tamaño del buffer en segundos (default: 1800 = 30 minutos)
- window_duration: Duración de ventanas para exportación (default: 60 segundos)

REQUISITOS:

- Named pipe debe existir en: /tmp/my_pipe
- Variables de entorno: PROJECT_LOCAL_ROOT
- Archivos de configuración: configuracion_dispositivo.json, configuracion_mseed.json
"""

######################################### ~Librerías~ #################################################
import numpy as np
from obspy import UTCDateTime, Trace, Stream
import os
import sys
import json
import logging
import datetime
import argparse
import threading
import time
from collections import deque
from threading import Lock, Event
import signal
from pathlib import Path
from .gpd_inference_engine import GPDInferenceEngine
from .seismic_pick import SeismicPick
#######################################################################################################

##################################### ~Constantes globales~ ############################################
PIPE_NAME = "/tmp/my_pipe"
TRAMA_SIZE = 2506  # Tamaño de cada trama en bytes
SAMPLES_PER_SECOND = 250  # Muestras por segundo por canal
NUM_CHANNELS = 3  # Número de canales (X, Y, Z)
#######################################################################################################

##################################### ~Módulo 1: Lector de Named Pipe~ #################################
class PipeReader(threading.Thread):
    """
    Módulo encargado de leer continuamente del named pipe generado por registro_continuo.c

    Características:
    - Lectura no bloqueante del pipe
    - Manejo robusto de desconexiones del escritor
    - Validación de tamaño de tramas
    - Callback para procesar cada trama recibida
    """

    def __init__(self, pipe_path=PIPE_NAME, callback=None, logger=None):
        """
        Inicializa el lector de pipe

        Args:
            pipe_path: Ruta del named pipe
            callback: Función a llamar con cada trama leída (debe aceptar bytes)
            logger: Logger para mensajes
        """
        super().__init__(daemon=True)
        self.pipe_path = pipe_path
        self.callback = callback
        self.logger = logger or logging.getLogger(__name__)
        self.running = Event()
        self.running.set()
        self.stats = {
            'tramas_recibidas': 0,
            'tramas_invalidas': 0,
            'bytes_recibidos': 0,
            'ultima_trama': None
        }

    def run(self):
        """Bucle principal de lectura del pipe"""
        self.logger.info(f"Iniciando lector de pipe: {self.pipe_path}")

        while self.running.is_set():
            try:
                # Verificar que el pipe existe
                if not os.path.exists(self.pipe_path):
                    self.logger.error(f"Named pipe no existe: {self.pipe_path}")
                    time.sleep(5)
                    continue

                # Abrir pipe en modo lectura (bloqueante hasta que haya escritor)
                self.logger.info(f"Esperando escritor en pipe: {self.pipe_path}")
                with open(self.pipe_path, 'rb') as pipe:
                    self.logger.info("Escritor conectado. Iniciando lectura...")

                    while self.running.is_set():
                        # Leer una trama completa
                        trama = pipe.read(TRAMA_SIZE)

                        if not trama:
                            # El escritor se desconectó
                            self.logger.warning("Escritor desconectado del pipe")
                            break

                        if len(trama) != TRAMA_SIZE:
                            self.logger.warning(
                                f"Trama incompleta recibida: {len(trama)} bytes "
                                f"(esperado: {TRAMA_SIZE})"
                            )
                            self.stats['tramas_invalidas'] += 1
                            continue

                        # Actualizar estadísticas
                        self.stats['tramas_recibidas'] += 1
                        self.stats['bytes_recibidos'] += len(trama)
                        self.stats['ultima_trama'] = datetime.datetime.now()

                        # Procesar trama mediante callback
                        if self.callback:
                            try:
                                self.callback(trama)
                            except Exception as e:
                                self.logger.error(f"Error en callback de trama: {e}", exc_info=True)

                        # Log periódico de estadísticas
                        if self.stats['tramas_recibidas'] % 100 == 0:
                            self.logger.debug(
                                f"Tramas procesadas: {self.stats['tramas_recibidas']}, "
                                f"Inválidas: {self.stats['tramas_invalidas']}"
                            )

            except FileNotFoundError:
                self.logger.error(f"Pipe no encontrado: {self.pipe_path}")
                time.sleep(5)
            except Exception as e:
                self.logger.error(f"Error en lector de pipe: {e}", exc_info=True)
                time.sleep(1)

        self.logger.info("Lector de pipe detenido")

    def stop(self):
        """Detiene el hilo de lectura"""
        self.logger.info("Deteniendo lector de pipe...")
        self.running.clear()

    def get_stats(self):
        """Retorna estadísticas de lectura"""
        return self.stats.copy()

#######################################################################################################

################################ ~Módulo 2: Conversor de Tramas a MiniSEED~ ###########################
class TramaToMiniSEEDConverter:
    """
    Módulo encargado de convertir tramas binarias a formato miniSEED en memoria

    Características:
    - Decodificación de tramas de 2506 bytes
    - Extracción de timestamp y datos de 3 canales
    - Conversión a formato ObsPy Trace en memoria (sin I/O de disco)
    - Validación de datos
    """

    def __init__(self, config_mseed, logger=None):
        """
        Inicializa el conversor

        Args:
            config_mseed: Diccionario con configuración miniSEED
            logger: Logger para mensajes
        """
        self.config = config_mseed
        self.logger = logger or logging.getLogger(__name__)
        self.sampling_rate = int(config_mseed.get("MUESTREO(20)", 250))
        self.stats_template = self._create_stats_template()

    def _create_stats_template(self):
        """Crea plantilla de metadatos SEED"""
        return {
            'network': self.config.get("RED(19)", "XX"),
            'station': self.config.get("CODIGO(1)", "UNKN"),
            'location': str(self.config.get("UBICACION(17)", "00")),
            'sampling_rate': self.sampling_rate,
            'mseed': {'dataquality': self.config.get("CALIDAD(16)", "D")}
        }

    def parse_trama(self, trama_bytes):
        """
        Parsea una trama binaria y extrae timestamp y datos

        Args:
            trama_bytes: Bytes de la trama (2506 bytes)

        Returns:
            dict con keys: 'timestamp', 'data' (array 3xN), 'valid'
        """
        if len(trama_bytes) != TRAMA_SIZE:
            self.logger.warning(f"Trama con tamaño incorrecto: {len(trama_bytes)}")
            return {'valid': False}

        try:
            # Convertir a numpy array
            trama = np.frombuffer(trama_bytes, dtype=np.uint8)

            # Extraer timestamp (últimos 6 bytes)
            anio = int(trama[2500]) + 2000
            mes = int(trama[2501])
            dia = int(trama[2502])
            hora = int(trama[2503])
            minuto = int(trama[2504])
            segundo = int(trama[2505])

            # Validar timestamp
            if not self._validate_timestamp(anio, mes, dia, hora, minuto, segundo):
                self.logger.warning(
                    f"Timestamp inválido: {anio:04d}-{mes:02d}-{dia:02d} "
                    f"{hora:02d}:{minuto:02d}:{segundo:02d}"
                )
                return {'valid': False}

            # Crear objeto UTCDateTime
            timestamp = UTCDateTime(anio, mes, dia, hora, minuto, segundo)

            # Extraer datos de los 3 canales (primeros 2500 bytes)
            datos_crudos = trama[:2500].reshape((250, 10))
            datos_canales = np.zeros((3, 250), dtype=np.int32)

            for canal in range(3):
                dato_1 = datos_crudos[:, canal * 3 + 1].astype(np.uint32)
                dato_2 = datos_crudos[:, canal * 3 + 2].astype(np.uint32)
                dato_3 = datos_crudos[:, canal * 3 + 3].astype(np.uint32)

                # Reconstruir valor de 20 bits
                xValue = ((dato_1 << 12) & 0xFF000) + \
                         ((dato_2 << 4) & 0xFF0) + \
                         ((dato_3 >> 4) & 0xF)

                # Convertir a complemento a 2 si es necesario
                mask = xValue >= 0x80000
                xValue[mask] = -1 * ((~xValue[mask] + 1) & 0x7FFFF)

                datos_canales[canal] = xValue.astype(np.int32)

            return {
                'valid': True,
                'timestamp': timestamp,
                'data': datos_canales,
                'year': anio,
                'month': mes,
                'day': dia,
                'hour': hora,
                'minute': minuto,
                'second': segundo
            }

        except Exception as e:
            self.logger.error(f"Error parseando trama: {e}", exc_info=True)
            return {'valid': False}

    def _validate_timestamp(self, year, month, day, hour, minute, second):
        """Valida componentes de timestamp"""
        return (2000 <= year <= 2100 and
                1 <= month <= 12 and
                1 <= day <= 31 and
                0 <= hour <= 23 and
                0 <= minute <= 59 and
                0 <= second <= 59)

    def trama_to_traces(self, trama_bytes):
        """
        Convierte una trama binaria a 3 objetos Trace (uno por canal)

        Args:
            trama_bytes: Bytes de la trama

        Returns:
            list de 3 Trace objects, o None si la trama es inválida
        """
        parsed = self.parse_trama(trama_bytes)

        if not parsed['valid']:
            return None

        traces = []
        channel_codes = self._get_channel_codes()

        for i, channel_code in enumerate(channel_codes):
            stats = self.stats_template.copy()
            stats['channel'] = channel_code
            stats['starttime'] = parsed['timestamp']
            stats['npts'] = len(parsed['data'][i])

            trace = Trace(data=parsed['data'][i], header=stats)
            traces.append(trace)

        return traces

    def _get_channel_codes(self):
        """Genera códigos de canal según convención SEED"""
        # Prefijo según frecuencia de muestreo
        prefix = 'E' if self.sampling_rate > 80 else 'S'

        # Tipo de instrumento
        instrument = 'L' if self.config.get("SENSOR(2)") == 'SISMICO' else 'N'

        # Orientaciones
        orientaciones = self.config.get("CANAL(18)", "ZNE")

        return [f"{prefix}{instrument}{orientaciones[i]}" for i in range(3)]

#######################################################################################################

############################ ~Módulo 3: Buffer Circular Thread-Safe~ ##################################
class CircularMiniSEEDBuffer:
    """
    Buffer circular para almacenamiento temporal de datos miniSEED

    Características:
    - Thread-safe mediante locks
    - Capacidad configurable en segundos de datos
    - Almacena Traces de ObsPy en memoria
    - Extracción de ventanas temporales
    - Rotación automática cuando se llena
    """

    def __init__(self, capacity_seconds=1800, sampling_rate=250, logger=None):
        """
        Inicializa el buffer circular

        Args:
            capacity_seconds: Capacidad del buffer en segundos
            sampling_rate: Tasa de muestreo en Hz
            logger: Logger para mensajes
        """
        self.capacity_seconds = capacity_seconds
        self.sampling_rate = sampling_rate
        self.logger = logger or logging.getLogger(__name__)

        # Buffer para cada canal (deque es thread-safe para append/popleft)
        self.buffers = {
            'channel_0': deque(maxlen=capacity_seconds),
            'channel_1': deque(maxlen=capacity_seconds),
            'channel_2': deque(maxlen=capacity_seconds)
        }

        # Índice de timestamps para búsqueda rápida
        self.timestamp_index = deque(maxlen=capacity_seconds)

        # Lock para operaciones que requieren consistencia entre canales
        self.lock = Lock()

        # Estadísticas
        self.stats = {
            'tramas_agregadas': 0,
            'bytes_almacenados': 0,
            'rotaciones': 0,
            'primer_timestamp': None,
            'ultimo_timestamp': None
        }

        self.logger.info(
            f"Buffer circular inicializado: capacidad={capacity_seconds}s, "
            f"sampling_rate={sampling_rate}Hz"
        )

    def add_traces(self, traces):
        """
        Agrega 3 traces (uno por canal) al buffer

        Args:
            traces: Lista de 3 objetos Trace de ObsPy
        """
        if not traces or len(traces) != 3:
            self.logger.warning(f"Número incorrecto de traces: {len(traces) if traces else 0}")
            return

        with self.lock:
            try:
                timestamp = traces[0].stats.starttime

                # Agregar cada trace a su buffer correspondiente
                for i, trace in enumerate(traces):
                    self.buffers[f'channel_{i}'].append(trace)

                # Agregar timestamp al índice
                self.timestamp_index.append(timestamp)

                # Actualizar estadísticas
                self.stats['tramas_agregadas'] += 1
                self.stats['bytes_almacenados'] += sum(trace.data.nbytes for trace in traces)

                if self.stats['primer_timestamp'] is None:
                    self.stats['primer_timestamp'] = timestamp
                self.stats['ultimo_timestamp'] = timestamp

                # Detectar rotación del buffer
                if len(self.timestamp_index) == self.capacity_seconds:
                    self.stats['rotaciones'] += 1
                    if self.stats['rotaciones'] % 10 == 0:
                        self.logger.debug(
                            f"Buffer rotado {self.stats['rotaciones']} veces. "
                            f"Rango temporal: {self.get_time_range()}"
                        )

            except Exception as e:
                self.logger.error(f"Error agregando traces al buffer: {e}", exc_info=True)

    def extract_window(self, duration_seconds=60, end_time=None):
        """
        Extrae una ventana temporal del buffer

        Args:
            duration_seconds: Duración de la ventana en segundos
            end_time: Tiempo final de la ventana (UTCDateTime). Si None, usa el último dato

        Returns:
            Stream de ObsPy con los datos de la ventana, o None si no hay suficientes datos
        """
        with self.lock:
            if not self.timestamp_index:
                self.logger.warning("Buffer vacío, no se puede extraer ventana")
                return None

            # Determinar tiempo final
            if end_time is None:
                end_time = self.timestamp_index[-1]

            # Determinar tiempo inicial
            start_time = end_time - duration_seconds

            # Buscar índices de inicio y fin
            start_idx = None
            end_idx = None

            for i, ts in enumerate(self.timestamp_index):
                if start_idx is None and ts >= start_time:
                    start_idx = i
                if ts <= end_time:
                    end_idx = i

            if start_idx is None or end_idx is None:
                self.logger.warning(
                    f"No se encontraron datos suficientes para ventana "
                    f"[{start_time} - {end_time}]"
                )
                return None

            # Extraer traces de cada canal
            stream = Stream()

            try:
                for channel_key in ['channel_0', 'channel_1', 'channel_2']:
                    # Obtener lista de traces en el rango
                    channel_buffer = list(self.buffers[channel_key])
                    traces_in_window = channel_buffer[start_idx:end_idx + 1]

                    if not traces_in_window:
                        continue

                    # Combinar traces en uno solo si hay múltiples
                    if len(traces_in_window) == 1:
                        combined_trace = traces_in_window[0].copy()
                    else:
                        # Crear Stream temporal y mergear
                        temp_stream = Stream(traces=traces_in_window)
                        temp_stream.merge(method=0, fill_value=0)  # method=0: sin interpolación
                        combined_trace = temp_stream[0].copy()

                    # Recortar al tiempo exacto solicitado
                    combined_trace.trim(starttime=start_time, endtime=end_time, pad=True, fill_value=0)

                    stream.append(combined_trace)

                self.logger.info(
                    f"Ventana extraída: {duration_seconds}s, "
                    f"{len(stream)} canales, "
                    f"rango: [{start_time} - {end_time}]"
                )

                return stream

            except Exception as e:
                self.logger.error(f"Error extrayendo ventana: {e}", exc_info=True)
                return None

    def get_time_range(self):
        """Retorna el rango temporal actual del buffer"""
        with self.lock:
            if not self.timestamp_index:
                return None
            return (self.timestamp_index[0], self.timestamp_index[-1])

    def get_stats(self):
        """Retorna estadísticas del buffer"""
        with self.lock:
            stats = self.stats.copy()
            stats['tamanio_actual'] = len(self.timestamp_index)
            stats['rango_temporal'] = self.get_time_range()
            return stats

    def clear(self):
        """Limpia el buffer"""
        with self.lock:
            for channel_key in self.buffers:
                self.buffers[channel_key].clear()
            self.timestamp_index.clear()
            self.stats['primer_timestamp'] = None
            self.stats['ultimo_timestamp'] = None
            self.logger.info("Buffer limpiado")

#######################################################################################################

############################ ~Módulo 5: Hilo de Inferencia GPD~ #######################################
class GPDInferenceThread(threading.Thread):
    """
    Hilo especializado en ejecutar la inferencia GPD periódicamente
    sobre los datos contenidos en el buffer circular.
    """

    def __init__(self, buffer, engine, interval_seconds=10, window_duration=60, 
                 picks_file=None, logger=None):
        """
        Inicializa el hilo de inferencia
        """
        super().__init__(daemon=True)
        self.buffer = buffer
        self.engine = engine
        self.interval = interval_seconds
        self.window_duration = window_duration
        self.picks_file = picks_file
        self.logger = logger or logging.getLogger(__name__)
        self.running = Event()
        self.running.set()

    def run(self):
        self.logger.info(
            f"Hilo de inferencia GPD iniciado. Intervalo: {self.interval}s, "
            f"Ventana: {self.window_duration}s"
        )

        while self.running.is_set():
            try:
                # Esperar el intervalo
                time.sleep(self.interval)

                # Extraer ventana del buffer
                # Nota: extract_window ya usa el Lock del buffer
                stream = self.buffer.extract_window(duration_seconds=self.window_duration)

                if stream and len(stream) == 3:
                    # Ejecutar inferencia
                    start_inf = time.perf_counter()
                    picks = self.engine.process_stream(stream)
                    duration = time.perf_counter() - start_inf

                    if picks:
                        self.logger.info(f"¡Detección GPD! {len(picks)} picks encontrados en {duration:.2f}s")
                        self._save_picks(picks)
                    else:
                        self.logger.debug(f"Inferencia completada en {duration:.2f}s. Sin detecciones.")
                else:
                    self.logger.debug("Buffer insuficiente para la ventana de inferencia")

            except Exception as e:
                self.logger.error(f"Error en hilo de inferencia: {e}", exc_info=True)

    def _save_picks(self, picks):
        """Guarda los picks en el archivo configurado"""
        if not self.picks_file:
            return

        try:
            with open(self.picks_file, 'a') as f:
                for pick in picks:
                    f.write(pick.to_line() + "\n")
        except Exception as e:
            self.logger.error(f"Error guardando picks: {e}")

    def stop(self):
        """Detiene el hilo"""
        self.logger.info("Deteniendo hilo de inferencia...")
        self.running.clear()

#######################################################################################################

############################ ~Módulo 4: Coordinador Principal~ ########################################
class MiniSEEDBufferManager:
    """
    Coordinador principal que integra todos los módulos

    Características:
    - Orquesta la lectura del pipe, conversión y almacenamiento en buffer
    - Exportación periódica de ventanas temporales
    - Manejo de señales para shutdown limpio
    """

    def __init__(self, config_mseed, buffer_size=1800, window_duration=60, 
                 inference_config=None, logger=None):
        """
        Inicializa el gestor

        Args:
            config_mseed: Configuración miniSEED
            buffer_size: Tamaño del buffer en segundos
            window_duration: Duración de ventanas para exportación
            inference_config: Diccionario con configuración de inferencia GPD (opcional)
            logger: Logger
        """
        self.logger = logger or logging.getLogger(__name__)
        self.config_mseed = config_mseed
        self.buffer_size = buffer_size
        self.window_duration = window_duration
        self.inference_config = inference_config

        # Inicializar componentes
        sampling_rate = int(config_mseed.get("MUESTREO(20)", 250))
        self.converter = TramaToMiniSEEDConverter(config_mseed, logger)
        self.buffer = CircularMiniSEEDBuffer(buffer_size, sampling_rate, logger)
        self.pipe_reader = PipeReader(PIPE_NAME, self._on_trama_received, logger)

        # Inferencia GPD (si se proporciona configuración)
        self.inference_thread = None
        if self.inference_config:
            try:
                model_path = self.inference_config.get("model_path")
                engine = GPDInferenceEngine(model_path, self.inference_config, logger)
                
                # Crear hilo de inferencia
                self.inference_thread = GPDInferenceThread(
                    buffer=self.buffer,
                    engine=engine,
                    interval_seconds=self.inference_config.get("inference_interval_seconds", 10),
                    window_duration=self.inference_config.get("inference_window_seconds", 60),
                    picks_file=self.inference_config.get("picks_output_file"),
                    logger=logger
                )
                self.logger.info("Motor de inferencia GPD configurado correctamente")
            except Exception as e:
                self.logger.error(f"No se pudo inicializar motor de inferencia GPD: {e}")

        # Control de ejecución
        self.running = Event()
        self.running.set()

        # Configurar manejadores de señales
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)

    def _on_trama_received(self, trama_bytes):
        """
        Callback llamado cuando se recibe una trama del pipe

        Args:
            trama_bytes: Bytes de la trama recibida
        """
        # Convertir trama a traces
        traces = self.converter.trama_to_traces(trama_bytes)

        if traces:
            # Agregar al buffer
            self.buffer.add_traces(traces)

    def _signal_handler(self, signum, frame):
        """Manejador de señales para shutdown limpio"""
        self.logger.info(f"Señal recibida: {signum}. Iniciando shutdown...")
        self.stop()

    def start_daemon(self):
        """Inicia el modo daemon (lectura continua)"""
        self.logger.info("Iniciando MiniSEED Buffer Manager en modo daemon")
        self.logger.info(f"Buffer: {self.buffer_size}s, Ventana: {self.window_duration}s")

        # Iniciar lector de pipe
        self.pipe_reader.start()

        # Iniciar inferencia si está configurada
        if self.inference_thread:
            self.inference_thread.start()

        # Bucle principal de monitoreo
        report_interval = 60  # Reportar cada 60 segundos
        last_report = time.time()

        try:
            while self.running.is_set():
                time.sleep(1)

                # Reporte periódico
                if time.time() - last_report >= report_interval:
                    self._print_status()
                    last_report = time.time()

        except KeyboardInterrupt:
            self.logger.info("KeyboardInterrupt recibido")
        finally:
            self.stop()

    def _print_status(self):
        """Imprime estado actual del sistema"""
        pipe_stats = self.pipe_reader.get_stats()
        buffer_stats = self.buffer.get_stats()

        self.logger.info("=" * 80)
        self.logger.info("STATUS REPORT")
        self.logger.info("-" * 80)
        self.logger.info(f"Pipe Reader:")
        self.logger.info(f"  Tramas recibidas: {pipe_stats['tramas_recibidas']}")
        self.logger.info(f"  Tramas inválidas: {pipe_stats['tramas_invalidas']}")
        self.logger.info(f"  Bytes recibidos: {pipe_stats['bytes_recibidos']:,}")
        self.logger.info(f"  Última trama: {pipe_stats['ultima_trama']}")
        self.logger.info(f"Buffer:")
        self.logger.info(f"  Tramas almacenadas: {buffer_stats['tamanio_actual']}/{self.buffer_size}")
        self.logger.info(f"  Tramas agregadas total: {buffer_stats['tramas_agregadas']}")
        self.logger.info(f"  Rotaciones: {buffer_stats['rotaciones']}")
        self.logger.info(f"  Rango temporal: {buffer_stats['rango_temporal']}")
        self.logger.info("=" * 80)

    def extract_and_save_window(self, duration_seconds, output_file):
        """
        Extrae una ventana temporal y la guarda a archivo

        Args:
            duration_seconds: Duración de la ventana
            output_file: Ruta del archivo de salida
        """
        self.logger.info(f"Extrayendo ventana de {duration_seconds}s...")

        stream = self.buffer.extract_window(duration_seconds)

        if stream:
            stream.write(output_file, format='MSEED', encoding='STEIM1', reclen=512)
            self.logger.info(f"Ventana guardada en: {output_file}")
            print(f"Ventana guardada exitosamente: {output_file}")
            return True
        else:
            self.logger.error("No se pudo extraer la ventana (buffer insuficiente)")
            print("Error: Buffer insuficiente para extraer la ventana solicitada")
            return False

    def stop(self):
        """Detiene el gestor y todos sus componentes"""
        self.logger.info("Deteniendo MiniSEED Buffer Manager...")
        self.running.clear()
        self.pipe_reader.stop()
        
        if self.inference_thread:
            self.inference_thread.stop()

        # Esperar a que los hilos terminen
        if self.pipe_reader.is_alive():
            self.pipe_reader.join(timeout=5)
        
        if self.inference_thread and self.inference_thread.is_alive():
            self.inference_thread.join(timeout=5)

        # Imprimir estado final
        self._print_status()

        self.logger.info("MiniSEED Buffer Manager detenido")

#######################################################################################################

######################################### ~Funciones auxiliares~ ######################################
def read_fileJSON(nameFile):
    """Lee un archivo de configuración en formato JSON"""
    try:
        with open(nameFile, 'r') as f:
            data = json.load(f)
        return data
    except FileNotFoundError:
        print(f"Archivo {nameFile} no encontrado.")
        return None
    except json.JSONDecodeError:
        print(f"Error al decodificar el archivo {nameFile}.")
        return None

def setup_logger(log_directory, log_filename="mseed_buffer.log", console_level=logging.INFO):
    """Configura el sistema de logging"""
    # Crear directorio si no existe
    Path(log_directory).mkdir(parents=True, exist_ok=True)

    # Configurar logger raíz
    logger = logging.getLogger()
    logger.setLevel(logging.DEBUG)

    # Handler para archivo
    log_path = os.path.join(log_directory, log_filename)
    file_handler = logging.FileHandler(log_path)
    file_handler.setLevel(logging.DEBUG)
    file_formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    file_handler.setFormatter(file_formatter)

    # Handler para consola
    console_handler = logging.StreamHandler()
    console_handler.setLevel(console_level)
    console_formatter = logging.Formatter('%(levelname)s - %(message)s')
    console_handler.setFormatter(console_formatter)

    # Agregar handlers
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)

    return logger

#######################################################################################################

############################################ ~Main~ ###################################################
def main():
    # Parser de argumentos
    parser = argparse.ArgumentParser(
        description="Gestor de buffer circular para datos miniSEED",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )

    parser.add_argument("--daemon", action="store_true",
                        help="Ejecutar en modo daemon (lectura continua)")
    parser.add_argument("--buffer-size", type=int, default=1800,
                        help="Tamaño del buffer en segundos (default: 1800 = 30 min)")
    parser.add_argument("--window-duration", type=int, default=60,
                        help="Duración de ventanas para exportación en segundos (default: 60)")
    parser.add_argument("--extract-window", type=int, metavar="DURATION",
                        help="Extraer ventana de N segundos del buffer actual")
    parser.add_argument("--output", type=str, default="ventana_extraida.mseed",
                        help="Archivo de salida para ventana extraída")
    parser.add_argument("--log-level", choices=['DEBUG', 'INFO', 'WARNING', 'ERROR'],
                        default='INFO', help="Nivel de logging en consola")
    
    # Argumentos GPD
    parser.add_argument("--enable-inference", action="store_true",
                        help="Activar detección de eventos GPD en tiempo real")
    parser.add_argument("--inference-config", type=str,
                        help="Ruta al archivo de configuración GPD JSON")

    args = parser.parse_args()

    # Obtener variable de entorno
    project_local_root = os.getenv("PROJECT_LOCAL_ROOT")
    if not project_local_root:
        print("ERROR: La variable de entorno PROJECT_LOCAL_ROOT no está definida.")
        return 1

    # Definir rutas
    config_mseed_file = os.path.join(project_local_root, "configuracion", "configuracion_mseed.json")
    log_directory = os.path.join(project_local_root, "log-files")

    # Configurar logging
    log_level = getattr(logging, args.log_level)
    logger = setup_logger(log_directory, console_level=log_level)

    logger.info("=" * 80)
    logger.info("MiniSEED Buffer Manager v1.0")
    logger.info("=" * 80)

    # Leer configuración miniSEED
    config_mseed = read_fileJSON(config_mseed_file)
    if config_mseed is None:
        logger.error(f"No se pudo leer el archivo de configuración: {config_mseed_file}")
        return 1

    logger.info(f"Configuración cargada: {config_mseed_file}")
    logger.info(f"Estación: {config_mseed.get('CODIGO(1)', 'UNKNOWN')}")

    # Verificar que el named pipe existe
    if not os.path.exists(PIPE_NAME):
        logger.warning(f"Named pipe no existe: {PIPE_NAME}")
        logger.warning("El pipe será creado por registro_continuo.c al iniciarse")

    # Configurar motor de inferencia si se solicita
    inference_config = None
    if args.enable_inference:
        config_path = args.inference_config or os.path.join(
            project_local_root, "configuracion", "configuracion_gpd.json"
        )
        inference_config = read_fileJSON(config_path)
        if inference_config:
            # Asegurar que model_path sea absoluto
            if not os.path.isabs(inference_config.get("model_path", "")):
                inference_config["model_path"] = os.path.join(
                    project_local_root, "models", "gpd_v2.tflite"
                )
            
            # Configurar archivo de salida de picks
            picks_file = os.path.join(log_directory, "gpd_detections.picks")
            inference_config["picks_output_file"] = picks_file
            logger.info(f"Detecciones GPD se guardarán en: {picks_file}")

    # Inicializar gestor
    manager = MiniSEEDBufferManager(
        config_mseed=config_mseed,
        buffer_size=args.buffer_size,
        window_duration=args.window_duration,
        inference_config=inference_config,
        logger=logger
    )

    # Ejecutar según modo
    if args.daemon:
        logger.info("Modo: DAEMON (lectura continua)")
        manager.start_daemon()
    elif args.extract_window:
        logger.info(f"Modo: EXTRACCIÓN (ventana de {args.extract_window}s)")
        logger.warning("Modo de extracción requiere buffer previamente poblado")
        logger.info("Para poblar el buffer, ejecute primero en modo --daemon")
        # En este modo, necesitaríamos un mecanismo de IPC para acceder al buffer
        # de otra instancia. Por simplicidad, este modo está limitado.
        print("ADVERTENCIA: Modo de extracción requiere implementación de IPC")
        print("Solución alternativa: Use señales o archivos compartidos")
        return 1
    else:
        parser.print_help()
        return 1

    return 0

#######################################################################################################
if __name__ == '__main__':
    sys.exit(main())
#######################################################################################################

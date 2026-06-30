"""
shared_memory_publisher.py — Gestión de memoria compartida para el stream de datos.

Permite publicar y leer tramas decodificadas de forma extremadamente rápida
usando memoria compartida (/dev/shm/) y mmap en Linux.

Layout del segmento de 3024 bytes:
Offset  Tamaño    Campo                     Tipo
──────  ────────  ────────────────────────  ──────────────
0       8         sequence_number           uint64 LE
8       8         timestamp_epoch           float64 LE (Unix timestamp)
16      3000      samples                   int32 LE × 750 (250×3)
3016    1         clock_source              uint8
3017    7         _padding                  reserved (alineamiento a 8 bytes)
──────  ────────
Total:  3024 bytes
"""

import os
import mmap
import struct
import time
import logging
import numpy as np
from typing import Optional, Tuple

SHM_PATH = "/dev/shm/rsa_current_frame"
SHM_SIZE = 3024

OFFSET_SEQ = 0
OFFSET_TIMESTAMP = 8
OFFSET_SAMPLES = 16
OFFSET_CLOCK = 3016


class SharedMemoryPublisher:
    """
    Publica tramas decodificadas a un segmento de memoria compartida.
    El segmento vive en /dev/shm/ (tmpfs en Linux), proporcionando latencias
    de escritura muy bajas sin I/O de disco.

    Diseño sin locks (Lock-free Writer):
    El sequence_number se incrementa a un valor impar al comenzar la escritura,
    y a un valor par (el final) al terminar. Los lectores realizan una doble lectura
    para verificar coherencia.
    """

    def __init__(self, shm_path: str = SHM_PATH, logger: Optional[logging.Logger] = None):
        self._shm_path = shm_path
        self._logger = logger or logging.getLogger(__name__)
        self._mmap = None
        self._seq = 0

        self._inicializar_shm()

    def _inicializar_shm(self) -> None:
        """Crea o abre el archivo en /dev/shm y lo mapea a memoria."""
        try:
            # Crear directorio base si no existiera (aunque /dev/shm siempre existe en Linux)
            os.makedirs(os.path.dirname(self._shm_path), exist_ok=True)

            # Abrir o crear el archivo
            fd = os.open(self._shm_path, os.O_CREAT | os.O_RDWR)
            # Asegurar tamaño exacto
            os.ftruncate(fd, SHM_SIZE)
            # Mapear
            self._mmap = mmap.mmap(fd, SHM_SIZE, mmap.MAP_SHARED, mmap.PROT_WRITE)
            os.close(fd)

            # Inicializar con ceros y seq=0
            self._mmap.seek(0)
            self._mmap.write(b'\x00' * SHM_SIZE)
            self._logger.info(f"[SHM_INIT] Segmento creado y mapeado en: {self._shm_path}")
        except Exception as e:
            self._logger.error(f"[SHM_INIT_ERROR] Error inicializando memoria compartida: {e}", exc_info=True)
            raise

    def publish(self, samples: np.ndarray, timestamp: float, clock_source: int) -> None:
        """
        Escribe una trama decodificada al segmento de memoria compartida.

        Secuencia de escritura (Seqlock):
        1. Incrementar sequence_number a impar (indica escritura en progreso).
        2. Escribir timestamp_epoch.
        3. Escribir samples (750 int32).
        4. Escribir clock_source.
        5. Incrementar sequence_number a par (indica escritura finalizada y coherente).
        """
        if self._mmap is None or self._mmap.closed:
            raise OSError("Memoria compartida no inicializada o cerrada.")

        # 1. Incrementar sequence_number a impar
        self._seq = (self._seq + 1) | 1
        self._mmap[OFFSET_SEQ:OFFSET_SEQ + 8] = struct.pack('<Q', self._seq)

        # 2. Escribir timestamp_epoch (float64)
        self._mmap[OFFSET_TIMESTAMP:OFFSET_TIMESTAMP + 8] = struct.pack('<d', timestamp)

        # 3. Escribir samples (750 int32 LE)
        # Asegurar formato int32 Little Endian y aplanar a 1D
        samples_flat = samples.astype('<i4', copy=False).ravel()
        samples_bytes = samples_flat.tobytes()
        if len(samples_bytes) != 3000:
            raise ValueError(f"Tamaño de muestras inválido. Se esperaban 3000 bytes, obtenidos {len(samples_bytes)}")
        self._mmap[OFFSET_SAMPLES:OFFSET_SAMPLES + 3000] = samples_bytes

        # 4. Escribir clock_source (uint8)
        self._mmap[OFFSET_CLOCK:OFFSET_CLOCK + 1] = struct.pack('<B', clock_source)

        # 5. Incrementar sequence_number a par (estable)
        self._seq = (self._seq + 1) & 0xFFFFFFFFFFFFFFFF
        self._mmap[OFFSET_SEQ:OFFSET_SEQ + 8] = struct.pack('<Q', self._seq)

    def close(self) -> None:
        """Cierra el mmap y elimina el archivo de /dev/shm."""
        if self._mmap is not None:
            try:
                self._mmap.close()
            except Exception:
                pass
            self._mmap = None

        if os.path.exists(self._shm_path):
            try:
                os.unlink(self._shm_path)
                self._logger.info(f"[SHM_CLEAN] Archivo removido: {self._shm_path}")
            except OSError as e:
                self._logger.warning(f"[SHM_CLEAN_ERROR] No se pudo remover el archivo {self._shm_path}: {e}")

    @property
    def sequence_number(self) -> int:
        """Retorna el sequence_number actual."""
        if self._mmap is None or self._mmap.closed:
            return 0
        return struct.unpack('<Q', self._mmap[OFFSET_SEQ:OFFSET_SEQ + 8])[0]


class SharedMemoryReader:
    """
    Lee tramas desde el segmento de memoria compartida (lado consumidor).
    Diseñado para polling eficiente sin bloquear al escritor.
    """

    def __init__(self, shm_path: str = SHM_PATH):
        self._shm_path = shm_path
        self._mmap = None
        self._ino = None
        self._open()

    def _open(self) -> None:
        """Abre y mapea el segmento en modo solo lectura."""
        if self._mmap is not None:
            try:
                self._mmap.close()
            except Exception:
                pass
            self._mmap = None

        if not os.path.exists(self._shm_path):
            raise FileNotFoundError(f"Segmento de memoria compartida no encontrado: {self._shm_path}")

        try:
            # Obtener inode para detección de recreación de archivo
            self._ino = os.stat(self._shm_path).st_ino
            fd = os.open(self._shm_path, os.O_RDONLY)
            self._mmap = mmap.mmap(fd, SHM_SIZE, mmap.MAP_SHARED, mmap.PROT_READ)
            os.close(fd)
        except Exception as e:
            raise OSError(f"Error al mapear memoria compartida en modo lectura: {e}") from e

    def _verificar_recreacion(self) -> None:
        """Verifica si el publicador recreó el archivo e invalida el mmap anterior."""
        try:
            current_ino = os.stat(self._shm_path).st_ino
            if current_ino != self._ino:
                self._open()
        except (FileNotFoundError, OSError):
            # El archivo pudo ser removido temporalmente por el publicador al cerrarse
            pass

    def get_sequence_number(self) -> int:
        """Lee solo el sequence_number (8 bytes) de forma ultra-rápida."""
        self._verificar_recreacion()
        if self._mmap is None or self._mmap.closed:
            return 0
        return struct.unpack('<Q', self._mmap[OFFSET_SEQ:OFFSET_SEQ + 8])[0]

    def read(self) -> Tuple[int, float, np.ndarray, int]:
        """
        Lee de forma coherente la trama actual utilizando Seqlock Double-Read.

        Returns:
            Tuple[sequence_number, timestamp_epoch, samples (250, 3) int32, clock_source]

        Raises:
            OSError: Si no se puede lograr una lectura consistente tras varios reintentos.
        """
        self._verificar_recreacion()
        if self._mmap is None or self._mmap.closed:
            raise OSError("Memoria compartida no inicializada o cerrada en el lector.")

        max_retries = 10
        for _ in range(max_retries):
            # 1. Leer sequence_number inicial
            seq1 = struct.unpack('<Q', self._mmap[OFFSET_SEQ:OFFSET_SEQ + 8])[0]

            # Si es impar, significa que el publicador está escribiendo en este momento
            if seq1 % 2 != 0:
                time.sleep(0.001)
                continue

            # 2. Leer datos
            timestamp = struct.unpack('<d', self._mmap[OFFSET_TIMESTAMP:OFFSET_TIMESTAMP + 8])[0]
            samples_bytes = self._mmap[OFFSET_SAMPLES:OFFSET_SAMPLES + 3000]
            clock_source = struct.unpack('<B', self._mmap[OFFSET_CLOCK:OFFSET_CLOCK + 1])[0]

            # 3. Leer sequence_number final
            seq2 = struct.unpack('<Q', self._mmap[OFFSET_SEQ:OFFSET_SEQ + 8])[0]

            # Si coinciden, los datos leídos son coherentes y no fueron interrumpidos
            if seq1 == seq2:
                # Reconstruir array numpy
                samples = np.frombuffer(samples_bytes, dtype='<i4').reshape((250, 3)).copy()
                return seq1, timestamp, samples, clock_source

            # Si no coinciden, se leyó durante una escritura, reintentar
            time.sleep(0.001)

        raise OSError("Fallo al obtener una lectura coherente de memoria compartida tras múltiples intentos.")

    def close(self) -> None:
        """Cierra el mmap en el lector (no elimina el archivo)."""
        if self._mmap is not None:
            try:
                self._mmap.close()
            except Exception:
                pass
            self._mmap = None

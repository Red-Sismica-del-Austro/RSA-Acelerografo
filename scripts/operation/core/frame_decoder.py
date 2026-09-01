"""
frame_decoder.py — Decodificador de tramas binarias del acelerógrafo RSA.

Extrae la lógica de decodificación 20-bit de binary_to_mseed.py en un módulo
reutilizable y liviano, sin dependencia de ObsPy.

Estructura de la trama de 2506 bytes (producida por registro_continuo_4.5.0.c):

    Byte 0:         Fuente de reloj
                      0: RPi  |  1: GPS  |  2: RTC
                      3: Error GPS (trama inválida)
                      4: Error RTC (no responde GPS)
                      5: Error GPS (timeout)

    Bytes 1-2500:   250 muestras × 10 bytes/muestra
                    Formato muestra: [ID(1B)] [X3,X2,X1, Y3,Y2,Y1, Z3,Z2,Z1 (9B)]
                    Codificación: 20 bits, complemento a 2 (sign-extended a int32)

    Bytes 2500-2505: Timestamp [año-2000, mes, día, hora, minuto, segundo]
                    (año en bytes[2500] = año - 2000; ej: 26 → 2026)

Nota sobre el bug de fecha del dsPIC:
    Existe un bug conocido en el firmware del dsPIC que puede provocar que los
    bytes de fecha (2500-2502) no se actualicen correctamente. Por eso se soportan
    dos métodos de extracción de fecha:
      - usar_fecha_filename=False: Desde bytes 2500-2502 de la trama (tradicional)
      - usar_fecha_filename=True:  Desde el nombre del archivo que contiene la trama

Uso:
    from core.frame_decoder import decode_frame, decode_samples, decode_timestamp

    raw = pipe.read(FRAME_SIZE)
    frame = decode_frame(raw)
    print(frame.samples.shape)   # (250, 3)
    print(frame.timestamp)       # datetime(2026, 6, 16, 14, 30, 00)
    print(frame.clock_source)    # 1 (GPS)
"""

import re
import os
import datetime
from typing import Optional, NamedTuple

import numpy as np


# ---------------------------------------------------------------------------
# Constantes
# ---------------------------------------------------------------------------

FRAME_SIZE = 2506
"""Tamaño en bytes de una trama binaria completa (1 segundo de datos)."""

SAMPLES_PER_FRAME = 250
"""Número de muestras por trama (250 Hz durante 1 segundo)."""

AXES = 3
"""Número de ejes: X, Y, Z."""

SAMPLE_BLOCK_SIZE = 10
"""Bytes por muestra: 1 byte ID + 9 bytes de datos (3 ejes × 3 bytes)."""

# Offsets de la trama
_OFFSET_SAMPLES_START = 0
_OFFSET_SAMPLES_END = 2500      # bytes 0..2499 inclusive
_OFFSET_YEAR = 2500
_OFFSET_MONTH = 2501
_OFFSET_DAY = 2502
_OFFSET_HOUR = 2503
_OFFSET_MINUTE = 2504
_OFFSET_SECOND = 2505

# Regex para extraer fecha del nombre de archivo ring buffer:
# ring_YYYYMMDD_HHMMSS.bin  → grupos (YYYY, MM, DD)
_RING_FILE_PATTERN = re.compile(r'^ring_(\d{4})(\d{2})(\d{2})_\d{6}\.bin$')

# Regex compatible con archivos .dat (mismo formato que binary_to_mseed.py):
# CODIGO_AAMMDD-HHMMSS.dat  → grupos (AA, MM, DD)
_DAT_FILE_PATTERN = re.compile(r'^[A-Z0-9]+_(\d{2})(\d{2})(\d{2})-\d{6}\.dat$')

# Códigos de fuente de reloj
CLOCK_SOURCE_RPI = 0
CLOCK_SOURCE_GPS = 1
CLOCK_SOURCE_RTC = 2
CLOCK_SOURCE_ERR_GPS_INVALID = 3
CLOCK_SOURCE_ERR_RTC_NO_GPS = 4
CLOCK_SOURCE_ERR_GPS_TIMEOUT = 5


# ---------------------------------------------------------------------------
# Tipo de retorno
# ---------------------------------------------------------------------------

class FrameData(NamedTuple):
    """
    Resultado de decodificar una trama binaria de 2506 bytes.

    Attributes:
        samples:      Array NumPy de forma (250, 3), dtype int32.
                      Filas = muestras (0..249), columnas = ejes (X=0, Y=1, Z=2).
        timestamp:    Fecha y hora de la trama como objeto datetime (UTC).
        clock_source: Código de fuente de reloj (ver constantes CLOCK_SOURCE_*).
    """
    samples: np.ndarray
    timestamp: datetime.datetime
    clock_source: int


# ---------------------------------------------------------------------------
# Funciones de extracción de fecha
# ---------------------------------------------------------------------------

def _extraer_fecha_desde_trama(raw: bytes) -> tuple:
    """
    Extrae (año, mes, día) desde los bytes 2500-2502 de la trama.

    El byte 2500 almacena el año como offset desde 2000 (ej. 26 → 2026).

    Returns:
        Tupla (año: int, mes: int, día: int)
    """
    data = raw if isinstance(raw, (bytes, bytearray)) else bytes(raw)
    year = int(data[_OFFSET_YEAR]) + 2000
    month = int(data[_OFFSET_MONTH])
    day = int(data[_OFFSET_DAY])
    return year, month, day


def _extraer_fecha_desde_nombre(filename: str) -> Optional[tuple]:
    """
    Extrae (año, mes, día) del nombre de un archivo del ring buffer o .dat.

    Soporta dos formatos:
      - ring_YYYYMMDD_HHMMSS.bin  (ring buffer)
      - CODIGO_AAMMDD-HHMMSS.dat  (registro continuo, año en 2 dígitos)

    Args:
        filename: Nombre del archivo (solo el basename, sin ruta)

    Returns:
        Tupla (año: int, mes: int, día: int), o None si el nombre no coincide
        con ningún patrón conocido.
    """
    # Intentar patrón ring buffer (año completo de 4 dígitos)
    m = _RING_FILE_PATTERN.match(filename)
    if m:
        year = int(m.group(1))
        month = int(m.group(2))
        day = int(m.group(3))
        return year, month, day

    # Intentar patrón .dat (año en 2 dígitos)
    m = _DAT_FILE_PATTERN.match(filename)
    if m:
        year = 2000 + int(m.group(1))
        month = int(m.group(2))
        day = int(m.group(3))
        return year, month, day

    return None


# ---------------------------------------------------------------------------
# API pública
# ---------------------------------------------------------------------------

def validate_timestamp(h: int, m: int, s: int) -> bool:
    """
    Valida que los componentes de un timestamp sean coherentes.

    Args:
        h: Hora (0-23)
        m: Minuto (0-59)
        s: Segundo (0-59)

    Returns:
        True si los valores son válidos, False en caso contrario.
    """
    return (0 <= h <= 23) and (0 <= m <= 59) and (0 <= s <= 59)


def decode_samples(raw: bytes) -> np.ndarray:
    """
    Decodifica las muestras de una trama binaria (bytes 1-2500).

    Implementa la decodificación 20-bit complemento a 2, equivalente a la
    lógica en binary_to_mseed.py (leer_archivo_binario, líneas 137-150).

    Args:
        raw: Al menos 2501 bytes de la trama (se usan bytes 1 a 2500 inclusive).

    Returns:
        np.ndarray de forma (250, 3), dtype int32.
        Columna 0 = eje X, columna 1 = eje Y, columna 2 = eje Z.

    Raises:
        ValueError: Si len(raw) < 2500.
    """
    if len(raw) < 2500:
        raise ValueError(
            f"Se requieren al menos 2500 bytes para decodificar muestras, "
            f"recibidos: {len(raw)}"
        )

    data = np.frombuffer(raw, dtype=np.uint8)

    # Bytes 0..2499: 250 muestras × 10 bytes
    # Cada muestra: [ID(1B)] [X3,X2,X1, Y3,Y2,Y1, Z3,Z2,Z1 (9B)]
    sample_data = data[_OFFSET_SAMPLES_START:_OFFSET_SAMPLES_END].reshape(
        (SAMPLES_PER_FRAME, SAMPLE_BLOCK_SIZE)
    )

    result = np.empty((SAMPLES_PER_FRAME, AXES), dtype=np.int32)

    for j in range(AXES):
        # Índices dentro de cada bloque de 10 bytes:
        # Eje j usa bytes en posiciones j*3+1, j*3+2, j*3+3 (base 0 del bloque)
        d1 = sample_data[:, j * 3 + 1].astype(np.uint32)
        d2 = sample_data[:, j * 3 + 2].astype(np.uint32)
        d3 = sample_data[:, j * 3 + 3].astype(np.uint32)

        # Reconstrucción del valor de 20 bits desde 3 bytes de 8 bits:
        # d1 ocupa bits [19:12], d2 ocupa bits [11:4], d3 bits [3:0]
        val = ((d1 << 12) & 0xFF000) + ((d2 << 4) & 0xFF0) + ((d3 >> 4) & 0xF)

        # Conversión de complemento a 2 en 20 bits a int32 con signo
        val = val.astype(np.int32)
        mask = val >= 0x80000
        val[mask] = -1 * ((~val[mask] + 1) & 0x7FFFF)

        result[:, j] = val

    return result


def decode_timestamp(
    raw: bytes,
    usar_fecha_filename: bool = False,
    filename: Optional[str] = None
) -> datetime.datetime:
    """
    Extrae el timestamp de los bytes 2500-2505 de una trama binaria.

    Soporta dos métodos de extracción de fecha (ver nota sobre bug dsPIC):

    - usar_fecha_filename=False (método tradicional):
        La fecha (año, mes, día) se extrae de los bytes 2500-2502 de la trama.

    - usar_fecha_filename=True (método filename):
        La fecha se extrae del nombre del archivo (`filename`).
        La hora siempre se extrae de los bytes 2503-2505 de la trama.
        Si `filename` es None o no coincide con ningún patrón conocido,
        se usa el método tradicional como fallback con un aviso.

    Args:
        raw:                  Exactamente FRAME_SIZE (2506) bytes de la trama.
        usar_fecha_filename:  Si True, extrae la fecha del nombre de archivo.
        filename:             Nombre del archivo (basename) para extraer la fecha.
                              Requerido cuando usar_fecha_filename=True.

    Returns:
        datetime.datetime con la fecha y hora de la trama.

    Raises:
        ValueError: Si la trama tiene menos de 2506 bytes, o si los componentes
                    de tiempo son inválidos (hora>23, minuto>59, segundo>59).
    """
    if len(raw) < FRAME_SIZE:
        raise ValueError(
            f"Se requieren {FRAME_SIZE} bytes para extraer el timestamp, "
            f"recibidos: {len(raw)}"
        )

    data = raw if isinstance(raw, (bytes, bytearray)) else bytes(raw)

    # La hora se extrae siempre de la trama (bytes 2503-2505)
    hour = int(data[_OFFSET_HOUR])
    minute = int(data[_OFFSET_MINUTE])
    second = int(data[_OFFSET_SECOND])

    if not validate_timestamp(hour, minute, second):
        raise ValueError(
            f"Timestamp inválido en la trama: {hour:02d}:{minute:02d}:{second:02d} "
            f"(hora>23 o minuto>59 o segundo>59)"
        )

    # Extracción de la fecha (año, mes, día)
    year, month, day = _resolver_fecha(
        raw=data,
        usar_fecha_filename=usar_fecha_filename,
        filename=filename
    )

    try:
        return datetime.datetime(year, month, day, hour, minute, second)
    except ValueError as e:
        raise ValueError(
            f"No se pudo construir datetime con los valores extraídos "
            f"({year}-{month:02d}-{day:02d} {hour:02d}:{minute:02d}:{second:02d}): {e}"
        ) from e


def _resolver_fecha(
    raw: bytes,
    usar_fecha_filename: bool,
    filename: Optional[str]
) -> tuple:
    """
    Resuelve la fecha (año, mes, día) según el método configurado.

    Fallback automático al método tradicional si el método filename falla.

    Returns:
        Tupla (año: int, mes: int, día: int)
    """
    if usar_fecha_filename and filename:
        basename = os.path.basename(filename)
        fecha = _extraer_fecha_desde_nombre(basename)
        if fecha is not None:
            return fecha
        # Fallback: el nombre no coincide con ningún patrón conocido
        # (no se lanza excepción para mantener robustez del servicio)

    # Método tradicional: desde bytes de la trama
    return _extraer_fecha_desde_trama(raw)


def decode_frame(
    raw: bytes,
    usar_fecha_filename: bool = False,
    filename: Optional[str] = None
) -> FrameData:
    """
    Decodifica una trama binaria completa de 2506 bytes.

    Es la función principal del módulo. Combina decode_samples() y
    decode_timestamp() en un único resultado tipado.

    Args:
        raw:                  Exactamente FRAME_SIZE (2506) bytes crudos,
                              tal como llegan del named pipe o de un archivo .dat.
        usar_fecha_filename:  Si True, extrae la fecha del nombre de archivo
                              en lugar de los bytes de la trama (ver nota dsPIC).
        filename:             Nombre del archivo fuente (basename o ruta completa).
                              Solo se usa cuando usar_fecha_filename=True.

    Returns:
        FrameData(
            samples=np.ndarray (250, 3) int32,
            timestamp=datetime,
            clock_source=int  # 0:RPi, 1:GPS, 2:RTC, 3-5:errores
        )

    Raises:
        ValueError: Si len(raw) != FRAME_SIZE, timestamp inválido, o
                    no se puede construir un datetime válido con los datos.
    """
    if len(raw) != FRAME_SIZE:
        raise ValueError(
            f"Se requieren exactamente {FRAME_SIZE} bytes por trama, "
            f"recibidos: {len(raw)}"
        )

    data = raw if isinstance(raw, (bytes, bytearray)) else bytes(raw)

    clock_source = int(data[0])
    samples = decode_samples(data)
    timestamp = decode_timestamp(
        raw=data,
        usar_fecha_filename=usar_fecha_filename,
        filename=filename
    )

    return FrameData(
        samples=samples,
        timestamp=timestamp,
        clock_source=clock_source
    )


# ---------------------------------------------------------------------------
# Utilidad: construir trama de prueba (sin dependencia de hardware)
# ---------------------------------------------------------------------------

def build_test_frame(
    year: int = 2026,
    month: int = 6,
    day: int = 16,
    hour: int = 14,
    minute: int = 30,
    second: int = 0,
    clock_source: int = CLOCK_SOURCE_GPS,
    x_value: int = 0,
    y_value: int = 0,
    z_value: int = 0
) -> bytes:
    """
    Construye una trama binaria de 2506 bytes para tests.

    Genera 250 muestras con valores fijos (x_value, y_value, z_value)
    en formato 20-bit complemento a 2.

    Args:
        year, month, day:   Fecha (año completo, e.g. 2026)
        hour, minute, second: Hora
        clock_source:       Código de fuente de reloj (0-5)
        x_value, y_value, z_value: Valores int32 para las muestras
                                   (rango válido: -524288 a 524287, 20 bits C2)

    Returns:
        bytes de longitud FRAME_SIZE (2506)
    """
    frame = bytearray(FRAME_SIZE)

    # Nota sobre clock_source: El firmware del dsPIC coloca la fuente de reloj en el byte 0,
    # pero luego el bucle de muestras sobreescribe el byte 0 con el ID de la primera muestra (0).
    # Replicamos este comportamiento escribiendo las muestras desde el byte 0.
    # Por consiguiente, clock_source decodificado de la trama real siempre será 0 (CLOCK_SOURCE_RPI).

    # Bytes 0-2499: 250 muestras con valores fijos
    def _encode_20bit(value: int) -> tuple:
        """Codifica un valor int32 en 20-bit C2, retorna (d1, d2, d3)."""
        # Asegurar que el valor esté en rango 20-bit
        if value < 0:
            raw20 = (~(-value) + 1) & 0xFFFFF  # C2 de 20 bits
        else:
            raw20 = value & 0xFFFFF

        # d1 = bits [19:12] (8 bits más significativos del valor de 20 bits)
        # d2 = bits [11:4]  (8 bits medios)
        # d3 = bits [3:0]   (4 bits menos significativos, en los 4 bits altos del byte)
        d1 = (raw20 >> 12) & 0xFF
        d2 = (raw20 >> 4) & 0xFF
        d3 = (raw20 & 0xF) << 4  # Los 4 bits LSB van en los 4 bits más altos del byte d3
        return d1, d2, d3

    x1, x2, x3 = _encode_20bit(x_value)
    y1, y2, y3 = _encode_20bit(y_value)
    z1, z2, z3 = _encode_20bit(z_value)

    for i in range(SAMPLES_PER_FRAME):
        base = i * SAMPLE_BLOCK_SIZE
        frame[base] = i & 0xFF          # ID de muestra (1 byte)
        frame[base + 1] = x1
        frame[base + 2] = x2
        frame[base + 3] = x3
        frame[base + 4] = y1
        frame[base + 5] = y2
        frame[base + 6] = y3
        frame[base + 7] = z1
        frame[base + 8] = z2
        frame[base + 9] = z3

    # Bytes 2500-2505: timestamp
    frame[_OFFSET_YEAR] = (year - 2000) & 0xFF
    frame[_OFFSET_MONTH] = month & 0xFF
    frame[_OFFSET_DAY] = day & 0xFF
    frame[_OFFSET_HOUR] = hour & 0xFF
    frame[_OFFSET_MINUTE] = minute & 0xFF
    frame[_OFFSET_SECOND] = second & 0xFF

    return bytes(frame)

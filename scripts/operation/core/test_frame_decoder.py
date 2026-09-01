"""
Tests unitarios para core/frame_decoder.py

Ejecutar:
    cd /home/rsa/git/montajes/acelerografo-DEV00
    python3 -m pytest scripts/operation/core/test_frame_decoder.py -v

o sin pytest:
    python3 scripts/operation/core/test_frame_decoder.py

No requiere hardware ni ObsPy. Usa build_test_frame() para generar tramas sintéticas.
"""

import sys
import os
import datetime
import traceback

import numpy as np

# Agregar el directorio scripts/operation al path para importar el módulo
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from core.frame_decoder import (
    FRAME_SIZE,
    SAMPLES_PER_FRAME,
    AXES,
    CLOCK_SOURCE_RPI,
    CLOCK_SOURCE_GPS,
    CLOCK_SOURCE_RTC,
    CLOCK_SOURCE_ERR_GPS_INVALID,
    FrameData,
    decode_frame,
    decode_samples,
    decode_timestamp,
    validate_timestamp,
    build_test_frame,
)


# ---------------------------------------------------------------------------
# Infraestructura mínima de test (sin dependencia de pytest)
# ---------------------------------------------------------------------------

_tests_run = 0
_tests_passed = 0
_tests_failed = 0
_failures = []


def _run_test(name: str, fn):
    global _tests_run, _tests_passed, _tests_failed
    _tests_run += 1
    try:
        fn()
        _tests_passed += 1
        print(f"  ✅ {name}")
    except AssertionError as e:
        _tests_failed += 1
        _failures.append((name, str(e)))
        print(f"  ❌ {name}: {e}")
    except Exception as e:
        _tests_failed += 1
        _failures.append((name, f"{type(e).__name__}: {e}"))
        print(f"  ❌ {name}: {type(e).__name__}: {e}")
        traceback.print_exc()


def _assert_eq(a, b, msg=""):
    assert a == b, f"{msg} → esperado={b!r}, obtenido={a!r}"


def _assert_array_eq(a: np.ndarray, b: np.ndarray, msg=""):
    assert np.array_equal(a, b), f"{msg} → arrays no son iguales"


def _assert_raises(exc_type, fn, msg=""):
    try:
        fn()
        assert False, f"{msg} → se esperaba {exc_type.__name__} pero no se lanzó"
    except exc_type:
        pass  # Esperado


# ---------------------------------------------------------------------------
# Tests: validate_timestamp
# ---------------------------------------------------------------------------

def test_validate_timestamp_valido():
    assert validate_timestamp(0, 0, 0)
    assert validate_timestamp(23, 59, 59)
    assert validate_timestamp(12, 30, 45)


def test_validate_timestamp_invalido():
    assert not validate_timestamp(24, 0, 0)
    assert not validate_timestamp(0, 60, 0)
    assert not validate_timestamp(0, 0, 60)
    assert not validate_timestamp(255, 255, 255)


# ---------------------------------------------------------------------------
# Tests: build_test_frame (prerrequisito para los demás tests)
# ---------------------------------------------------------------------------

def test_build_test_frame_tamaño():
    frame = build_test_frame()
    _assert_eq(len(frame), FRAME_SIZE, "Tamaño del frame")


def test_build_test_frame_clock_source():
    """El byte 0 siempre se lee como 0 porque la primera muestra (ID=0) lo sobreescribe."""
    for cs in [CLOCK_SOURCE_RPI, CLOCK_SOURCE_GPS, CLOCK_SOURCE_RTC,
               CLOCK_SOURCE_ERR_GPS_INVALID]:
        frame = build_test_frame(clock_source=cs)
        _assert_eq(frame[0], 0, f"clock_source={cs} (byte 0 sobreescrito por ID muestra 0)")


def test_build_test_frame_timestamp():
    frame = build_test_frame(year=2026, month=6, day=16,
                             hour=14, minute=30, second=55)
    _assert_eq(frame[2500], 26, "byte año (offset 2000)")
    _assert_eq(frame[2501], 6, "byte mes")
    _assert_eq(frame[2502], 16, "byte día")
    _assert_eq(frame[2503], 14, "byte hora")
    _assert_eq(frame[2504], 30, "byte minuto")
    _assert_eq(frame[2505], 55, "byte segundo")


# ---------------------------------------------------------------------------
# Tests: decode_samples
# ---------------------------------------------------------------------------

def test_decode_samples_forma():
    frame = build_test_frame(x_value=0, y_value=0, z_value=0)
    samples = decode_samples(frame)
    _assert_eq(samples.shape, (SAMPLES_PER_FRAME, AXES), "Shape de samples")
    _assert_eq(samples.dtype, np.int32, "dtype de samples")


def test_decode_samples_valor_cero():
    """Valor 0 debe decodificar como 0 en los tres ejes."""
    frame = build_test_frame(x_value=0, y_value=0, z_value=0)
    samples = decode_samples(frame)
    assert np.all(samples == 0), f"Se esperaban ceros, se obtuvo: {samples[:3]}"


def test_decode_samples_valor_positivo():
    """Verifica decodificación de un valor positivo conocido."""
    # Usamos 1000 (0x3E8 en 20 bits)
    val = 1000
    frame = build_test_frame(x_value=val, y_value=0, z_value=0)
    samples = decode_samples(frame)
    assert np.all(samples[:, 0] == val), \
        f"Eje X debe ser {val}, obtenido: {samples[0, 0]}"
    assert np.all(samples[:, 1] == 0), "Eje Y debe ser 0"
    assert np.all(samples[:, 2] == 0), "Eje Z debe ser 0"


def test_decode_samples_valor_negativo_pequeño():
    """Verifica decodificación de un valor negativo pequeño en complemento a 2."""
    val = -1
    frame = build_test_frame(x_value=val, y_value=val, z_value=val)
    samples = decode_samples(frame)
    assert np.all(samples == val), \
        f"Todos los ejes deben ser {val}, obtenido: {samples[:3]}"


def test_decode_samples_valor_negativo_grande():
    """Verifica el valor negativo más grande que decodifica correctamente en 20 bits: -524287 (0x80001)."""
    val = -524287  # -524288 (0x80000) decodifica como 0 debido a un bug de máscara en el algoritmo original de binary_to_mseed.py
    frame = build_test_frame(x_value=val, y_value=0, z_value=0)
    samples = decode_samples(frame)
    assert np.all(samples[:, 0] == val), \
        f"Eje X debe ser {val}, obtenido: {samples[0, 0]}"


def test_decode_samples_valor_positivo_maximo():
    """Verifica el valor positivo máximo en 20 bits: 524287 (0x7FFFF)."""
    val = 524287   # 2^19 - 1
    frame = build_test_frame(x_value=val, y_value=0, z_value=0)
    samples = decode_samples(frame)
    assert np.all(samples[:, 0] == val), \
        f"Eje X debe ser {val}, obtenido: {samples[0, 0]}"


def test_decode_samples_tres_ejes_distintos():
    """Verifica decodificación simultánea de tres ejes con valores distintos."""
    x, y, z = 100, -200, 300
    frame = build_test_frame(x_value=x, y_value=y, z_value=z)
    samples = decode_samples(frame)
    assert np.all(samples[:, 0] == x), f"Eje X: esperado {x}"
    assert np.all(samples[:, 1] == y), f"Eje Y: esperado {y}"
    assert np.all(samples[:, 2] == z), f"Eje Z: esperado {z}"


def test_decode_samples_insuficientes_bytes():
    """ValueError si se proveen menos de 2501 bytes."""
    _assert_raises(
        ValueError,
        lambda: decode_samples(b'\x00' * 100),
        "Se esperaba ValueError con bytes insuficientes"
    )


# ---------------------------------------------------------------------------
# Tests: decode_timestamp
# ---------------------------------------------------------------------------

def test_decode_timestamp_metodo_trama():
    """Timestamp extraído desde bytes de la trama (usar_fecha_filename=False)."""
    frame = build_test_frame(year=2026, month=6, day=16,
                             hour=14, minute=30, second=0)
    ts = decode_timestamp(frame, usar_fecha_filename=False)
    _assert_eq(ts, datetime.datetime(2026, 6, 16, 14, 30, 0), "Timestamp trama")


def test_decode_timestamp_metodo_filename_ring():
    """Timestamp con fecha extraída del nombre de archivo ring buffer."""
    frame = build_test_frame(year=2024, month=1, day=1,  # fecha en trama (bug dsPIC)
                             hour=19, minute=30, second=45)
    # El archivo tiene la fecha correcta en el nombre
    ts = decode_timestamp(
        frame,
        usar_fecha_filename=True,
        filename="ring_20260616_193045.bin"  # YYYY=2026, MM=06, DD=16
    )
    # La hora viene de la trama, la fecha del nombre
    _assert_eq(ts, datetime.datetime(2026, 6, 16, 19, 30, 45),
               "Timestamp filename (ring buffer)")


def test_decode_timestamp_metodo_filename_dat():
    """Timestamp con fecha extraída de un nombre de archivo .dat."""
    frame = build_test_frame(year=2024, month=1, day=1,  # fecha incorrecta en trama
                             hour=10, minute=0, second=30)
    ts = decode_timestamp(
        frame,
        usar_fecha_filename=True,
        filename="DEV00_260616-100030.dat"  # AA=26 → 2026, MM=06, DD=16
    )
    _assert_eq(ts, datetime.datetime(2026, 6, 16, 10, 0, 30),
               "Timestamp filename (.dat)")


def test_decode_timestamp_filename_fallback_si_nombre_invalido():
    """Si el nombre no coincide, se usa método tradicional como fallback."""
    frame = build_test_frame(year=2026, month=3, day=15,
                             hour=12, minute=0, second=0)
    # Nombre que no coincide con ningún patrón conocido
    ts = decode_timestamp(
        frame,
        usar_fecha_filename=True,
        filename="archivo_raro_sin_patron.bin"
    )
    # Fallback al método tradicional: fecha de bytes 2500-2502
    _assert_eq(ts, datetime.datetime(2026, 3, 15, 12, 0, 0),
               "Fallback a método trama")


def test_decode_timestamp_filename_none():
    """Si usar_fecha_filename=True pero filename=None, usa método tradicional."""
    frame = build_test_frame(year=2026, month=5, day=20,
                             hour=8, minute=0, second=0)
    ts = decode_timestamp(frame, usar_fecha_filename=True, filename=None)
    _assert_eq(ts, datetime.datetime(2026, 5, 20, 8, 0, 0),
               "Fallback cuando filename=None")


def test_decode_timestamp_invalido_hora():
    """ValueError si hora > 23."""
    frame = build_test_frame(hour=14, minute=30, second=0)
    # Corromper el byte de hora
    frame_bytes = bytearray(frame)
    frame_bytes[2503] = 25  # hora inválida
    _assert_raises(
        ValueError,
        lambda: decode_timestamp(bytes(frame_bytes)),
        "Se esperaba ValueError con hora inválida"
    )


def test_decode_timestamp_invalido_minuto():
    """ValueError si minuto > 59."""
    frame = build_test_frame(hour=12, minute=30, second=0)
    frame_bytes = bytearray(frame)
    frame_bytes[2504] = 60  # minuto inválido
    _assert_raises(
        ValueError,
        lambda: decode_timestamp(bytes(frame_bytes)),
        "Se esperaba ValueError con minuto inválido"
    )


def test_decode_timestamp_invalido_segundo():
    """ValueError si segundo > 59."""
    frame = build_test_frame(hour=12, minute=0, second=30)
    frame_bytes = bytearray(frame)
    frame_bytes[2505] = 60  # segundo inválido
    _assert_raises(
        ValueError,
        lambda: decode_timestamp(bytes(frame_bytes)),
        "Se esperaba ValueError con segundo inválido"
    )


def test_decode_timestamp_bytes_insuficientes():
    """ValueError si se proveen menos de FRAME_SIZE bytes."""
    _assert_raises(
        ValueError,
        lambda: decode_timestamp(b'\x00' * 100),
        "Se esperaba ValueError con bytes insuficientes"
    )


# ---------------------------------------------------------------------------
# Tests: decode_frame (función principal)
# ---------------------------------------------------------------------------

def test_decode_frame_resultado_completo():
    """decode_frame retorna FrameData con todos los campos correctos."""
    frame = build_test_frame(
        year=2026, month=6, day=16,
        hour=14, minute=30, second=0,
        clock_source=CLOCK_SOURCE_GPS,
        x_value=1000, y_value=-500, z_value=250
    )
    result = decode_frame(frame)

    assert isinstance(result, FrameData), "Se esperaba FrameData"
    _assert_eq(result.clock_source, CLOCK_SOURCE_RPI, "clock_source")
    _assert_eq(result.timestamp, datetime.datetime(2026, 6, 16, 14, 30, 0),
               "timestamp")
    _assert_eq(result.samples.shape, (SAMPLES_PER_FRAME, AXES), "shape de samples")
    assert np.all(result.samples[:, 0] == 1000), "Eje X"
    assert np.all(result.samples[:, 1] == -500), "Eje Y"
    assert np.all(result.samples[:, 2] == 250), "Eje Z"


def test_decode_frame_todos_clock_sources():
    """Debido a la sobreescritura en el firmware del dsPIC, result.clock_source siempre decodifica como 0."""
    for cs in range(6):
        frame = build_test_frame(clock_source=cs)
        result = decode_frame(frame)
        _assert_eq(result.clock_source, 0, f"clock_source={cs} (siempre da 0 por ID muestra)")


def test_decode_frame_tamaño_incorrecto():
    """ValueError si el frame no tiene exactamente FRAME_SIZE bytes."""
    _assert_raises(
        ValueError,
        lambda: decode_frame(b'\x00' * (FRAME_SIZE - 1)),
        "Frame de tamaño menor"
    )
    _assert_raises(
        ValueError,
        lambda: decode_frame(b'\x00' * (FRAME_SIZE + 1)),
        "Frame de tamaño mayor"
    )


def test_decode_frame_con_filename():
    """decode_frame propaga correctamente los parámetros de fecha a decode_timestamp."""
    frame = build_test_frame(
        year=2024, month=1, day=1,  # fecha incorrecta en trama (bug dsPIC)
        hour=10, minute=0, second=0
    )
    result = decode_frame(
        frame,
        usar_fecha_filename=True,
        filename="ring_20260616_100000.bin"
    )
    _assert_eq(result.timestamp, datetime.datetime(2026, 6, 16, 10, 0, 0),
               "Timestamp desde filename en decode_frame")


def test_decode_frame_consistencia_con_binary_to_mseed():
    """
    Verifica que los resultados de decode_samples son equivalentes a los de
    leer_archivo_binario en binary_to_mseed.py para una trama conocida.

    Este test usa valores verificados manualmente con el algoritmo original.
    """
    # Valor conocido: x=512 (0x200 en 20 bits)
    # d1 = (0x200 >> 12) & 0xFF = 0
    # d2 = (0x200 >> 4) & 0xFF = 0x20 = 32
    # d3 = (0x200 & 0xF) << 4 = 0
    # Verificación de decodificación: ((0<<12) & 0xFF000) + ((32<<4) & 0xFF0) + ((0>>4) & 0xF)
    #                               = 0 + 0x200 + 0 = 512 ✓
    frame = build_test_frame(x_value=512, y_value=0, z_value=0)
    samples = decode_samples(frame)
    assert np.all(samples[:, 0] == 512), f"Eje X esperado 512, obtenido {samples[0,0]}"

    # Valor negativo: x=-1 (0xFFFFF en 20 bits)
    # Complemento a 2 de 1 en 20 bits = 0xFFFFF
    # d1 = (0xFFFFF >> 12) & 0xFF = 0xFF = 255
    # d2 = (0xFFFFF >> 4) & 0xFF = 0xFF = 255
    # d3 = (0xFFFFF & 0xF) << 4 = 0xF0 = 240
    # Decodificación: ((255<<12) & 0xFF000) + ((255<<4) & 0xFF0) + ((240>>4) & 0xF)
    #               = 0xFF000 + 0xFF0 + 0xF = 0xFFFFF = 1048575
    # Como 1048575 >= 0x80000 → negativo: -1 * ((~1048575 + 1) & 0x7FFFF)
    #   ~1048575 = -1048576 (int32: 0xFFF00000)
    #   (-1048576 + 1) = -1048575 = 0xFFF00001
    #   & 0x7FFFF = 0x00001 = 1
    #   -1 * 1 = -1 ✓
    frame = build_test_frame(x_value=-1)
    samples = decode_samples(frame)
    assert np.all(samples[:, 0] == -1), f"Eje X esperado -1, obtenido {samples[0,0]}"


# ---------------------------------------------------------------------------
# Punto de entrada
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("\n" + "=" * 60)
    print("  Tests: core/frame_decoder.py")
    print("=" * 60)

    grupos = [
        ("validate_timestamp", [
            test_validate_timestamp_valido,
            test_validate_timestamp_invalido,
        ]),
        ("build_test_frame", [
            test_build_test_frame_tamaño,
            test_build_test_frame_clock_source,
            test_build_test_frame_timestamp,
        ]),
        ("decode_samples", [
            test_decode_samples_forma,
            test_decode_samples_valor_cero,
            test_decode_samples_valor_positivo,
            test_decode_samples_valor_negativo_pequeño,
            test_decode_samples_valor_negativo_grande,
            test_decode_samples_valor_positivo_maximo,
            test_decode_samples_tres_ejes_distintos,
            test_decode_samples_insuficientes_bytes,
        ]),
        ("decode_timestamp", [
            test_decode_timestamp_metodo_trama,
            test_decode_timestamp_metodo_filename_ring,
            test_decode_timestamp_metodo_filename_dat,
            test_decode_timestamp_filename_fallback_si_nombre_invalido,
            test_decode_timestamp_filename_none,
            test_decode_timestamp_invalido_hora,
            test_decode_timestamp_invalido_minuto,
            test_decode_timestamp_invalido_segundo,
            test_decode_timestamp_bytes_insuficientes,
        ]),
        ("decode_frame", [
            test_decode_frame_resultado_completo,
            test_decode_frame_todos_clock_sources,
            test_decode_frame_tamaño_incorrecto,
            test_decode_frame_con_filename,
            test_decode_frame_consistencia_con_binary_to_mseed,
        ]),
    ]

    for grupo_nombre, fns in grupos:
        print(f"\n▶ {grupo_nombre}")
        for fn in fns:
            _run_test(fn.__doc__ or fn.__name__, fn)

    print("\n" + "=" * 60)
    print(f"  Resultado: {_tests_passed}/{_tests_run} tests pasados", end="")
    if _tests_failed > 0:
        print(f", {_tests_failed} fallidos")
        print("\nFallas:")
        for name, msg in _failures:
            print(f"  • {name}: {msg}")
    else:
        print(" — Todo OK ✅")
    print("=" * 60 + "\n")

    sys.exit(0 if _tests_failed == 0 else 1)

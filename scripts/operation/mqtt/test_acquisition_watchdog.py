"""
test_acquisition_watchdog.py — Tests unitarios para AcquisitionWatchdog.

Prueba la detección de estado de adquisición (ok, warning, error),
el cálculo de latencia/antigüedad de tramas y la tolerancia a errores de archivos.
"""

import os
import sys
import shutil
import tempfile
import datetime
from datetime import timezone

_OPERATION_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _OPERATION_DIR not in sys.path:
    sys.path.insert(0, _OPERATION_DIR)

from mqtt.acquisition_watchdog import AcquisitionWatchdog
from core.frame_decoder import FRAME_SIZE


# ---------------------------------------------------------------------------
# Helpers de Test
# ---------------------------------------------------------------------------

def _crear_trama_dummy(dt: datetime.datetime) -> bytes:
    """Crea una trama binaria válida de 2506 bytes con el timestamp dado."""
    frame = bytearray(FRAME_SIZE)
    frame[0] = 0  # Fuente de reloj RPi
    # Muestras dummy
    for i in range(250):
        offset = 1 + (i * 10)
        frame[offset] = i % 256
    # Timestamp en bytes 2500..2505 (YY, MM, DD, HH, MM, SS)
    # Formato del acelerógrafo RSA: YY=año-2000 o año directo
    frame[2500] = dt.year % 100
    frame[2501] = dt.month
    frame[2502] = dt.day
    frame[2503] = dt.hour
    frame[2504] = dt.minute
    frame[2505] = dt.second
    return bytes(frame)


def _crear_archivo_ring(directorio: str, dt: datetime.datetime, num_tramas: int = 5) -> str:
    """Crea un archivo ring_YYYYMMDD_HHMMSS.bin con N tramas."""
    filename = f"ring_{dt.strftime('%Y%m%d_%H%M%S')}.bin"
    filepath = os.path.join(directorio, filename)
    with open(filepath, "wb") as f:
        for i in range(num_tramas):
            t_trama = dt + datetime.timedelta(seconds=i)
            f.write(_crear_trama_dummy(t_trama))
    return filepath


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_dir_inexistente_retorna_error():
    """Directorios inexistentes retornan status 'error'."""
    watchdog = AcquisitionWatchdog(ring_dir="/tmp/directorio_no_existente_rsa_test")
    res = watchdog.evaluar_salud(station_id="DEV0")
    assert res["status"] == "error"
    assert res["reason"] == "ring_buffer_dir_not_found"
    assert res["station_id"] == "DEV0"


def test_dir_vacio_retorna_error():
    """Directorio vacío sin archivos retorna status 'error' con reason 'no_data_available'."""
    temp_dir = tempfile.mkdtemp(prefix="rsa_watchdog_test_")
    try:
        watchdog = AcquisitionWatchdog(ring_dir=temp_dir)
        res = watchdog.evaluar_salud(station_id="DEV0")
        assert res["status"] == "error"
        assert res["reason"] == "no_data_available"
    finally:
        shutil.rmtree(temp_dir)


def test_adquisicion_nominal_retorna_ok():
    """Una trama con 10 segundos de antigüedad debe reportar status 'ok'."""
    temp_dir = tempfile.mkdtemp(prefix="rsa_watchdog_test_")
    try:
        now_ref = datetime.datetime(2026, 9, 2, 16, 30, 0, tzinfo=timezone.utc)
        trama_ts = now_ref - datetime.timedelta(seconds=10)

        _crear_archivo_ring(temp_dir, trama_ts, num_tramas=1)

        watchdog = AcquisitionWatchdog(ring_dir=temp_dir, stale_threshold_s=300)
        res = watchdog.evaluar_salud(station_id="DEV0", now_utc=now_ref)

        assert res["status"] == "ok", f"Esperado 'ok', obtenido {res['status']}"
        assert res["age_seconds"] == 10.0, f"Esperado 10.0s, obtenido {res['age_seconds']}"
        assert res["station_id"] == "DEV0"
        assert "last_frame_utc" in res
    finally:
        shutil.rmtree(temp_dir)


def test_adquisicion_estancada_retorna_warning():
    """Una trama con 400 segundos de antigüedad (umbral 300s) reporta 'warning'."""
    temp_dir = tempfile.mkdtemp(prefix="rsa_watchdog_test_")
    try:
        now_ref = datetime.datetime(2026, 9, 2, 16, 30, 0, tzinfo=timezone.utc)
        trama_ts = now_ref - datetime.timedelta(seconds=400)

        _crear_archivo_ring(temp_dir, trama_ts, num_tramas=1)

        watchdog = AcquisitionWatchdog(ring_dir=temp_dir, stale_threshold_s=300)
        res = watchdog.evaluar_salud(station_id="DEV0", now_utc=now_ref)

        assert res["status"] == "warning", f"Esperado 'warning', obtenido {res['status']}"
        assert res["reason"] == "stale_data"
        assert res["age_seconds"] == 400.0
        assert res["threshold_seconds"] == 300
    finally:
        shutil.rmtree(temp_dir)


def test_archivo_corrupto_retrocede_al_anterior():
    """Si el archivo más reciente está incompleto, retrocede al archivo anterior."""
    temp_dir = tempfile.mkdtemp(prefix="rsa_watchdog_test_")
    try:
        now_ref = datetime.datetime(2026, 9, 2, 16, 30, 0, tzinfo=timezone.utc)
        trama_valida_ts = now_ref - datetime.timedelta(seconds=30)

        # Archivo 1 válido
        _crear_archivo_ring(temp_dir, trama_valida_ts, num_tramas=1)

        # Archivo 2 incompleto/corrupto (100 bytes)
        archivo_corrupto = os.path.join(temp_dir, "ring_20260902_163000.bin")
        with open(archivo_corrupto, "wb") as f:
            f.write(b"\x00" * 100)

        watchdog = AcquisitionWatchdog(ring_dir=temp_dir, stale_threshold_s=300)
        res = watchdog.evaluar_salud(station_id="DEV0", now_utc=now_ref)

        assert res["status"] == "ok"
        assert res["age_seconds"] == 30.0
    finally:
        shutil.rmtree(temp_dir)


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    tests = [
        test_dir_inexistente_retorna_error,
        test_dir_vacio_retorna_error,
        test_adquisicion_nominal_retorna_ok,
        test_adquisicion_estancada_retorna_warning,
        test_archivo_corrupto_retrocede_al_anterior,
    ]

    print("\n=================================================================")
    print("  Tests: mqtt/test_acquisition_watchdog.py")
    print("=================================================================\n")

    todos_ok = True
    for test_fn in tests:
        try:
            test_fn()
            print(f"  ✅ {test_fn.__name__}")
        except Exception as e:
            print(f"  ❌ {test_fn.__name__}: {e}")
            todos_ok = False

    print("\n=================================================================")
    if todos_ok:
        print(f"  Resultado: {len(tests)}/{len(tests)} tests pasados — Todo OK ✅")
    else:
        print("  Resultado: FALLARON algunos tests ❌")
    print("=================================================================\n")

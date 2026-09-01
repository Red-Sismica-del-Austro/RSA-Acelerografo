"""
Tests unitarios para core/signal_preprocessor.py

Ejecutar:
    cd /home/rsa/git/montajes/acelerografo-DEV00
    python3 scripts/operation/core/test_signal_preprocessor.py
"""

import os
import sys
import numpy as np
import traceback

# Agregar el directorio scripts/operation al path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from core.signal_preprocessor import (
    SignalPreprocessor,
    GPD_WINDOW_SAMPLES,
)

# ---------------------------------------------------------------------------
# Infraestructura de test (sin dependencia de pytest)
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


def _assert_true(cond, msg=""):
    assert cond, f"{msg} → se esperaba True"


def _assert_almost_eq(a, b, delta=1e-5, msg=""):
    assert abs(a - b) <= delta, f"{msg} → esperado={b:.5f}±{delta:.5f}, obtenido={a:.5f}"


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_resample_shape():
    """Resampling de 250 Hz a 100 Hz produce la forma (100, 3)."""
    prep = SignalPreprocessor()
    # Generar muestras sintéticas: 250 muestras por 3 canales
    samples_in = np.ones((250, 3), dtype=np.int32) * 5000
    samples_out = prep.resample_frame(samples_in)
    _assert_eq(samples_out.shape, (100, 3), "forma de salida del downsampler")


def test_resample_250_to_100():
    """Downsampling preserva la frecuencia de una sinusoide de 10 Hz por debajo de Nyquist."""
    prep = SignalPreprocessor()
    
    # Construir una sinusoide de 10 Hz muestreada a 250 Hz (1 segundo = 250 muestras)
    t_250 = np.linspace(0, 1, 250, endpoint=False)
    freq = 10.0
    amp = 10000.0
    # Señal en el eje 0 (X)
    sig_250 = np.zeros((250, 3), dtype=np.float64)
    sig_250[:, 0] = amp * np.sin(2 * np.pi * freq * t_250)
    
    # Resamplear a 100 Hz (1 segundo = 100 muestras)
    sig_100 = prep.resample_frame(sig_250)
    _assert_eq(sig_100.shape, (100, 3))
    
    # Validar que los valores resampleados correspondan a la sinusoide original a 10 Hz
    t_100 = np.linspace(0, 1, 100, endpoint=False)
    expected_sig_100 = amp * np.sin(2 * np.pi * freq * t_100)
    
    # Medir correlación o error medio para verificar que no haya atenuación
    # (resample_poly introduce ligeros efectos transitorios de borde al principio/fin,
    # por lo que comparamos excluyendo los primeros/últimos 5 elementos).
    diff = sig_100[5:-5, 0] - expected_sig_100[5:-5]
    max_error = np.max(np.abs(diff))
    
    # El error relativo de la interpolación polifásica en el centro debe ser ínfimo
    _assert_true(max_error < 100.0, f"error máximo de resampling polifásico elevado: {max_error}")


def test_normalize_range():
    """Normalización per-channel escala la ventana a un máximo de 1.0 por canal."""
    prep = SignalPreprocessor()
    window = np.zeros((100, 3), dtype=np.float64)
    # Canal X: rango -500 a 500
    window[:, 0] = np.linspace(-500.0, 400.0, 100)
    # Canal Y: rango 0 a 1200
    window[:, 1] = np.linspace(0.0, 1200.0, 100)
    # Canal Z: rango -2000 a 1000
    window[:, 2] = np.linspace(-2000.0, 1000.0, 100)

    normalized = prep.normalize_window(window)
    
    # Verificar tipos
    _assert_eq(normalized.dtype, np.float32, "dtype de normalización")
    
    # Máximos absolutos por canal de la salida deben ser aproximadamente 1.0 (dentro de tolerancia numérica)
    max_x = np.max(np.abs(normalized[:, 0]))
    max_y = np.max(np.abs(normalized[:, 1]))
    max_z = np.max(np.abs(normalized[:, 2]))
    
    _assert_almost_eq(max_x, 1.0, delta=1e-5, msg="máximo absoluto canal X")
    _assert_almost_eq(max_y, 1.0, delta=1e-5, msg="máximo absoluto canal Y")
    _assert_almost_eq(max_z, 1.0, delta=1e-5, msg="máximo absoluto canal Z")


def test_normalize_zeros():
    """La normalización no falla (ni produce NaN) ante una ventana llena de ceros."""
    prep = SignalPreprocessor()
    window = np.zeros((100, 3), dtype=np.float64)
    normalized = prep.normalize_window(window)
    
    _assert_true(not np.isnan(normalized).any(), "no deben haber NaNs")
    _assert_true(not np.isinf(normalized).any(), "no deben haber Infs")
    # Los valores deben ser aproximadamente 0.0 debido al divisor (0 / (0 + 1e-9) = 0)
    _assert_almost_eq(normalized[50, 0], 0.0, delta=1e-7, msg="canal de ceros normalizado")


def test_filter_attenuation():
    """El filtro Butterworth atenúa significativamente frecuencias fuera del pasabanda (3-20 Hz)."""
    # Filtro pasabanda 3-20 Hz habilitado
    prep = SignalPreprocessor(filter_enabled=True, freq_min=3.0, freq_max=20.0, filter_order=4)
    
    # 8 segundos a 100 Hz = 800 muestras
    t = np.linspace(0, 8, 800, endpoint=False)
    
    # Generar señal con tres frecuencias:
    # 1. 0.5 Hz (fuera, muy baja, debe atenuarse)
    # 2. 10 Hz  (dentro, pasabanda, debe pasar libremente)
    # 3. 40 Hz  (fuera, muy alta, debe atenuarse)
    sig_low = np.sin(2 * np.pi * 0.5 * t)
    sig_mid = np.sin(2 * np.pi * 10.0 * t)
    sig_high = np.sin(2 * np.pi * 40.0 * t)
    
    data = np.zeros((800, 3), dtype=np.float64)
    data[:, 0] = sig_low
    data[:, 1] = sig_mid
    data[:, 2] = sig_high
    
    filtered = prep.apply_filter(data)
    
    # Calcular amplitudes rms del centro de la ventana filtrada (excluyendo bordes)
    rms_low = np.sqrt(np.mean(filtered[200:600, 0] ** 2))
    rms_mid = np.sqrt(np.mean(filtered[200:600, 1] ** 2))
    rms_high = np.sqrt(np.mean(filtered[200:600, 2] ** 2))
    
    # RMS original de una sinusoide de amplitud 1 es ~0.707
    rms_original = 1.0 / np.sqrt(2) # ~0.707
    
    # 10 Hz debe estar poco atenuado (ej. conservar al menos el 80% de su RMS)
    _assert_true(rms_mid > 0.8 * rms_original, f"frecuencia pasante de 10 Hz atenuada: rms={rms_mid:.4f}")
    # 0.5 Hz y 40 Hz deben estar muy atenuados (ej. conservar menos del 15% de su RMS)
    _assert_true(rms_low < 0.15 * rms_original, f"frecuencia baja de 0.5 Hz no atenuada: rms={rms_low:.4f}")
    _assert_true(rms_high < 0.15 * rms_original, f"frecuencia alta de 40 Hz no atenuada: rms={rms_high:.4f}")


def test_prepare_window_shape():
    """prepare_window produce salida con forma (1, 400, 3) y dtype float32 en ambas opciones de tamaño."""
    prep = SignalPreprocessor(filter_enabled=True)
    
    # Caso 1: Entrada con padding (Opción A: 800 muestras)
    raw_800 = np.random.randn(800, 3)
    out_800 = prep.prepare_window(raw_800)
    _assert_eq(out_800.shape, (1, 400, 3), "forma de salida con padding de 800")
    _assert_eq(out_800.dtype, np.float32, "dtype de salida con padding de 800")
    
    # Caso 2: Entrada sin padding (400 muestras)
    raw_400 = np.random.randn(400, 3)
    out_400 = prep.prepare_window(raw_400)
    _assert_eq(out_400.shape, (1, 400, 3), "forma de salida sin padding")
    _assert_eq(out_400.dtype, np.float32, "dtype de salida sin padding")


# ---------------------------------------------------------------------------
# Punto de entrada
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("\n" + "=" * 65)
    print("  Tests: core/signal_preprocessor.py")
    print("=" * 65)

    grupos = [
        ("preprocesamiento de señal", [
            test_resample_shape,
            test_resample_250_to_100,
            test_normalize_range,
            test_normalize_zeros,
            test_filter_attenuation,
            test_prepare_window_shape,
        ]),
    ]

    for grupo_nombre, fns in grupos:
        print(f"\n▶ {grupo_nombre}")
        for fn in fns:
            _run_test(fn.__doc__ or fn.__name__, fn)

    print("\n" + "=" * 65)
    print(f"  Resultado: {_tests_passed}/{_tests_run} tests pasados", end="")
    if _tests_failed > 0:
        print(f", {_tests_failed} fallidos")
        print("\nFallas:")
        for name, msg in _failures:
            print(f"  • {name}: {msg}")
    else:
        print(" — Todo OK ✅")
    print("=" * 65 + "\n")

    sys.exit(0 if _tests_failed == 0 else 1)

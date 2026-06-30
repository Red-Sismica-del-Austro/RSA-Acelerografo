"""
Tests unitarios para streaming/shared_memory_publisher.py

Ejecutar:
    cd /home/rsa/git/montajes/acelerografo-DEV00
    python3 scripts/operation/streaming/test_shared_memory.py
"""

import os
import sys
import time
import threading
import numpy as np
import tempfile
import traceback
from typing import Tuple

# Agregar el directorio scripts/operation al path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from streaming.shared_memory_publisher import (
    SharedMemoryPublisher,
    SharedMemoryReader,
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


def _make_temp_shm_path() -> str:
    """Retorna una ruta temporal segura en /dev/shm para no colisionar con producción."""
    fd, path = tempfile.mkstemp(prefix="rsa_shm_test_", dir="/dev/shm")
    os.close(fd)
    # Lo eliminamos para que el editor/publisher lo cree fresco
    try:
        os.unlink(path)
    except OSError:
        pass
    return path


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_shm_write_read():
    """Escritura y lectura de trama con datos conocidos en SHM."""
    shm_path = _make_temp_shm_path()
    pub = SharedMemoryPublisher(shm_path=shm_path)
    try:
        # Muestras sintéticas (250 samples, 3 canales)
        samples_in = np.arange(750, dtype=np.int32).reshape((250, 3))
        timestamp_in = 1718746245.123
        clock_source_in = 1  # GPS

        # Publicar
        pub.publish(samples_in, timestamp_in, clock_source_in)

        # Leer con reader
        reader = SharedMemoryReader(shm_path=shm_path)
        try:
            seq, timestamp_out, samples_out, clock_source_out = reader.read()

            _assert_true(seq > 0, "sequence number debe ser > 0")
            _assert_eq(seq % 2, 0, "sequence number final debe ser par (estable)")
            _assert_eq(timestamp_out, timestamp_in, "timestamp coherente")
            _assert_eq(clock_source_out, clock_source_in, "fuente de reloj coherente")
            _assert_true(np.array_equal(samples_out, samples_in), "muestras idénticas")
        finally:
            reader.close()
    finally:
        pub.close()


def test_shm_sequence():
    """Verificar que seq_number se incrementa monotónicamente."""
    shm_path = _make_temp_shm_path()
    pub = SharedMemoryPublisher(shm_path=shm_path)
    try:
        reader = SharedMemoryReader(shm_path=shm_path)
        try:
            samples = np.zeros((250, 3), dtype=np.int32)
            
            # Primera publicación
            pub.publish(samples, 100.0, 0)
            seq1 = reader.get_sequence_number()
            
            # Segunda publicación
            pub.publish(samples, 101.0, 0)
            seq2 = reader.get_sequence_number()

            _assert_true(seq2 > seq1, f"secuencia debe crecer: seq1={seq1}, seq2={seq2}")
            _assert_eq(seq1 % 2, 0, "seq1 debe ser par")
            _assert_eq(seq2 % 2, 0, "seq2 debe ser par")
        finally:
            reader.close()
    finally:
        pub.close()


def test_shm_reader_auto_reconnect():
    """El lector se reconecta si el publicador reinicia y recrea el segmento."""
    shm_path = _make_temp_shm_path()
    
    # 1. Primer publicador escribe algo
    pub1 = SharedMemoryPublisher(shm_path=shm_path)
    samples1 = np.ones((250, 3), dtype=np.int32) * 42
    pub1.publish(samples1, 100.0, 1)
    
    # 2. Instanciar lector
    reader = SharedMemoryReader(shm_path=shm_path)
    try:
        seq_a, ts_a, samples_a, _ = reader.read()
        _assert_eq(samples_a[0, 0], 42, "primer valor leído es 42")
        
        # 3. Simular reinicio: cerrar pub1 (que elimina el archivo) y crear pub2
        pub1.close()
        
        pub2 = SharedMemoryPublisher(shm_path=shm_path)
        try:
            samples2 = np.ones((250, 3), dtype=np.int32) * 99
            pub2.publish(samples2, 200.0, 2)
            
            # 4. El reader debe detectar el cambio de archivo (diferente inode) y re-mapear solo
            seq_b, ts_b, samples_b, clock_b = reader.read()
            _assert_eq(samples_b[0, 0], 99, "lector auto-detectó recreación y leyó 99")
            _assert_eq(clock_b, 2, "reloj correcto")
        finally:
            pub2.close()
    finally:
        reader.close()


def test_shm_coherencia_concurrente():
    """
    Escritura concurrente: el lector siempre obtiene una trama completa y coherente,
    sin race conditions, debido al protocolo Seqlock.
    """
    shm_path = _make_temp_shm_path()
    pub = SharedMemoryPublisher(shm_path=shm_path)
    
    hilo_activo = True
    coherence_error = False

    def _escritor_intensivo():
        val = 0
        while hilo_activo:
            try:
                # Escribimos tramas alternadas llenas de 'val'
                samples = np.ones((250, 3), dtype=np.int32) * val
                pub.publish(samples, float(val), val % 6)
                val += 1
                time.sleep(0.0001)  # Intervalo ultra-corto para forzar concurrencia
            except Exception:
                break

    t = threading.Thread(target=_escritor_intensivo, daemon=True)
    t.start()

    time.sleep(0.05)  # Esperar que empiece a escribir
    
    reader = SharedMemoryReader(shm_path=shm_path)
    try:
        # El lector lee tantas veces como pueda y valida coherencia
        for _ in range(1000):
            try:
                seq, ts, samples, clock = reader.read()
                # En cada lectura coherente, todos los elementos del array
                # deben ser exactamente iguales a un mismo valor (ts)
                unique_vals = np.unique(samples)
                if len(unique_vals) != 1 or unique_vals[0] != int(ts):
                    coherence_error = True
                    print(f"  ❌ Error de coherencia detectado: unique={unique_vals}, ts={ts}")
                    break
            except OSError:
                # Ocurre si la lectura coincide exactamente durante la escritura parcial
                # de forma muy recurrente, pero el reader debería reintentar hasta 10 veces
                pass
    finally:
        reader.close()
        hilo_activo = False
        t.join(timeout=2.0)
        pub.close()

    _assert_true(not coherence_error, "no debe haber lecturas parciales incoherentes (mezcla de tramas)")


# ---------------------------------------------------------------------------
# Punto de entrada
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("\n" + "=" * 65)
    print("  Tests: streaming/shared_memory_publisher.py")
    print("=" * 65)

    grupos = [
        ("memoria compartida y seqlock", [
            test_shm_write_read,
            test_shm_sequence,
            test_shm_reader_auto_reconnect,
            test_shm_coherencia_concurrente,
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

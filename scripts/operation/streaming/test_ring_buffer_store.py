"""
Tests unitarios para streaming/ring_buffer_store.py

Ejecutar:
    cd /home/rsa/git/montajes/acelerografo-DEV00
    python3 -m pytest scripts/operation/streaming/test_ring_buffer_store.py -v

o sin pytest:
    python3 scripts/operation/streaming/test_ring_buffer_store.py

No requiere hardware. Usa un directorio temporal en /tmp para no interferir
con el ring buffer de producción. Las tramas se construyen con build_test_frame()
de core/frame_decoder.py.
"""

import sys
import os
import datetime
import tempfile
import shutil
import threading
import time
import traceback

import numpy as np

# Agregar el directorio scripts/operation al path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from core.frame_decoder import (
    FRAME_SIZE,
    build_test_frame,
    decode_timestamp,
)
from streaming.ring_buffer_store import RingBufferStore, RingFileEntry


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


def _assert_raises(exc_type, fn, msg=""):
    try:
        fn()
        assert False, f"{msg} → se esperaba {exc_type.__name__} pero no se lanzó"
    except exc_type:
        pass


def _make_store(tmpdir, max_size_mb=10, archivo_duracion_s=300):
    """Crea un RingBufferStore en un directorio temporal."""
    return RingBufferStore(
        directorio=tmpdir,
        max_size_mb=max_size_mb,
        archivo_duracion_s=archivo_duracion_s,
        usar_fecha_filename=False  # En tests usamos fecha desde trama
    )


def _make_frame(year=2026, month=6, day=16, hour=14, minute=30, second=0,
                x=0, y=0, z=0):
    """Construye una trama de prueba con timestamp dado."""
    return build_test_frame(
        year=year, month=month, day=day,
        hour=hour, minute=minute, second=second,
        x_value=x, y_value=y, z_value=z
    )


def _ts(hour=14, minute=30, second=0, day=16):
    return datetime.datetime(2026, 6, day, hour, minute, second)


# ---------------------------------------------------------------------------
# Tests: inicialización y estructura
# ---------------------------------------------------------------------------

def test_init_crea_directorio():
    """RingBufferStore crea el directorio si no existe."""
    with tempfile.TemporaryDirectory() as base:
        nuevo_dir = os.path.join(base, "ring_test")
        assert not os.path.exists(nuevo_dir)
        store = _make_store(nuevo_dir)
        assert os.path.isdir(nuevo_dir)
        store.close()


def test_init_directorio_vacio():
    """Al inicializar con directorio vacío, índice queda vacío."""
    with tempfile.TemporaryDirectory() as tmpdir:
        store = _make_store(tmpdir)
        _assert_eq(store.get_time_range(), None, "rango en buffer vacío")
        _assert_eq(store.get_disk_usage_mb(), 0.0, "uso en disco vacío")
        store.close()


def test_write_frame_tamanio_invalido():
    """ValueError si la trama no tiene exactamente FRAME_SIZE bytes."""
    with tempfile.TemporaryDirectory() as tmpdir:
        store = _make_store(tmpdir)
        ts = _ts()
        _assert_raises(
            ValueError,
            lambda: store.write_frame(b'\x00' * 100, ts),
            "trama demasiado corta"
        )
        _assert_raises(
            ValueError,
            lambda: store.write_frame(b'\x00' * (FRAME_SIZE + 1), ts),
            "trama demasiado larga"
        )
        store.close()


# ---------------------------------------------------------------------------
# Tests: escritura y consulta básica
# ---------------------------------------------------------------------------

def test_write_y_query_una_trama():
    """Escribir una trama y recuperarla por rango exacto."""
    with tempfile.TemporaryDirectory() as tmpdir:
        store = _make_store(tmpdir)
        ts = _ts(hour=14, minute=30, second=0)
        raw = _make_frame(hour=14, minute=30, second=0, x=1000, y=-500, z=250)

        store.write_frame(raw, ts)

        results = store.query_raw(
            start=datetime.datetime(2026, 6, 16, 14, 30, 0),
            end=datetime.datetime(2026, 6, 16, 14, 30, 59)
        )
        _assert_eq(len(results), 1, "una trama recuperada")
        _assert_eq(results[0], raw, "trama recuperada igual a la escrita")
        store.close()


def test_write_multiples_tramas_query_rango():
    """Escribir N tramas y recuperar un subconjunto por rango temporal."""
    with tempfile.TemporaryDirectory() as tmpdir:
        store = _make_store(tmpdir, archivo_duracion_s=3600)

        # Escribir 5 tramas: ss=0,1,2,3,4 a las 14:30:xx
        tramas = []
        for s in range(5):
            ts = _ts(hour=14, minute=30, second=s)
            raw = _make_frame(hour=14, minute=30, second=s, x=s * 100)
            store.write_frame(raw, ts)
            tramas.append(raw)

        # Consultar solo ss=1,2,3
        results = store.query_raw(
            start=_ts(hour=14, minute=30, second=1),
            end=_ts(hour=14, minute=30, second=3)
        )
        _assert_eq(len(results), 3, "3 tramas en rango [1,3]")
        _assert_eq(results[0], tramas[1], "primera trama del rango")
        _assert_eq(results[2], tramas[3], "última trama del rango")
        store.close()


def test_query_rango_fuera_de_buffer():
    """query() retorna lista vacía si el rango no tiene datos."""
    with tempfile.TemporaryDirectory() as tmpdir:
        store = _make_store(tmpdir, archivo_duracion_s=3600)
        ts = _ts(hour=14, minute=30, second=0)
        store.write_frame(_make_frame(hour=14, minute=30, second=0), ts)

        results = store.query_raw(
            start=datetime.datetime(2026, 6, 16, 20, 0, 0),
            end=datetime.datetime(2026, 6, 16, 21, 0, 0)
        )
        _assert_eq(len(results), 0, "lista vacía fuera de rango")
        store.close()


def test_query_start_mayor_que_end_lanza_valueerror():
    """ValueError si start > end en query_raw() y query()."""
    with tempfile.TemporaryDirectory() as tmpdir:
        store = _make_store(tmpdir)
        _assert_raises(
            ValueError,
            lambda: store.query_raw(
                start=datetime.datetime(2026, 6, 16, 15, 0, 0),
                end=datetime.datetime(2026, 6, 16, 14, 0, 0)
            ),
            "start > end debe lanzar ValueError"
        )
        store.close()


def test_query_retorna_framedata():
    """query() retorna FrameData con samples correctos."""
    with tempfile.TemporaryDirectory() as tmpdir:
        store = _make_store(tmpdir, archivo_duracion_s=3600)
        ts = _ts(hour=14, minute=30, second=0)
        raw = _make_frame(hour=14, minute=30, second=0, x=1234, y=-567, z=89)
        store.write_frame(raw, ts)

        results = store.query(
            start=_ts(hour=14, minute=30, second=0),
            end=_ts(hour=14, minute=30, second=59)
        )
        _assert_eq(len(results), 1, "una FrameData")
        frame = results[0]
        assert np.all(frame.samples[:, 0] == 1234), f"Eje X esperado 1234, obtenido {frame.samples[0,0]}"
        assert np.all(frame.samples[:, 1] == -567), f"Eje Y esperado -567"
        assert np.all(frame.samples[:, 2] == 89), f"Eje Z esperado 89"
        store.close()


# ---------------------------------------------------------------------------
# Tests: rotación de archivos
# ---------------------------------------------------------------------------

def test_rotacion_crea_nuevo_archivo():
    """El ring buffer rota el archivo cuando se supera archivo_duracion_s (tiempo real)."""
    with tempfile.TemporaryDirectory() as tmpdir:
        # Duración muy corta: 1 segundo por archivo (mínimo praáctico en tiempo real)
        store = _make_store(tmpdir, archivo_duracion_s=1)

        # Primera trama: abre el primer archivo
        store.write_frame(_make_frame(hour=14, minute=30, second=0), _ts(minute=30, second=0))

        # Esperar a que el tiempo real supere archivo_duracion_s=1s
        time.sleep(1.1)

        # Segunda trama: debe disparar la rotación (tiempo real >= 1s)
        store.write_frame(_make_frame(hour=14, minute=30, second=1), _ts(minute=30, second=1))

        # Tercera trama: va al nuevo archivo
        store.write_frame(_make_frame(hour=14, minute=30, second=2), _ts(minute=30, second=2))
        store.close()

        archivos = sorted(
            f for f in os.listdir(tmpdir) if f.endswith('.bin')
        )
        assert len(archivos) >= 2, \
            f"Deben existir al menos 2 archivos tras rotación, encontrados: {archivos}"


def test_naming_archivos_ring():
    """Los archivos se nombran con el formato ring_YYYYMMDD_HHMMSS.bin."""
    with tempfile.TemporaryDirectory() as tmpdir:
        store = _make_store(tmpdir)
        ts = datetime.datetime(2026, 6, 16, 14, 30, 0)
        store.write_frame(_make_frame(hour=14, minute=30, second=0), ts)
        store.close()

        archivos = [f for f in os.listdir(tmpdir) if f.endswith('.bin')]
        assert len(archivos) == 1, f"Debe existir exactamente 1 archivo, encontrados: {archivos}"
        nombre = archivos[0]
        assert nombre.startswith("ring_"), f"Nombre debe comenzar con 'ring_': {nombre}"
        assert nombre == "ring_20260616_143000.bin", \
            f"Nombre esperado 'ring_20260616_143000.bin', obtenido: {nombre}"


def test_query_abarca_multiples_archivos():
    """query_raw() recupera tramas de múltiples archivos rotativos."""
    with tempfile.TemporaryDirectory() as tmpdir:
        store = _make_store(tmpdir, archivo_duracion_s=1)

        tramas_escritas = []
        # 4 tramas separadas por sleep para forzar rotación real
        for s in range(4):
            ts = _ts(hour=14, minute=30, second=s)
            raw = _make_frame(hour=14, minute=30, second=s, x=s * 10)
            store.write_frame(raw, ts)
            tramas_escritas.append(raw)
            if s < 3:
                time.sleep(1.1)  # Forzar rotación por tiempo real

        results = store.query_raw(
            start=_ts(hour=14, minute=30, second=0),
            end=_ts(hour=14, minute=30, second=3)
        )
        _assert_eq(len(results), 4, "4 tramas de múltiples archivos")
        store.close()


def test_rotacion_bug_cambio_dia():
    """Regresón temporal en cambio de día (bug dsPIC) no bloquea la rotación."""
    # Simula el escenario real:
    # - El archivo se crea a las 23:59:44 del día 17
    # - Las tramas de las 00:00:xx llegan con fecha del día 17 (bug dsPIC)
    # - El timestamp retrocede, pero el tiempo real supera archivo_duracion_s
    # - Con el fix: _debe_rotar() detecta por tiempo real y rota correctamente
    with tempfile.TemporaryDirectory() as tmpdir:
        store = _make_store(tmpdir, archivo_duracion_s=1)

        # Trama inicial: 23:59:44 del día 17 (abre el archivo)
        ts_inicio = datetime.datetime(2026, 6, 17, 23, 59, 44)
        store.write_frame(
            build_test_frame(year=2026, month=6, day=17, hour=23, minute=59, second=44),
            ts_inicio
        )

        # Esperar a que el tiempo real supere archivo_duracion_s=1s
        time.sleep(1.1)

        # Trama con regresión temporal: 00:00:01 pero fecha del día 17 (bug dsPIC)
        # delta_ts = datetime(17, 00:00:01) - datetime(17, 23:59:44) = -86383s (negativo)
        ts_regresion = datetime.datetime(2026, 6, 17, 0, 0, 1)  # Fecha incorrecta del dsPIC
        store.write_frame(
            build_test_frame(year=2026, month=6, day=17, hour=0, minute=0, second=1),
            ts_regresion
        )
        store.close()

        archivos = sorted(
            f for f in os.listdir(tmpdir) if f.endswith('.bin')
        )
        assert len(archivos) >= 2, (
            f"Bug de cambio de día: deben existir al menos 2 archivos tras rotación, "
            f"encontrados: {archivos}. El archivo se bloqueó sin rotar."
        )


# ---------------------------------------------------------------------------
# Tests: política de retención FIFO
# ---------------------------------------------------------------------------

def test_retencion_elimina_archivos_antiguos():
    """La política FIFO elimina archivos cuando se supera max_size_mb."""
    with tempfile.TemporaryDirectory() as tmpdir:
        # Tamaño máximo muy pequeño: 1 MB (permite ~400 tramas de 2506B)
        # Con duración de 2 s por archivo, necesitamos escribir suficientes tramas
        # para superar el límite. Usamos 1 MB límite.
        # 1 MB / 2506 B ≈ 410 tramas → necesitamos más de eso
        store = _make_store(tmpdir, max_size_mb=1, archivo_duracion_s=200)

        # Escribir tramas para dos archivos de 200 segundos cada uno (~500 KB)
        # El primer archivo: ss=0..199 a las 14:00:xx
        for s in range(200):
            h = 14 + s // 3600
            m = (s % 3600) // 60
            sec = s % 60
            ts = datetime.datetime(2026, 6, 16, h, m, sec)
            store.write_frame(
                build_test_frame(year=2026, month=6, day=16, hour=h, minute=m, second=sec),
                ts
            )

        # Verificar que hay al menos 1 archivo antes de saturar
        archivos_antes = len([f for f in os.listdir(tmpdir) if f.endswith('.bin')])
        assert archivos_antes >= 1, "Debe haber al menos 1 archivo creado"

        # Escribir un segundo bloque de 200 tramas para saturar el límite de 1 MB
        for s in range(200, 400):
            h = 14 + s // 3600
            m = (s % 3600) // 60
            sec = s % 60
            ts = datetime.datetime(2026, 6, 16, h, m, sec)
            store.write_frame(
                build_test_frame(year=2026, month=6, day=16, hour=h, minute=m, second=sec),
                ts
            )

        store.close()

        # El directorio debe tener menos archivos de los que se crearían sin retención
        # (porque los más antiguos se eliminaron)
        uso_mb = store.get_disk_usage_mb()
        assert uso_mb <= 1.0 + 0.8, \
            f"Uso en disco {uso_mb:.2f} MB debería ser ≤ max_size_mb + 1 archivo"


def test_retencion_no_elimina_archivo_activo():
    """La retención nunca elimina el archivo activo en escritura."""
    with tempfile.TemporaryDirectory() as tmpdir:
        # Límite muy pequeño: casi 0 MB → solo puede existir el archivo activo
        store = _make_store(tmpdir, max_size_mb=1, archivo_duracion_s=3600)

        for s in range(10):
            ts = datetime.datetime(2026, 6, 16, 14, 30, s)
            store.write_frame(
                build_test_frame(year=2026, month=6, day=16, hour=14, minute=30, second=s),
                ts
            )

        # No debe lanzar ninguna excepción y debe haber al menos 1 archivo
        archivos = [f for f in os.listdir(tmpdir) if f.endswith('.bin')]
        assert len(archivos) >= 1, "Debe existir al menos 1 archivo (el activo)"
        store.close()


# ---------------------------------------------------------------------------
# Tests: reconstrucción del índice
# ---------------------------------------------------------------------------

def test_rebuild_index_recupera_archivos_existentes():
    """_rebuild_index() reconstruye el índice desde archivos .bin existentes."""
    with tempfile.TemporaryDirectory() as tmpdir:
        # Primera instancia: escribir datos y cerrar
        store1 = _make_store(tmpdir, archivo_duracion_s=3600)
        for s in range(3):
            ts = _ts(hour=14, minute=30, second=s)
            store1.write_frame(_make_frame(hour=14, minute=30, second=s), ts)
        store1.close()

        # Segunda instancia: debe reconstruir el índice automáticamente
        store2 = _make_store(tmpdir, archivo_duracion_s=3600)
        time_range = store2.get_time_range()
        assert time_range is not None, "rango no debe ser None tras recuperación"

        oldest, newest = time_range
        assert oldest.second == 0, f"oldest.second esperado 0, obtenido {oldest.second}"
        assert newest.second == 2, f"newest.second esperado 2, obtenido {newest.second}"

        # Consultar también debe funcionar
        results = store2.query_raw(
            start=_ts(hour=14, minute=30, second=0),
            end=_ts(hour=14, minute=30, second=59)
        )
        _assert_eq(len(results), 3, "3 tramas recuperadas tras reconstrucción del índice")
        store2.close()


def test_rebuild_index_ignora_archivos_corruptos():
    """_rebuild_index() ignora archivos con tamaño < FRAME_SIZE."""
    with tempfile.TemporaryDirectory() as tmpdir:
        # Crear un archivo .bin corrupto (menos de FRAME_SIZE bytes)
        corrupto = os.path.join(tmpdir, "ring_20260616_143000.bin")
        with open(corrupto, "wb") as f:
            f.write(b'\x00' * 100)  # Demasiado pequeño

        store = _make_store(tmpdir)
        _assert_eq(store.get_time_range(), None, "buffer vacío con archivo corrupto")
        store.close()


# ---------------------------------------------------------------------------
# Tests: thread-safety
# ---------------------------------------------------------------------------

def test_escritura_concurrente_no_corrompe():
    """Escrituras desde múltiples hilos no producen corrupción."""
    with tempfile.TemporaryDirectory() as tmpdir:
        store = _make_store(tmpdir, archivo_duracion_s=3600)
        errores = []

        def escritor(hilo_id, n_tramas):
            for i in range(n_tramas):
                try:
                    s = (hilo_id * 10 + i) % 60
                    ts = datetime.datetime(2026, 6, 16, 14, 30, s)
                    raw = build_test_frame(
                        year=2026, month=6, day=16, hour=14, minute=30, second=s
                    )
                    store.write_frame(raw, ts)
                    time.sleep(0.001)
                except Exception as e:
                    errores.append(str(e))

        hilos = [threading.Thread(target=escritor, args=(i, 5)) for i in range(3)]
        for h in hilos:
            h.start()
        for h in hilos:
            h.join()

        assert len(errores) == 0, f"Errores en escritura concurrente: {errores}"

        # Verificar que el archivo no está corrupto (todas las tramas son múltiplos de FRAME_SIZE)
        for entry in store._index:
            assert entry.size_bytes % FRAME_SIZE == 0, \
                f"Archivo {entry.filepath} tiene tamaño no múltiplo de {FRAME_SIZE}"

        store.close()


# ---------------------------------------------------------------------------
# Tests: get_time_range y get_disk_usage_mb
# ---------------------------------------------------------------------------

def test_time_range_vacio():
    """get_time_range() retorna None en buffer vacío."""
    with tempfile.TemporaryDirectory() as tmpdir:
        store = _make_store(tmpdir)
        _assert_eq(store.get_time_range(), None, "None en buffer vacío")
        store.close()


def test_time_range_con_datos():
    """get_time_range() retorna el rango correcto."""
    with tempfile.TemporaryDirectory() as tmpdir:
        store = _make_store(tmpdir, archivo_duracion_s=3600)
        store.write_frame(_make_frame(hour=14, minute=0, second=0), _ts(hour=14, minute=0, second=0))
        store.write_frame(_make_frame(hour=14, minute=0, second=59), _ts(hour=14, minute=0, second=59))

        tr = store.get_time_range()
        assert tr is not None
        oldest, newest = tr
        _assert_eq(oldest.second, 0, "oldest.second")
        _assert_eq(newest.second, 59, "newest.second")
        store.close()


def test_disk_usage_mb():
    """get_disk_usage_mb() refleja el espacio real de los archivos."""
    with tempfile.TemporaryDirectory() as tmpdir:
        store = _make_store(tmpdir, archivo_duracion_s=3600)
        n = 10
        for s in range(n):
            store.write_frame(_make_frame(hour=14, minute=30, second=s), _ts(minute=30, second=s))

        # Puede haber un archivo no flusheado todavía, pero la cuenta del índice debe ser consistente
        uso = store.get_disk_usage_mb()
        esperado_mb = (n * FRAME_SIZE) / (1024 * 1024)
        assert abs(uso - esperado_mb) < 0.001, \
            f"Uso en disco {uso:.4f} MB, esperado ~{esperado_mb:.4f} MB"
        store.close()


# ---------------------------------------------------------------------------
# Punto de entrada
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("\n" + "=" * 65)
    print("  Tests: streaming/ring_buffer_store.py")
    print("=" * 65)

    grupos = [
        ("inicialización y estructura", [
            test_init_crea_directorio,
            test_init_directorio_vacio,
            test_write_frame_tamanio_invalido,
        ]),
        ("escritura y consulta básica", [
            test_write_y_query_una_trama,
            test_write_multiples_tramas_query_rango,
            test_query_rango_fuera_de_buffer,
            test_query_start_mayor_que_end_lanza_valueerror,
            test_query_retorna_framedata,
        ]),
        ("rotación de archivos", [
            test_rotacion_crea_nuevo_archivo,
            test_naming_archivos_ring,
            test_query_abarca_multiples_archivos,
            test_rotacion_bug_cambio_dia,
        ]),
        ("política de retención FIFO", [
            test_retencion_elimina_archivos_antiguos,
            test_retencion_no_elimina_archivo_activo,
        ]),
        ("reconstrucción del índice", [
            test_rebuild_index_recupera_archivos_existentes,
            test_rebuild_index_ignora_archivos_corruptos,
        ]),
        ("thread-safety", [
            test_escritura_concurrente_no_corrompe,
        ]),
        ("get_time_range y get_disk_usage_mb", [
            test_time_range_vacio,
            test_time_range_con_datos,
            test_disk_usage_mb,
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

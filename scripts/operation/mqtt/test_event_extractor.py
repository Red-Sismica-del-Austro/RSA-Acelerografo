#!/usr/bin/env python3
"""
Tests unitarios para mqtt/event_extractor.py

Ejecutar:
    cd /home/rsa/git/montajes/acelerografo-DEV00
    python3 scripts/operation/mqtt/test_event_extractor.py

o con pytest:
    python3 -m pytest scripts/operation/mqtt/test_event_extractor.py -v

Utiliza unittest.mock para simular los subprocesos de conversión y subida,
y directorios temporales para validar el flujo completo sin hardware real.
"""

import os
import sys
import datetime
import tempfile
import json
import shutil
import traceback
from unittest.mock import patch, MagicMock

# Agregar el directorio scripts/operation al path
operation_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if operation_dir not in sys.path:
    sys.path.insert(0, operation_dir)

from core.frame_decoder import build_test_frame
from streaming.ring_buffer_store import RingBufferStore
from mqtt.event_extractor import extraer_y_subir_evento

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


# ---------------------------------------------------------------------------
# Entorno ficticio para tests
# ---------------------------------------------------------------------------

class TestEnvironment:
    """Clase para configurar y limpiar un entorno temporal de pruebas."""
    def __init__(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = self.temp_dir.name
        
        # Subdirectorios estándar
        self.config_dir = os.path.join(self.root, "configuracion")
        self.ring_buffer_dir = os.path.join(self.root, "data", "ring-buffer")
        self.mseed_dir = os.path.join(self.root, "data", "mseed")
        self.eventos_dir = os.path.join(self.root, "data", "eventos-extraidos")
        self.tmp_files_dir = os.path.join(self.root, "tmp-files")
        
        for d in [self.config_dir, self.ring_buffer_dir, self.mseed_dir, self.eventos_dir, self.tmp_files_dir]:
            os.makedirs(d, exist_ok=True)
            
        # Mock de variables de entorno y sys.path
        self._orig_env = os.environ.get("PROJECT_LOCAL_ROOT")
        os.environ["PROJECT_LOCAL_ROOT"] = self.root
        
        # Crear archivos de configuración simulados
        self.escribir_configuraciones(streaming_habilitado=True)
        
    def escribir_configuraciones(self, streaming_habilitado=True):
        config_disp = {
            "dispositivo": {"id": "DEV00"},
            "directorios": {
                "registro_continuo": self.ring_buffer_dir,  # Solo para fallback o referencias
                "archivos_mseed": self.mseed_dir,
                "eventos_extraidos": self.eventos_dir
            },
            "streaming": {
                "habilitado": streaming_habilitado,
                "ring_buffer": {
                    "directorio": self.ring_buffer_dir,
                    "max_size_mb": 10,
                    "archivo_duracion_min": 5
                }
            }
        }
        config_mseed = {
            "CODIGO(1)": "DEV00",
            "SENSOR(2)": "ACELEROMETRO",
            "MUESTREO(20)": 250,
            "CALIDAD(16)": "D",
            "RED(19)": "GI",
            "UBICACION(17)": "00",
            "CANAL(18)": "XYZ",
            "USAR_FECHA_FILENAME": True
        }
        
        with open(os.path.join(self.config_dir, "configuracion_dispositivo.json"), "w") as f:
            json.dump(config_disp, f)
            
        with open(os.path.join(self.config_dir, "configuracion_mseed.json"), "w") as f:
            json.dump(config_mseed, f)
            
    def crear_venv_python_mock(self):
        # Crear estructura de .venv para engañar a event_extractor
        venv_bin = os.path.join(self.root, ".venv", "bin")
        os.makedirs(venv_bin, exist_ok=True)
        # Crear un dummy executable o archivo
        dummy_python = os.path.join(venv_bin, "python3")
        with open(dummy_python, "w") as f:
            f.write("#!/bin/sh\nexit 0\n")
        os.chmod(dummy_python, 0o755)
        
    def cleanup(self):
        if self._orig_env is not None:
            os.environ["PROJECT_LOCAL_ROOT"] = self._orig_env
        else:
            os.environ.pop("PROJECT_LOCAL_ROOT", None)
        self.temp_dir.cleanup()


# ---------------------------------------------------------------------------
# Tests unitarios
# ---------------------------------------------------------------------------

def test_extraccion_exito_desde_ring_buffer():
    """Extracción exitosa desde el ring buffer (evita extract_segment.py)."""
    env = TestEnvironment()
    env.crear_venv_python_mock()
    
    # Escribir algunas tramas de prueba en el ring buffer temporal
    store = RingBufferStore(
        directorio=env.ring_buffer_dir,
        max_size_mb=10,
        archivo_duracion_s=300,
        usar_fecha_filename=False
    )
    # Escribir tramas desde las 14:30:00 a las 14:30:05
    start_time = datetime.datetime(2026, 6, 17, 14, 30, 0)
    for s in range(6):
        ts = start_time + datetime.timedelta(seconds=s)
        frame = build_test_frame(
            year=2026, month=6, day=17,
            hour=14, minute=30, second=s,
            x_value=s * 10
        )
        store.write_frame(frame, ts)
    store.close()
    
    # Simular la llamada a binary_to_mseed.py
    # Cuando se ejecute binary_to_mseed.py, creamos el archivo mseed de salida ficticio
    # y devolvemos su ruta en el stdout.
    mseed_generado_name = "DEV00_20260617_143000.mseed"
    mseed_generado_path = os.path.join(env.mseed_dir, mseed_generado_name)
    
    def side_effect_run(cmd, *args, **kwargs):
        # cmd es una lista como: ['.venv/bin/python3', '.../binary_to_mseed.py', '--file', '...']
        if "binary_to_mseed.py" in cmd[1]:
            # Simular creación del archivo de salida por parte de binary_to_mseed.py
            with open(mseed_generado_path, "w") as f:
                f.write("DUMMY MSEED DATA")
            
            # Devolver respuesta simulada en stdout
            mock_res = MagicMock()
            mock_res.returncode = 0
            mock_res.stdout = f"output     : {mseed_generado_path}\n"
            mock_res.stderr = ""
            return mock_res
        
        # Subida a Drive
        if "subir_archivo.py" in cmd[1]:
            mock_res = MagicMock()
            mock_res.returncode = 0
            mock_res.stdout = "Subida completada con éxito\n"
            mock_res.stderr = ""
            return mock_res
            
        raise ValueError(f"Comando no esperado en mock: {cmd}")
        
    with patch("subprocess.run", side_effect=side_effect_run) as mock_run:
        # Llamar a extraer_y_subir_evento
        res = extraer_y_subir_evento(
            start="2026-06-17Z14:30:01",
            duration=3.0,
            upload=True,
            delete_after_upload=False
        )
        
        _assert_eq(res["status"], "completed", "estado exitoso")
        _assert_eq(res["source"], "ring_buffer", "fuente ring buffer")
        _assert_eq(res["output_file"], mseed_generado_name, "nombre del archivo")
        _assert_eq(res["uploaded"], True, "subido a Drive")
        
        # Verificar que el mseed está en el directorio de eventos
        mseed_destino = os.path.join(env.eventos_dir, mseed_generado_name)
        assert os.path.exists(mseed_destino), f"El archivo debe haberse movido a {mseed_destino}"
        
        # El archivo mseed temporal en mseed_dir no debe existir (se movió)
        assert not os.path.exists(mseed_generado_path), "El temporal de mseed_dir debe haberse movido"
        
        # Verificar que se llamó a binary_to_mseed pero NO a extract_segment
        llamados = []
        for call_args in mock_run.call_args_list:
            args, _ = call_args
            if args and isinstance(args[0], list):
                for arg in args[0]:
                    if "binary_to_mseed.py" in arg or "extract_segment.py" in arg:
                        llamados.append(os.path.basename(arg))
        assert "binary_to_mseed.py" in llamados, "Se debió llamar a binary_to_mseed.py"
        assert "extract_segment.py" not in llamados, "NO se debió llamar a extract_segment.py"

    env.cleanup()


def test_extraccion_fallback_rango_fuera_de_ring_buffer():
    """Extracción cae a extract_segment.py si el rango no está cubierto por el ring buffer."""
    env = TestEnvironment()
    env.crear_venv_python_mock()
    
    # Escribir algunas tramas en el ring buffer
    store = RingBufferStore(
        directorio=env.ring_buffer_dir,
        max_size_mb=10,
        archivo_duracion_s=300,
        usar_fecha_filename=False
    )
    start_time = datetime.datetime(2026, 6, 17, 14, 30, 0)
    for s in range(5):
        store.write_frame(build_test_frame(year=2026, month=6, day=17, hour=14, minute=30, second=s), start_time + datetime.timedelta(seconds=s))
    store.close()
    
    # Solicitamos un rango fuera del ring buffer (ej: 14:35:00)
    mseed_generado_name = "DEV00_20260617_143500.mseed"
    mseed_generado_path = os.path.join(env.eventos_dir, mseed_generado_name)
    
    def side_effect_run(cmd, *args, **kwargs):
        if "extract_segment.py" in cmd[1]:
            # Simular creación del mseed directamente en eventos_dir
            with open(mseed_generado_path, "w") as f:
                f.write("DUMMY MSEED FROM ARCHIVE")
            mock_res = MagicMock()
            mock_res.returncode = 0
            mock_res.stdout = f"Archivo:  {mseed_generado_path}\n"
            mock_res.stderr = ""
            return mock_res
        if "subir_archivo.py" in cmd[1]:
            mock_res = MagicMock()
            mock_res.returncode = 0
            mock_res.stdout = "Subida OK\n"
            mock_res.stderr = ""
            return mock_res
        raise ValueError(f"Comando no esperado en mock: {cmd}")
        
    with patch("subprocess.run", side_effect=side_effect_run) as mock_run:
        res = extraer_y_subir_evento(
            start="2026-06-17Z14:35:00",
            duration=10.0,
            upload=True,
            delete_after_upload=False
        )
        
        _assert_eq(res["status"], "completed", "estado exitoso")
        _assert_eq(res["source"], "mseed_archive", "fuente archivo mseed")
        _assert_eq(res["output_file"], mseed_generado_name, "archivo extraído")
        
        # Verificar que se llamó a extract_segment
        llamados = []
        for call_args in mock_run.call_args_list:
            args, _ = call_args
            if args and isinstance(args[0], list):
                for arg in args[0]:
                    if "binary_to_mseed.py" in arg or "extract_segment.py" in arg:
                        llamados.append(os.path.basename(arg))
        assert "extract_segment.py" in llamados, "Se debió ejecutar extract_segment.py"
        assert "binary_to_mseed.py" not in llamados, "NO se debió ejecutar binary_to_mseed.py"
        
    env.cleanup()


def test_extraccion_directa_cuando_streaming_deshabilitado():
    """Extracción va directo a extract_segment.py si el streaming está deshabilitado."""
    env = TestEnvironment()
    env.escribir_configuraciones(streaming_habilitado=False)
    env.crear_venv_python_mock()
    
    mseed_generado_name = "DEV00_20260617_143000.mseed"
    mseed_generado_path = os.path.join(env.eventos_dir, mseed_generado_name)
    
    def side_effect_run(cmd, *args, **kwargs):
        if "extract_segment.py" in cmd[1]:
            with open(mseed_generado_path, "w") as f:
                f.write("DUMMY MSEED")
            mock_res = MagicMock()
            mock_res.returncode = 0
            mock_res.stdout = f"Archivo:  {mseed_generado_path}\n"
            mock_res.stderr = ""
            return mock_res
        if "subir_archivo.py" in cmd[1]:
            mock_res = MagicMock()
            mock_res.returncode = 0
            return mock_res
        raise ValueError(f"Comando no esperado: {cmd}")
        
    with patch("subprocess.run", side_effect=side_effect_run) as mock_run:
        res = extraer_y_subir_evento(
            start="2026-06-17Z14:30:00",
            duration=5.0,
            upload=True
        )
        
        _assert_eq(res["status"], "completed")
        _assert_eq(res["source"], "mseed_archive")
        
        # Verificar que NO se instanció el ring buffer ni se buscó en él
        llamados = []
        for call_args in mock_run.call_args_list:
            args, _ = call_args
            if args and isinstance(args[0], list):
                for arg in args[0]:
                    if "binary_to_mseed.py" in arg or "extract_segment.py" in arg:
                        llamados.append(os.path.basename(arg))
        assert "extract_segment.py" in llamados
        assert "binary_to_mseed.py" not in llamados
        
    env.cleanup()


# ---------------------------------------------------------------------------
# Punto de entrada
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("\n" + "=" * 65)
    print("  Tests: mqtt/event_extractor.py")
    print("=" * 65)

    grupos = [
        ("flujo de extracción y fallback", [
            test_extraccion_exito_desde_ring_buffer,
            test_extraccion_fallback_rango_fuera_de_ring_buffer,
            test_extraccion_directa_cuando_streaming_deshabilitado,
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

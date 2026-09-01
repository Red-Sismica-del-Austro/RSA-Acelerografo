"""
test_event_logger.py — Suite de tests unitarios para core/event_logger.py

Tests incluidos:
    test_crear_csv_nuevo           — Se crea el archivo con headers en el primer registro
    test_registrar_deteccion       — La fila se escribe con todos los campos correctos
    test_registrar_multiples       — Múltiples registros se acumulan sin sobrescribir
    test_actualizar_confirmacion   — Actualiza confirmado y archivo_mseed de un registro
    test_actualizar_no_encontrado  — Retorna False cuando el timestamp no existe
    test_registrar_evento_externo  — Crea fila con fase=EXTERNAL y metodo=network_cmd
    test_concurrencia              — 10 hilos escriben simultáneamente sin corrupción
    test_rotacion_mensual          — Meses distintos → archivos CSV separados

Cada test usa un directorio temporal (tempfile.mkdtemp) y lo elimina al finalizar.
No requiere hardware, red ni dependencias externas.

Uso:
    python3 -m pytest test_event_logger.py -v
    python3 test_event_logger.py
"""

import csv
import os
import sys
import tempfile
import threading
import shutil
import unittest
from datetime import datetime, timezone

# Asegurar que el directorio padre (operation/) esté en el path
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_OPERATION_DIR = os.path.dirname(_SCRIPT_DIR)
if _OPERATION_DIR not in sys.path:
    sys.path.insert(0, _OPERATION_DIR)

from core.event_logger import EventLogger, CSV_HEADERS


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _leer_csv(path: str) -> list[dict]:
    """Devuelve todas las filas del CSV como lista de dicts."""
    with open(path, "r", newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestEventLogger(unittest.TestCase):

    def setUp(self):
        """Crea un directorio temporal exclusivo para cada test."""
        self.tmp_dir = tempfile.mkdtemp(prefix="test_event_logger_")
        self.logger = EventLogger(csv_dir=self.tmp_dir)

    def tearDown(self):
        """Elimina el directorio temporal al finalizar el test."""
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    # -------------------------------------------------------------------
    # test_crear_csv_nuevo
    # -------------------------------------------------------------------
    def test_crear_csv_nuevo(self):
        """Al registrar la primera detección se crea el CSV con los headers correctos."""
        ts = "2026-07-06T15:30:00.000Z"
        self.logger.registrar_deteccion(
            timestamp_centro=ts,
            fase="P",
            probabilidad=0.985,
        )

        csv_path = os.path.join(self.tmp_dir, "2026-07_detecciones.csv")
        self.assertTrue(os.path.isfile(csv_path), "El CSV no fue creado")

        with open(csv_path, "r", newline="", encoding="utf-8") as f:
            reader = csv.reader(f)
            headers = next(reader)

        self.assertEqual(headers, CSV_HEADERS,
                         "Los headers del CSV no coinciden con CSV_HEADERS")

    # -------------------------------------------------------------------
    # test_registrar_deteccion
    # -------------------------------------------------------------------
    def test_registrar_deteccion(self):
        """La fila registrada contiene exactamente los campos esperados."""
        ts = "2026-07-06T15:30:00.000Z"
        self.logger.registrar_deteccion(
            timestamp_centro=ts,
            fase="P",
            probabilidad=0.9854,
            confirmado=False,
            archivo_mseed="",
            metodo="local_gpd",
        )

        csv_path = os.path.join(self.tmp_dir, "2026-07_detecciones.csv")
        filas = _leer_csv(csv_path)

        self.assertEqual(len(filas), 1, "Debe haber exactamente 1 fila")
        fila = filas[0]

        self.assertEqual(fila["timestamp_centro"], ts)
        self.assertEqual(fila["fase"], "P")
        self.assertAlmostEqual(float(fila["probabilidad"]), 0.9854, places=3)
        self.assertEqual(fila["confirmado"], "False")
        self.assertEqual(fila["archivo_mseed"], "")
        self.assertEqual(fila["metodo"], "local_gpd")
        # timestamp_local debe ser un ISO8601 UTC no vacío
        self.assertTrue(len(fila["timestamp_local"]) > 10)

    # -------------------------------------------------------------------
    # test_registrar_multiples
    # -------------------------------------------------------------------
    def test_registrar_multiples(self):
        """Múltiples registros se acumulan sin sobrescribirse."""
        timestamps = [
            "2026-07-06T10:00:00.000Z",
            "2026-07-06T11:00:00.000Z",
            "2026-07-06T12:00:00.000Z",
        ]
        for ts in timestamps:
            self.logger.registrar_deteccion(
                timestamp_centro=ts,
                fase="S",
                probabilidad=0.96,
            )

        csv_path = os.path.join(self.tmp_dir, "2026-07_detecciones.csv")
        filas = _leer_csv(csv_path)

        self.assertEqual(len(filas), 3, "Deben existir 3 filas")
        ts_leidos = [f["timestamp_centro"] for f in filas]
        self.assertEqual(ts_leidos, timestamps)

    # -------------------------------------------------------------------
    # test_actualizar_confirmacion
    # -------------------------------------------------------------------
    def test_actualizar_confirmacion(self):
        """Actualiza confirmado=True y archivo_mseed en un registro existente."""
        ts = "2026-07-06T15:30:00.000Z"
        # Registrar como pendiente
        self.logger.registrar_deteccion(
            timestamp_centro=ts,
            fase="P",
            probabilidad=0.98,
            confirmado=False,
        )

        # Actualizar tras extracción
        resultado = self.logger.actualizar_confirmacion(
            timestamp_centro=ts,
            confirmado=True,
            archivo_mseed="DEV00_260706-153000.mseed",
        )
        self.assertTrue(resultado, "Debe retornar True al encontrar el registro")

        csv_path = os.path.join(self.tmp_dir, "2026-07_detecciones.csv")
        filas = _leer_csv(csv_path)

        self.assertEqual(len(filas), 1)
        self.assertEqual(filas[0]["confirmado"], "True")
        self.assertEqual(filas[0]["archivo_mseed"], "DEV00_260706-153000.mseed")

    # -------------------------------------------------------------------
    # test_actualizar_confirmacion_solo_primera_ocurrencia
    # -------------------------------------------------------------------
    def test_actualizar_solo_primera_ocurrencia(self):
        """Si hay dos filas con el mismo timestamp, solo se actualiza la primera."""
        ts = "2026-07-06T15:30:00.000Z"
        self.logger.registrar_deteccion(ts, "P", 0.98, confirmado=False)
        self.logger.registrar_deteccion(ts, "P", 0.97, confirmado=False)

        self.logger.actualizar_confirmacion(ts, confirmado=True, archivo_mseed="evento.mseed")

        csv_path = os.path.join(self.tmp_dir, "2026-07_detecciones.csv")
        filas = _leer_csv(csv_path)

        self.assertEqual(len(filas), 2)
        self.assertEqual(filas[0]["confirmado"], "True")
        self.assertEqual(filas[0]["archivo_mseed"], "evento.mseed")
        # La segunda fila NO debe modificarse
        self.assertEqual(filas[1]["confirmado"], "False")
        self.assertEqual(filas[1]["archivo_mseed"], "")

    # -------------------------------------------------------------------
    # test_actualizar_no_encontrado
    # -------------------------------------------------------------------
    def test_actualizar_no_encontrado(self):
        """Retorna False cuando timestamp_centro no existe en el CSV."""
        ts_existente = "2026-07-06T15:30:00.000Z"
        ts_inexistente = "2026-07-06T99:00:00.000Z"

        self.logger.registrar_deteccion(ts_existente, "P", 0.98)

        resultado = self.logger.actualizar_confirmacion(
            timestamp_centro=ts_inexistente,
            confirmado=True,
        )
        self.assertFalse(resultado, "Debe retornar False cuando no hay match")

    # -------------------------------------------------------------------
    # test_actualizar_csv_no_existe
    # -------------------------------------------------------------------
    def test_actualizar_csv_no_existe(self):
        """Retorna False cuando el CSV mensual no existe."""
        resultado = self.logger.actualizar_confirmacion(
            timestamp_centro="2026-07-06T15:30:00.000Z",
            confirmado=True,
        )
        self.assertFalse(resultado)

    # -------------------------------------------------------------------
    # test_registrar_evento_externo
    # -------------------------------------------------------------------
    def test_registrar_evento_externo(self):
        """Un evento externo se registra con los campos canónicos correctos."""
        ts = "2026-07-06T16:45:12.000Z"
        self.logger.registrar_evento_externo(
            timestamp_centro=ts,
            archivo_mseed="DEV00_260706-164512.mseed",
        )

        csv_path = os.path.join(self.tmp_dir, "2026-07_detecciones.csv")
        filas = _leer_csv(csv_path)

        self.assertEqual(len(filas), 1)
        fila = filas[0]
        self.assertEqual(fila["fase"], "EXTERNAL")
        self.assertAlmostEqual(float(fila["probabilidad"]), 0.0)
        self.assertEqual(fila["confirmado"], "True")
        self.assertEqual(fila["archivo_mseed"], "DEV00_260706-164512.mseed")
        self.assertEqual(fila["metodo"], "network_cmd")

    # -------------------------------------------------------------------
    # test_concurrencia
    # -------------------------------------------------------------------
    def test_concurrencia(self):
        """10 hilos escribiendo simultáneamente no corrompen el CSV."""
        n_hilos = 10
        n_por_hilo = 5
        errores = []

        def _escribir(hilo_id: int):
            try:
                for i in range(n_por_hilo):
                    ts = f"2026-07-06T{hilo_id:02d}:{i:02d}:00.000Z"
                    self.logger.registrar_deteccion(
                        timestamp_centro=ts,
                        fase="P",
                        probabilidad=0.9 + hilo_id * 0.001,
                    )
            except Exception as exc:
                errores.append(str(exc))

        hilos = [threading.Thread(target=_escribir, args=(i,)) for i in range(n_hilos)]
        for h in hilos:
            h.start()
        for h in hilos:
            h.join(timeout=10)

        self.assertEqual(errores, [], f"Errores en hilos: {errores}")

        csv_path = os.path.join(self.tmp_dir, "2026-07_detecciones.csv")
        filas = _leer_csv(csv_path)

        self.assertEqual(
            len(filas), n_hilos * n_por_hilo,
            f"Se esperaban {n_hilos * n_por_hilo} filas, se obtuvieron {len(filas)}"
        )

        # Verificar que todas las filas tienen los headers correctos
        for fila in filas:
            self.assertEqual(set(fila.keys()), set(CSV_HEADERS))

    # -------------------------------------------------------------------
    # test_rotacion_mensual
    # -------------------------------------------------------------------
    def test_rotacion_mensual(self):
        """Detecciones de meses distintos se escriben en archivos CSV separados."""
        ts_julio = "2026-07-15T10:00:00.000Z"
        ts_agosto = "2026-08-03T08:30:00.000Z"

        self.logger.registrar_deteccion(ts_julio, "P", 0.97)
        self.logger.registrar_deteccion(ts_agosto, "S", 0.94)

        csv_julio = os.path.join(self.tmp_dir, "2026-07_detecciones.csv")
        csv_agosto = os.path.join(self.tmp_dir, "2026-08_detecciones.csv")

        self.assertTrue(os.path.isfile(csv_julio), "Debe existir CSV de julio")
        self.assertTrue(os.path.isfile(csv_agosto), "Debe existir CSV de agosto")

        filas_julio = _leer_csv(csv_julio)
        filas_agosto = _leer_csv(csv_agosto)

        self.assertEqual(len(filas_julio), 1)
        self.assertEqual(len(filas_agosto), 1)
        self.assertEqual(filas_julio[0]["timestamp_centro"], ts_julio)
        self.assertEqual(filas_agosto[0]["timestamp_centro"], ts_agosto)

    # -------------------------------------------------------------------
    # test_timestamp_iso_invalido
    # -------------------------------------------------------------------
    def test_timestamp_iso_invalido(self):
        """Un timestamp malformado no crashea y escribe en el CSV del mes actual."""
        ts_invalido = "FECHA_INVALIDA"
        # No debe lanzar excepción
        try:
            self.logger.registrar_deteccion(ts_invalido, "P", 0.90)
        except Exception as exc:
            self.fail(f"registrar_deteccion() lanzó excepción inesperada: {exc}")

        # Debe haber un archivo CSV (el del mes actual)
        ahora = datetime.now(timezone.utc)
        csv_path = os.path.join(self.tmp_dir, f"{ahora.strftime('%Y-%m')}_detecciones.csv")
        self.assertTrue(os.path.isfile(csv_path), "Debe crear el CSV del mes actual")

    # -------------------------------------------------------------------
    # test_directorio_se_crea_automaticamente
    # -------------------------------------------------------------------
    def test_directorio_se_crea_automaticamente(self):
        """El directorio csv_dir se crea automáticamente si no existe."""
        nuevo_dir = os.path.join(self.tmp_dir, "subdir", "events")
        logger = EventLogger(csv_dir=nuevo_dir)
        logger.registrar_deteccion("2026-07-06T10:00:00.000Z", "P", 0.95)

        self.assertTrue(os.path.isdir(nuevo_dir), "El directorio debe crearse automáticamente")

    # -------------------------------------------------------------------
    # test_probabilidad_se_redondea
    # -------------------------------------------------------------------
    def test_probabilidad_se_redondea(self):
        """La probabilidad se almacena redondeada a 4 decimales."""
        ts = "2026-07-06T10:00:00.000Z"
        self.logger.registrar_deteccion(ts, "P", 0.98543219)

        csv_path = os.path.join(self.tmp_dir, "2026-07_detecciones.csv")
        filas = _leer_csv(csv_path)
        self.assertEqual(filas[0]["probabilidad"], "0.9854")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    unittest.main(verbosity=2)

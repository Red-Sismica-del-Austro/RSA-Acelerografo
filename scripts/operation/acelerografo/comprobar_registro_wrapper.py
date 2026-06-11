#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
comprobar_registro_wrapper.py — Wrapper de diagnóstico del registro continuo

Ejecuta el binario compilado 'comprobar_registro' y transforma su salida
de texto plano a un objeto JSON estructurado que el servidor Flask puede
devolver directamente al frontend.

Uso:
    python3 comprobar_registro_wrapper.py

Salida (stdout, JSON):
    {
        "hora_sistema":  "17:28:19",
        "nombre_archivo": "DEV0_26_06_10_17.dat",
        "tamano_archivo": 1253000,
        "fuente_reloj":  "GPS",
        "hora_uc":       "17:28:19",
        "aceleracion_x": 0.00372505,
        "aceleracion_y": -0.00148201,
        "aceleracion_z": 9.80145263,
        "error_reloj":   null
    }

En caso de error del binario, retorna:
    { "error": "<mensaje>" }

Códigos de retorno:
    0 — Éxito
    1 — Error al ejecutar el binario o parsear la salida
"""

import json
import os
import re
import subprocess
import sys

# ---------------------------------------------------------------------------
# Ruta del binario (resuelta desde PROJECT_LOCAL_ROOT)
# ---------------------------------------------------------------------------

PROJECT_LOCAL_ROOT = os.getenv("PROJECT_LOCAL_ROOT")
if not PROJECT_LOCAL_ROOT:
    print(json.dumps({"error": "La variable PROJECT_LOCAL_ROOT no está configurada."}))
    sys.exit(1)

BINARIO = os.path.join(
    PROJECT_LOCAL_ROOT, "scripts", "acelerografo", "ejecutables", "comprobar_registro"
)

if not os.path.isfile(BINARIO):
    print(json.dumps({"error": f"Binario no encontrado: {BINARIO}"}))
    sys.exit(1)


# ---------------------------------------------------------------------------
# Ejecución del binario
# ---------------------------------------------------------------------------

try:
    resultado = subprocess.run(
        [BINARIO],
        capture_output=True,
        text=True,
        timeout=10,
        env=os.environ.copy(),
    )
except subprocess.TimeoutExpired:
    print(json.dumps({"error": "El binario comprobar_registro tardó demasiado (timeout 10s)."}))
    sys.exit(1)
except Exception as exc:
    print(json.dumps({"error": f"Error al ejecutar el binario: {exc}"}))
    sys.exit(1)

if resultado.returncode != 0:
    stderr_msg = resultado.stderr.strip() or "Error desconocido."
    print(json.dumps({"error": stderr_msg}))
    sys.exit(1)

salida = resultado.stdout

# ---------------------------------------------------------------------------
# Parseo de la salida de texto plano
#
# Formato esperado del programa C:
#
#   Tiempo del sistema:
#   26/06/10 17:28:19
#
#   Archivo actual: 'DEV0_26_06_10_17.dat'
#   Tamaño del archivo:1253000
#
#   Datos de la trama:
#   | GPS 26/06/10 17:28:19-62319 | X: 0.00372505 Y: -0.00148201 Z: 9.80145263 |
# ---------------------------------------------------------------------------

datos = {
    "hora_sistema":   None,
    "nombre_archivo": None,
    "tamano_archivo": None,
    "fuente_reloj":   None,
    "hora_uc":        None,
    "aceleracion_x":  None,
    "aceleracion_y":  None,
    "aceleracion_z":  None,
    "error_reloj":    None,
}

lineas = salida.splitlines()

for i, linea in enumerate(lineas):
    linea_s = linea.strip()

    # --- Hora del sistema ---
    # Línea previa: "Tiempo del sistema:"
    # Línea siguiente: "YY/MM/DD HH:MM:SS"
    if linea_s == "Tiempo del sistema:":
        if i + 1 < len(lineas):
            m = re.search(r"(\d{2}:\d{2}:\d{2})$", lineas[i + 1].strip())
            if m:
                datos["hora_sistema"] = m.group(1)

    # --- Nombre del archivo actual ---
    # Línea: "Archivo actual: 'DEV0_26_06_10_17.dat'"
    m = re.match(r"Archivo actual:\s*'([^']+)'", linea_s)
    if m:
        datos["nombre_archivo"] = m.group(1)

    # --- Tamaño del archivo ---
    # Línea: "Tamaño del archivo:1253000"
    m = re.match(r"Tama[ñn]o del archivo:(\d+)", linea_s)
    if m:
        datos["tamano_archivo"] = int(m.group(1))

    # --- Datos de la trama: fuente reloj + hora uC + aceleraciones ---
    # Línea: "| GPS 26/06/10 17:28:19-62319 | X: 0.00372505 Y: -0.00148201 Z: 9.80145263 |"
    # También puede ser: "| RPi ... |" o "| RTC ... |" o "| E3 ... |"
    m = re.match(
        r"\|\s*(\S+)\s+"                            # fuente_reloj (GPS, RPi, RTC, E3…)
        r"\d{2}/\d{2}/\d{2}\s+"                    # fecha uC (aa/mm/dd)
        r"(\d{2}:\d{2}:\d{2})-\d+\s*\|"            # hora_uc + segundos totales
        r"\s*X:\s*([-\d.]+)\s+"                    # X
        r"Y:\s*([-\d.]+)\s+"                       # Y
        r"Z:\s*([-\d.]+)\s*\|",                    # Z
        linea_s,
    )
    if m:
        datos["fuente_reloj"]  = m.group(1)
        datos["hora_uc"]       = m.group(2)
        datos["aceleracion_x"] = float(m.group(3))
        datos["aceleracion_y"] = float(m.group(4))
        datos["aceleracion_z"] = float(m.group(5))

    # --- Error de reloj ---
    # Líneas: "**Error E3/GPS: No se pudo comprobar..."
    m = re.match(r"\*\*Error\s+(E\d+/\w+):\s*(.+)", linea_s)
    if m:
        datos["error_reloj"] = f"{m.group(1)}: {m.group(2)}"


# ---------------------------------------------------------------------------
# Validación mínima y salida
# ---------------------------------------------------------------------------

campos_criticos = ["hora_sistema", "nombre_archivo", "tamano_archivo"]
faltantes = [c for c in campos_criticos if datos[c] is None]

if faltantes:
    # Retornar la salida cruda como fallback para facilitar depuración
    print(json.dumps({
        "error": f"No se pudieron parsear los campos: {', '.join(faltantes)}. Salida cruda incluida.",
        "salida_cruda": salida,
    }))
    sys.exit(1)

print(json.dumps(datos, ensure_ascii=False))
sys.exit(0)

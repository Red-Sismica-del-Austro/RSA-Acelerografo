#!/usr/bin/env python3
"""
Script de prueba para verificar event_extractor.py de forma aislada,
sin necesidad del broker MQTT ni del coordinador activo.

Uso:
    python3 test_event_extractor.py
    python3 test_event_extractor.py --start "2026-05-10Z14:30:00" --duration 60

Requiere que PROJECT_LOCAL_ROOT esté definida en el entorno.
"""

import os
import sys
import argparse

# Añadir el directorio mqtt al path para importar event_extractor
mqtt_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, mqtt_dir)

# ============================================================================
# DIAGNÓSTICO PREVIO: verificar rutas antes de importar
# ============================================================================

def diagnostico_rutas():
    """Verifica que todas las rutas y dependencias estén disponibles."""
    print("=" * 60)
    print("DIAGNÓSTICO DE RUTAS")
    print("=" * 60)

    ok = True

    # Variable de entorno
    project_local_root = os.getenv("PROJECT_LOCAL_ROOT")
    if not project_local_root:
        print("[FALLO] PROJECT_LOCAL_ROOT no está definida")
        ok = False
    else:
        print(f"[OK]    PROJECT_LOCAL_ROOT = {project_local_root}")

        # Entorno virtual
        venv_python = os.path.join(project_local_root, ".venv", "bin", "python3")
        if os.path.exists(venv_python):
            print(f"[OK]    .venv/bin/python3 encontrado: {venv_python}")
        else:
            print(f"[FALLO] .venv/bin/python3 NO encontrado: {venv_python}")
            ok = False

    # Ubicar los scripts hermanos
    operation_dir = os.path.dirname(mqtt_dir)

    extract_script = os.path.join(operation_dir, "mseed", "extract_segment.py")
    if os.path.exists(extract_script):
        print(f"[OK]    extract_segment.py encontrado: {extract_script}")
    else:
        print(f"[FALLO] extract_segment.py NO encontrado: {extract_script}")
        ok = False

    upload_script = os.path.join(operation_dir, "drive", "subir_archivo.py")
    if os.path.exists(upload_script):
        print(f"[OK]    subir_archivo.py encontrado: {upload_script}")
    else:
        print(f"[FALLO] subir_archivo.py NO encontrado: {upload_script}")
        ok = False

    # Directorio de eventos extraídos
    if project_local_root:
        import json
        config_path = os.path.join(project_local_root, "configuracion", "configuracion_dispositivo.json")
        if os.path.exists(config_path):
            print(f"[OK]    configuracion_dispositivo.json encontrado")
            try:
                with open(config_path) as f:
                    config = json.load(f)
                eventos_dir = config.get("directorios", {}).get("eventos_extraidos", "")
                mseed_dir   = config.get("directorios", {}).get("archivos_mseed", "")
                print(f"[INFO]  directorios.eventos_extraidos = {eventos_dir}")
                print(f"[INFO]  directorios.archivos_mseed    = {mseed_dir}")
                if not os.path.exists(eventos_dir):
                    print(f"[AVISO] El directorio de eventos NO existe todavía: {eventos_dir}")
                if not os.path.exists(mseed_dir):
                    print(f"[AVISO] El directorio de mseed NO existe: {mseed_dir}")
            except Exception as e:
                print(f"[AVISO] No se pudo leer configuracion_dispositivo.json: {e}")
        else:
            print(f"[FALLO] configuracion_dispositivo.json NO encontrado: {config_path}")
            ok = False

    print()
    return ok


# ============================================================================
# PRUEBA DE EXTRACCIÓN (sin subida a Drive)
# ============================================================================

def prueba_extraccion(start: str, duration: float):
    """Llama a extraer_y_subir_evento() con upload=False y muestra el resultado."""
    print("=" * 60)
    print("PRUEBA DE EXTRACCIÓN (upload=False)")
    print("=" * 60)
    print(f"  start    = {start}")
    print(f"  duration = {duration}s")
    print()

    from event_extractor import extraer_y_subir_evento

    resultado = extraer_y_subir_evento(
        start=start,
        duration=duration,
        upload=False,
        delete_after_upload=False,
        logger=None  # Sin logger estructurado; los prints del módulo son suficientes
    )

    print()
    print("─" * 60)
    print("RESULTADO:")
    for clave, valor in resultado.items():
        print(f"  {clave:<15} = {valor}")
    print("─" * 60)
    return resultado["status"] == "completed"


# ============================================================================
# MAIN
# ============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="Verifica el funcionamiento de event_extractor.py"
    )
    parser.add_argument(
        "--start", "-s",
        default=None,
        help='Tiempo de inicio (formato: "YYYY-MM-DDZHH:MM:SS"). '
             'Si se omite, solo ejecuta el diagnóstico de rutas.'
    )
    parser.add_argument(
        "--duration", "-d",
        type=float,
        default=30.0,
        help="Duración en segundos (default: 30)"
    )
    args = parser.parse_args()

    # Siempre ejecutar diagnóstico
    rutas_ok = diagnostico_rutas()

    if not rutas_ok:
        print("[ABORTANDO] Corrige los errores de ruta antes de continuar.")
        sys.exit(1)

    if args.start:
        exito = prueba_extraccion(args.start, args.duration)
        sys.exit(0 if exito else 1)
    else:
        print("[INFO] Diagnóstico completado. Para probar la extracción, usa:")
        print(f'       python3 {os.path.basename(__file__)} --start "2026-05-10Z14:30:00" --duration 30')


if __name__ == "__main__":
    main()

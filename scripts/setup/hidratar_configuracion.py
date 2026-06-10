#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Script de Hidratación de Configuración para la Red Sísmica del Austro (RSA)
Este script lee configuracion_maestra.json y genera los archivos de configuración
individuales para el runtime del acelerógrafo a partir de sus respectivas plantillas.
"""

import os
import sys
import json
import re

def main():
    print("=== Iniciando hidratación de configuración ===")

    # 1. Resolver rutas de Git y Local
    project_git_root = os.getenv("PROJECT_GIT_ROOT")
    project_local_root = os.getenv("PROJECT_LOCAL_ROOT")

    script_dir = os.path.dirname(os.path.abspath(__file__))
    deduced_git_root = os.path.dirname(os.path.dirname(script_dir))

    # Si no se definen variables, deducir
    if not project_git_root:
        project_git_root = deduced_git_root
        print(f"PROJECT_GIT_ROOT no definida. Deduciendo: {project_git_root}")
    if not project_local_root:
        project_local_root = project_git_root
        print(f"PROJECT_LOCAL_ROOT no definida. Usando: {project_local_root}")

    # En Git se usa 'configuration' y en Local se usa 'configuracion'
    git_config_dir = os.path.join(project_git_root, "configuration")
    local_config_dir = os.path.join(project_local_root, "configuracion")

    # Si estamos en entorno de desarrollo/local y no existe 'configuracion', usar 'configuration'
    if not os.path.exists(local_config_dir):
        local_config_dir = git_config_dir

    # Buscar configuración maestra: primero en local_config_dir, fallback a git_config_dir
    master_path = os.path.join(local_config_dir, "configuracion_maestra.json")
    if not os.path.exists(master_path):
        fallback_path = os.path.join(git_config_dir, "configuracion_maestra.json")
        if os.path.exists(fallback_path):
            print(f"Configuración maestra no encontrada en local. Usando fallback de Git: {fallback_path}")
            master_path = fallback_path
        else:
            print(f"Error crítico: No se encontró configuracion_maestra.json ni en local ({master_path}) ni en Git ({fallback_path})", file=sys.stderr)
            sys.exit(1)
    else:
        print(f"Usando configuración maestra local: {master_path}")

    # 2. Cargar y validar configuración maestra
    try:
        with open(master_path, 'r', encoding='utf-8') as f:
            config = json.load(f)
    except Exception as e:
        print(f"Error al decodificar {master_path}: {e}", file=sys.stderr)
        sys.exit(1)

    # Validaciones obligatorias
    required_keys = ["estacion_id", "nombre", "coordenadas", "adquisicion", "drive_folder_ids"]
    for key in required_keys:
        if key not in config:
            print(f"Error crítico: Llave faltante '{key}' en la configuración maestra.", file=sys.stderr)
            sys.exit(1)

    estacion_id = config["estacion_id"]
    # Formato estándar RSA: 3 letras y 1 número (ej: NOM0, CHA1, DEV0)
    if not re.match(r'^[A-Z]{3}\d$', estacion_id):
        print(f"Advertencia: El 'estacion_id' ({estacion_id}) no cumple con el formato estándar RSA de 3 letras y 1 número (ej: NOM0).")

    # 3. Definir plantillas y archivos destino
    mappings = {
        "configuracion_dispositivo.json.template": "configuracion_dispositivo.json",
        "configuracion_mqtt.json.template": "configuracion_mqtt.json",
        "configuracion_mseed.json.template": "configuracion_mseed.json",
        "hostapd.conf.template": "hostapd.conf"
    }

    # Asegurar que el directorio de salida existe
    os.makedirs(local_config_dir, exist_ok=True)

    # 4. Procesar cada plantilla
    for template_name, dest_name in mappings.items():
        # Buscar plantilla: primero en local_config_dir, fallback a git_config_dir
        template_path = os.path.join(local_config_dir, template_name)
        if not os.path.exists(template_path):
            template_path = os.path.join(git_config_dir, template_name)
            
        dest_path = os.path.join(local_config_dir, dest_name)

        if not os.path.exists(template_path):
            print(f"Error crítico: Plantilla no encontrada: {template_path}", file=sys.stderr)
            sys.exit(1)

        try:
            with open(template_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            # Reemplazar marcadores generales
            content = content.replace("{{ESTACION_ID}}", str(config["estacion_id"]))
            content = content.replace("{{NOMBRE}}", str(config["nombre"]))
            content = content.replace("{{LATITUD}}", str(config["coordenadas"].get("latitud", 0.0)))
            content = content.replace("{{LONGITUD}}", str(config["coordenadas"].get("longitud", 0.0)))
            content = content.replace("{{ALTITUD}}", str(config["coordenadas"].get("altitud", 0.0)))
            content = content.replace("{{FUENTE_RELOJ}}", str(config["adquisicion"].get("fuente_reloj", "0")))
            content = content.replace("{{MODO_ADQUISICION}}", str(config["adquisicion"].get("modo_adquisicion", "offline")))
            content = content.replace("{{DETECCION_EVENTOS}}", str(config["adquisicion"].get("deteccion_eventos", "no")))
            content = content.replace("{{PUBLICAR_EVENTOS}}", str(config["adquisicion"].get("publicar_eventos", "no")))
            
            # Carpetas de Drive
            drive_ids = config.get("drive_folder_ids", {})
            content = content.replace("{{DRIVE_CONTINUOS_ID}}", str(drive_ids.get("continuos_id", "")))
            content = content.replace("{{DRIVE_MSEED_ID}}", str(drive_ids.get("mseed_id", "")))
            content = content.replace("{{DRIVE_EVENTS_ID}}", str(drive_ids.get("events_id", "")))
            content = content.replace("{{DRIVE_TMP_ID}}", str(drive_ids.get("tmp_id", "")))
            content = content.replace("{{DRIVE_LOGS_ID}}", str(drive_ids.get("logs_id", "")))

            # Marcadores de WiFi AP (si existen en la plantilla)
            if "wifi_ap" in config:
                wifi_config = config["wifi_ap"]
                # Resolver SSID dinámico que puede contener {{ESTACION_ID}}
                ssid_template = wifi_config.get("ssid", "ACEL-{{ESTACION_ID}}-CONFIG")
                ssid_resolved = ssid_template.replace("{{ESTACION_ID}}", str(config["estacion_id"]))
                
                content = content.replace("{{WIFI_SSID}}", ssid_resolved)
                content = content.replace("{{WIFI_PASSPHRASE}}", str(wifi_config.get("wpa_passphrase", "CambiarEstaContrasenaSegura123")))
                content = content.replace("{{WIFI_CHANNEL}}", str(wifi_config.get("canal", "7")))
                
                hidden_val = "1" if wifi_config.get("ocultar_red", "si") == "si" else "0"
                content = content.replace("{{WIFI_HIDDEN}}", hidden_val)

            # Escribir archivo final
            with open(dest_path, 'w', encoding='utf-8') as f:
                f.write(content)
            
            print(f"Archivo generado exitosamente: {dest_path}")
            
        except Exception as e:
            print(f"Error procesando {template_name} -> {dest_name}: {e}", file=sys.stderr)
            sys.exit(1)

    print("=== Hidratación completada con éxito ===")

if __name__ == "__main__":
    main()

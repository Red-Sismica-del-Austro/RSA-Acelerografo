#!/usr/bin/env python3
"""
Script para extraer segmentos de archivos miniSEED
Extrae una ventana temporal específica de archivos miniSEED horarios organizados por fecha.
"""

import os
import sys
import argparse
from datetime import datetime, timedelta
from pathlib import Path
from obspy import read, UTCDateTime
import re

# ============================================================================
# CONFIGURACIÓN: Directorios por defecto
# ============================================================================
DEFAULT_INPUT_DIR = "/home/rsa/projects/acelerografo/resultados/mseed"
DEFAULT_OUTPUT_DIR = "/home/rsa/projects/acelerografo/resultados/eventos-extraidos"


# ============================================================================
# FUNCIONES AUXILIARES
# ============================================================================

def parse_start_time(start_str):
    """
    Parsea el tiempo de inicio en formato ISO UTC.

    Args:
        start_str: String en formato ISO UTC (e.g., "2024-01-15Z14:30:45.250")

    Returns:
        tuple: (UTCDateTime objeto, datetime objeto en UTC)

    Raises:
        ValueError: Si el formato es inválido
    """
    # Verificar que use formato UTC (Z)
    if 'Z' not in start_str:
        raise ValueError(
            f"Formato de tiempo inválido: {start_str}. "
            "Use formato UTC con 'Z' (e.g., '2024-01-15Z14:30:45.250')"
        )

    # Tiempo UTC - reemplazar 'Z' por espacio para parsear
    time_str = start_str.replace('Z', ' ')

    try:
        # Intentar con milisegundos
        utc_dt = datetime.strptime(time_str, "%Y-%m-%d %H:%M:%S.%f")
    except ValueError:
        try:
            # Intentar sin milisegundos
            utc_dt = datetime.strptime(time_str, "%Y-%m-%d %H:%M:%S")
        except ValueError:
            raise ValueError(f"Formato de tiempo inválido: {start_str}")

    return UTCDateTime(utc_dt), utc_dt


def generate_output_filename(input_filename, start_time_utc):
    """
    Genera el nombre del archivo de salida basándose en el archivo de entrada
    y el nuevo tiempo de inicio.

    Args:
        input_filename: Nombre del archivo de entrada (e.g., "CHA1_20251022_000004.mseed")
        start_time_utc: Tiempo de inicio UTC del segmento extraído (UTCDateTime)

    Returns:
        str: Nombre del archivo de salida (e.g., "CHA1_20251022_000045.mseed")
    """
    # Extraer componentes del nombre original
    # Formato esperado: STATIONID_YYYYMMDD_HHMMSS.mseed
    basename = os.path.basename(input_filename)
    parts = basename.rsplit('.', 1)  # Separar extensión
    name_part = parts[0]
    extension = parts[1] if len(parts) > 1 else 'mseed'

    # Dividir el nombre en componentes
    components = name_part.split('_')

    if len(components) >= 3:
        station_id = components[0]
        # Generar nueva fecha y hora desde el tiempo de inicio UTC
        dt = start_time_utc.datetime
        date_str = dt.strftime("%Y%m%d")
        time_str = dt.strftime("%H%M%S")

        # Construir nuevo nombre
        output_name = f"{station_id}_{date_str}_{time_str}.{extension}"
    else:
        # Si el formato no coincide, agregar timestamp al final
        dt = start_time_utc.datetime
        timestamp = dt.strftime("%Y%m%d_%H%M%S")
        output_name = f"{name_part}_extracted_{timestamp}.{extension}"

    return output_name


def find_mseed_file(input_dir, target_date, target_time_utc):
    """
    Encuentra el archivo miniSEED que contiene el tiempo solicitado.

    Args:
        input_dir: Directorio donde buscar archivos miniSEED
        target_date: Fecha objetivo (datetime.date)
        target_time_utc: Tiempo UTC objetivo (UTCDateTime)

    Returns:
        str: Ruta al archivo miniSEED encontrado

    Raises:
        FileNotFoundError: Si no se encuentra ningún archivo válido
    """
    input_path = Path(input_dir)

    if not input_path.exists():
        raise FileNotFoundError(f"El directorio de entrada no existe: {input_dir}")

    # Patrón de nombre de archivo: IDE1_YYYYMMDD_HHMMSS.mseed
    date_str = target_date.strftime("%Y%m%d")
    pattern = re.compile(rf"^[A-Z0-9]+_{date_str}_\d{{6}}\.mseed$")

    # Buscar archivos que coincidan con la fecha
    matching_files = []
    for file in input_path.glob("*.mseed"):
        if pattern.match(file.name):
            matching_files.append(file)

    if not matching_files:
        raise FileNotFoundError(
            f"No se encontraron archivos miniSEED para la fecha {date_str} en {input_dir}"
        )

    # Verificar cuál archivo contiene el tiempo solicitado
    # (basándose en metadata, no en el nombre)
    for mseed_file in matching_files:
        try:
            stream = read(str(mseed_file), headonly=True)
            file_start = stream[0].stats.starttime
            file_end = stream[0].stats.endtime

            # Verificar si el tiempo objetivo está dentro del rango
            if file_start <= target_time_utc <= file_end:
                return str(mseed_file)

        except Exception as e:
            print(f"Advertencia: Error al leer {mseed_file.name}: {e}", file=sys.stderr)
            continue

    # Si ningún archivo contiene el tiempo exacto, buscar el más cercano
    print(f"Advertencia: No se encontró un archivo que contenga exactamente {target_time_utc}", file=sys.stderr)
    print(f"Archivos disponibles para la fecha {date_str}:", file=sys.stderr)

    for mseed_file in matching_files:
        try:
            stream = read(str(mseed_file), headonly=True)
            file_start = stream[0].stats.starttime
            file_end = stream[0].stats.endtime
            print(f"  - {mseed_file.name}: {file_start} - {file_end}", file=sys.stderr)
        except:
            pass

    raise FileNotFoundError(
        f"Ningún archivo miniSEED contiene el tiempo solicitado: {target_time_utc} (UTC)"
    )


def extract_segment(input_file, output_file, start_time_utc, duration):
    """
    Extrae un segmento de un archivo miniSEED.

    Args:
        input_file: Ruta al archivo miniSEED de entrada
        output_file: Ruta al archivo miniSEED de salida
        start_time_utc: Tiempo de inicio UTC (UTCDateTime)
        duration: Duración en segundos (float)
    """
    print(f"Cargando archivo: {input_file}")
    stream = read(input_file)

    # Calcular tiempo de fin
    end_time_utc = start_time_utc + duration

    print(f"Extrayendo segmento:")
    print(f"  Inicio (UTC): {start_time_utc}")
    print(f"  Fin (UTC):    {end_time_utc}")
    print(f"  Duración:     {duration} segundos")

    # Extraer el segmento (todos los canales)
    segment = stream.slice(starttime=start_time_utc, endtime=end_time_utc)
    segment.trim(starttime=start_time_utc, endtime=end_time_utc, nearest_sample=True)

    if len(segment) == 0:
        raise ValueError(
            f"No se encontraron datos en el intervalo especificado:\n"
            f"  Inicio: {start_time_utc}\n"
            f"  Fin:    {end_time_utc}\n"
            f"Rango disponible en el archivo:\n"
            f"  Inicio: {stream[0].stats.starttime}\n"
            f"  Fin:    {stream[0].stats.endtime}"
        )

    # Determinar encoding basado en el tipo de datos
    import numpy as np
    any_float = any(np.issubdtype(tr.data.dtype, np.floating) for tr in segment)

    if any_float:
        for tr in segment:
            tr.data = tr.data.astype(np.float32, copy=False)
        encoding = 4  # FLOAT32
    else:
        for tr in segment:
            if tr.data.dtype != np.int32:
                tr.data = tr.data.astype(np.int32, copy=False)
        encoding = 11  # STEIM2

    # Guardar el segmento
    segment.write(output_file, format="MSEED", encoding=encoding, reclen=4096)

    print(f"\nSegmento guardado exitosamente:")
    print(f"  Archivo:  {output_file}")
    print(f"  Canales:  {', '.join([tr.stats.channel for tr in segment])}")
    print(f"  Muestras: {sum([tr.stats.npts for tr in segment])} (total)")


# ============================================================================
# FUNCIÓN PRINCIPAL
# ============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="Extrae un segmento temporal de archivos miniSEED organizados por fecha.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Ejemplos de uso:

  # Extraer segmento usando hora UTC
  python extract_segment.py --start "2024-01-15Z19:30:45.250" --duration 60

  # Especificar directorios personalizados
  python extract_segment.py --input /data/mseed --output /data/output \\
      --start "2024-01-15Z19:30:45.250" --duration 60

  # Especificar archivo de salida específico
  python extract_segment.py --start "2024-01-15Z19:30:45.250" --duration 60 \\
      --output /data/output/evento_001.mseed

Notas:
  - El tiempo debe especificarse en formato UTC con 'Z' (e.g., '2024-01-15Z14:30:45.250')
  - Los archivos deben seguir el formato: STATIONID_YYYYMMDD_HHMMSS.mseed
  - La duración se especifica en segundos (puede incluir decimales)
  - El archivo de salida mantiene el formato del archivo de entrada con la hora de inicio actualizada
    Ejemplo: CHA1_20251022_000004.mseed + --start "2025-10-22Z00:00:45" → CHA1_20251022_000045.mseed
        """
    )

    # Argumentos requeridos
    parser.add_argument(
        '--start', '-s',
        required=True,
        help='Tiempo de inicio en formato ISO UTC (e.g., "2024-01-15Z14:30:45.250")'
    )

    parser.add_argument(
        '--duration', '-d',
        type=float,
        required=True,
        help='Duración del segmento en segundos (puede incluir decimales)'
    )

    # Argumentos opcionales
    parser.add_argument(
        '--input', '-i',
        default=DEFAULT_INPUT_DIR,
        help=f'Directorio con archivos miniSEED de entrada (default: {DEFAULT_INPUT_DIR})'
    )

    parser.add_argument(
        '--output', '-o',
        default=None,
        help='Ruta del archivo de salida o directorio (default: auto-generado con formato STATIONID_YYYYMMDD_HHMMSS.mseed en DEFAULT_OUTPUT_DIR)'
    )

    args = parser.parse_args()

    try:
        # 1. Parsear el tiempo de inicio
        start_time_utc, start_dt_utc = parse_start_time(args.start)
        target_date = start_dt_utc.date()

        # 2. Encontrar el archivo miniSEED correcto
        input_file = find_mseed_file(args.input, target_date, start_time_utc)
        print(f"Archivo encontrado: {os.path.basename(input_file)}")

        # 3. Determinar archivo de salida
        # Generar nombre basado en el archivo de entrada y el tiempo de inicio
        output_filename = generate_output_filename(input_file, start_time_utc)

        if args.output:
            # Si output es un directorio, usar el nombre generado
            if os.path.isdir(args.output) or args.output.endswith('/'):
                output_file = os.path.join(args.output, output_filename)
            else:
                # Si es una ruta completa de archivo, usar esa ruta
                output_file = args.output
        else:
            # Usar directorio por defecto con nombre generado
            os.makedirs(DEFAULT_OUTPUT_DIR, exist_ok=True)
            output_file = os.path.join(DEFAULT_OUTPUT_DIR, output_filename)

        # Crear directorio de salida si no existe
        os.makedirs(os.path.dirname(os.path.abspath(output_file)), exist_ok=True)

        # 4. Extraer el segmento
        extract_segment(input_file, output_file, start_time_utc, args.duration)

        return 0

    except Exception as e:
        print(f"\nError: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())

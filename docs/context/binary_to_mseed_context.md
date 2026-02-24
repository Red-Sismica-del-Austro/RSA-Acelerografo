# Contexto del Script binary_to_mseed.py

**Archivo**: [scripts/operation/mseed/binary_to_mseed.py](../../../scripts/operation/mseed/binary_to_mseed.py)

**Propósito**: Convertir archivos binarios (.dat) del acelerógrafo a formato Mini-SEED estándar para análisis sismológico.

**Versión analizada**: Script actual en el repositorio

**Autor**: No especificado en el código

**Fecha de análisis**: 2025-11-25

---

## Tabla de Contenidos

1. [Arquitectura del Sistema](#arquitectura-del-sistema)
2. [Propósito y Casos de Uso](#propósito-y-casos-de-uso)
3. [Dependencias y Librerías](#dependencias-y-librerías)
4. [Flujo de Ejecución Principal](#flujo-de-ejecución-principal)
5. [Funciones Principales](#funciones-principales)
6. [Formato de Datos](#formato-de-datos)
7. [Configuración](#configuración)
8. [Modo de Uso](#modo-de-uso)
9. [Logging y Diagnóstico](#logging-y-diagnóstico)
10. [Consideraciones Importantes](#consideraciones-importantes)
11. [Problemas Identificados](#problemas-identificados)
12. [Mejoras Potenciales](#mejoras-potenciales)

---

## Arquitectura del Sistema

### Posición en el Flujo de Datos

```
┌─────────────────────────────────────────────────────────────────┐
│                    SISTEMA COMPLETO                             │
│                                                                 │
│  1. ADQUISICIÓN (Hardware → dsPIC → RPi)                        │
│     └─ registro_continuo_4.5.0.c                                │
│                    ↓                                            │
│  ┌──────────────────────────────────────────┐                   │
│  │  Archivos Binarios (.dat)                │                   │
│  │  - Formato propietario                   │                   │
│  │  - 2506 bytes/segundo                    │                   │
│  │  - 250 muestras/segundo por eje          │                   │
│  │  - Valores enteros de 20 bits            │                   │
│  └──────────────────┬───────────────────────┘                   │
│                     │                                           │
│                     │ (conversión)                              │
│                     ↓                                           │
│  ┌──────────────────────────────────────────┐                   │
│  │  binary_to_mseed.py                      │◄─── Este programa │
│  │  (este programa)                         │                   │
│  │                                          │                   │
│  │  • Lee configuración JSON                │                   │
│  │  • Procesa archivos .dat                 │                   │
│  │  • Convierte a valores físicos (gales)   │                   │
│  │  • Detecta datos faltantes               │                   │
│  │  • Genera metadatos SEED                 │                   │
│  │  • Escribe formato Mini-SEED (STEIM1)    │                   │
│  └──────────────────┬───────────────────────┘                   │
│                     │                                           │
│                     ↓                                           │
│  ┌──────────────────────────────────────────┐                   │
│  │  Archivos Mini-SEED (.mseed)             │                   │
│  │  - Formato estándar internacional        │                   │
│  │  - Compatible con ObsPy, SAC, etc.       │                   │
│  │  - 3 canales (X, Y, Z)                   │                   │
│  │  - Compresión STEIM1                     │                   │
│  │  - Metadata completo (red, estación...)  │                   │
│  └──────────────────┬───────────────────────┘                   │
│                     │                                           │
│                     ↓                                           │
│  3. DISTRIBUCIÓN                                                │
│     └─ Subida a Google Drive (comentado)                        │
│     └─ Análisis con herramientas estándar                       │
└─────────────────────────────────────────────────────────────────┘
```

---

## Propósito y Casos de Uso

### Propósito Principal

Convertir archivos binarios propietarios del acelerógrafo al formato **Mini-SEED** estándar de la industria sismológica, permitiendo:

1. **Interoperabilidad**: Uso con software estándar (ObsPy, SAC, SeisComP)
2. **Distribución**: Compartir datos con redes sismológicas nacionales/internacionales
3. **Análisis**: Procesamiento con herramientas científicas estándar
4. **Archivado**: Almacenamiento en formato reconocido a largo plazo

### Casos de Uso

#### 1. Conversión Automática de Registro Continuo

**Contexto**: Después de que `registro_continuo_4.5.0.c` cierra un archivo .dat cada hora.

**Flujo**:
```bash
# Llamado por cron o script de gestión
python3 binary_to_mseed.py 1
# o
python3 binary_to_mseed.py --modo rc
```

**Resultado**: Archivo Mini-SEED de ~1 hora con 900,000 muestras (250 Hz × 3600 s).

#### 2. Conversión de Eventos Extraídos

**Contexto**: Después de extraer un evento con `extraer_evento_binario_2.1.1.c`.

**Flujo**:
```bash
# Llamado después de detección de evento
python3 binary_to_mseed.py 2
# o
python3 binary_to_mseed.py --modo ee
```

**Resultado**: Archivo Mini-SEED del evento (duración variable).

#### 3. Conversión Manual

**Contexto**: Análisis retrospectivo o recuperación de datos.

**Flujo**:
```bash
python3 binary_to_mseed.py --modo archivo --nombre RSA01_200325_143045.dat
```

**Resultado**: Conversión de archivo específico sin depender de archivos temporales.

---

## Dependencias y Librerías

### Librerías Externas

```python
import numpy as np                    # Procesamiento numérico vectorizado
from obspy import UTCDateTime         # Timestamps precisos para sismología
from obspy import read, Trace, Stream # Objetos Mini-SEED
import json                           # Lectura de configuración
import logging                        # Sistema de logs
import argparse                       # Parser de argumentos CLI
```

### Dependencias del Sistema

- **Python 3.7+**
- **ObsPy**: Librería especializada para datos sísmicos
- **NumPy**: Versión optimizada con soporte BLAS/LAPACK recomendado

### Archivos de Configuración Requeridos

1. **configuracion_mseed.json**: Metadata de la estación sismológica
2. **configuracion_dispositivo.json**: Rutas y configuración del dispositivo
3. **NombreArchivoRegistroContinuo.tmp**: Nombre del archivo RC a convertir
4. **NombreArchivoEventoExtraido.tmp**: Nombre del archivo de evento a convertir

---

## Flujo de Ejecución Principal

### Diagrama de Flujo

```
main()
    ↓
┌────────────────────────────────────────────┐
│ 1. Parser de argumentos                    │
│    - Modo simple (1/2)                     │
│    - Modo nombrado (rc/ee/archivo)         │
│    - Nombre archivo manual (opcional)      │
└────────────────────────────────────────────┘
    ↓
┌────────────────────────────────────────────┐
│ 2. Validación de entorno                   │
│    - PROJECT_LOCAL_ROOT definida           │
│    - Archivos de configuración existen     │
└────────────────────────────────────────────┘
    ↓
┌────────────────────────────────────────────┐
│ 3. Carga de configuración                  │
│    - read_fileJSON(config_mseed.json)      │
│    - read_fileJSON(config_dispositivo.json)│
└────────────────────────────────────────────┘
    ↓
┌────────────────────────────────────────────┐
│ 4. Determinación de archivo de entrada     │
│    ├─ Modo 1/rc: Lee .tmp de RC            │
│    ├─ Modo 2/ee: Lee .tmp de evento        │
│    └─ Modo archivo: Usa --nombre           │
└────────────────────────────────────────────┘
    ↓
┌────────────────────────────────────────────┐
│ 5. Inicialización de logger                │
│    - obtener_logger(dispositivo_id)        │
│    - Log en PROJECT_LOCAL_ROOT/log-files/  │
└────────────────────────────────────────────┘
    ↓
┌────────────────────────────────────────────┐
│ 6. Extracción de timestamp inicial         │
│    - extraer_tiempo_binario(binary_file)   │
│    - Lee primeros 2506 bytes               │
│    - Extrae fecha/hora de bytes finales    │
└────────────────────────────────────────────┘
    ↓
┌────────────────────────────────────────────┐
│ 7. Lectura y procesamiento del archivo     │
│    - leer_archivo_binario(binary_file)     │
│    - Procesamiento vectorizado con NumPy   │
│    - Detección de datos faltantes          │
│    - Retorna: datos_np[3, n_samples]       │
└────────────────────────────────────────────┘
    ↓
┌────────────────────────────────────────────┐
│ 8. Generación de nombre Mini-SEED          │
│    - nombrar_archivo_mseed()               │
│    - Formato: CODIGO_YYYYMMDD_HHMMSS.mseed │
└────────────────────────────────────────────┘
    ↓
┌────────────────────────────────────────────┐
│ 9. Conversión a Mini-SEED                  │
│    - conversion_mseed_digital()            │
│    - Crea 3 trazas (obtenerTraza × 3)      │
│    - Maneja datos faltantes (relleno ceros)│
│    - Stream.write(format='MSEED')          │
└────────────────────────────────────────────┘
    ↓
┌────────────────────────────────────────────┐
│ 10. Reporte de tiempo de ejecución         │
│     - Tiempo total en consola              │
│     - Log de éxito/error                   │
└────────────────────────────────────────────┘
```

---

## Funciones Principales

### 1. main()

**Propósito**: Orquesta todo el proceso de conversión.

**Líneas**: 370-485

**Lógica**:
```python
def main():
    # 1. Parser de argumentos (simple y nombrado)
    parser = argparse.ArgumentParser()
    parser.add_argument("modo_simple", nargs="?", choices=["1", "2"])
    parser.add_argument("--modo", choices=["rc", "ee", "archivo"])
    parser.add_argument("--nombre", help="Nombre del archivo binario")

    # 2. Validación de entorno
    project_local_root = os.getenv("PROJECT_LOCAL_ROOT")
    if not project_local_root:
        print("Variable PROJECT_LOCAL_ROOT no definida")
        return

    # 3. Carga de configuración
    config_mseed = read_fileJSON(config_mseed_file)
    config_dispositivo = read_fileJSON(config_dispositivo_file)

    # 4. Determinación de archivo según modo
    if tipoArchivo == '1':  # Registro continuo
        binary_file = path_registro_continuo + binary_filename
    elif tipoArchivo == '2':  # Evento extraído
        binary_file = path_eventos_extraidos + binary_filename
    elif tipoArchivo == "archivo":  # Manual
        binary_file = os.path.join(project_local_root, "resultados",
                                     "registro-continuo", binary_filename)

    # 5-9. Procesamiento principal
    tiempo_binario = extraer_tiempo_binario(binary_file)
    datos_archivo_binario, segundos_faltantes = leer_archivo_binario(binary_file, logger)
    nombre_archivo_mseed = nombrar_archivo_mseed(codigo_estacion, tiempo_binario)
    conversion_mseed_digital(nombre_archivo_mseed, path_archivo_salida, ...)
```

**Notas**:
- Soporta 3 modos de invocación (simple, nombrado, manual)
- Código comentado de subida a Drive (líneas 474-482)
- Timer para medir rendimiento

---

### 2. leer_archivo_binario()

**Propósito**: Lectura eficiente y procesamiento del archivo binario completo.

**Líneas**: 125-210

**Parámetros**:
- `archivo_binario` (str): Ruta completa al archivo .dat
- `logger` (Logger): Instancia de logging

**Retorno**:
- `datos_np` (ndarray): Array de forma (3, n_muestras) con valores enteros de 20 bits
- `segundos_faltantes` (list o None): Lista de segundos sin datos

**Algoritmo**:

```python
def leer_archivo_binario(archivo_binario, logger):
    datos = [[], [], []]  # Almacenamiento temporal para X, Y, Z
    tiempos = []

    chunk_size = 2506 * 60  # ~150 KB por chunk (60 segundos)

    with open(archivo_binario, "rb") as f:
        while True:
            # 1. Lectura por bloques (eficiencia)
            chunk = np.fromfile(f, dtype=np.uint8, count=chunk_size)
            if chunk.size == 0:
                break  # EOF

            # 2. Cálculo de tramas completas
            num_tramas = len(chunk) // 2506
            if num_tramas == 0:
                continue  # Chunk incompleto al final

            # 3. Reshape a matriz de tramas
            chunk = chunk[:num_tramas * 2506].reshape((num_tramas, 2506))

            # 4. Extracción de timestamps (últimos 3 bytes)
            horas = chunk[:, 2503].astype(np.uint32)
            minutos = chunk[:, 2504].astype(np.uint32)
            segundos = chunk[:, 2505].astype(np.uint32)

            # 5. Validación de timestamps
            mascara_valida = (horas <= 23) & (minutos <= 59) & (segundos <= 59)
            tramas_invalidas = (~mascara_valida).sum()

            # 6. Filtrado de tramas válidas
            for h, m, s, valido in zip(horas, minutos, segundos, mascara_valida):
                if not valido:
                    logger.warning(f"Trama inválida: {h:02}:{m:02}:{s:02}")
                    continue
                tiempos.append(h * 3600 + m * 60 + s)

            # 7. Procesamiento vectorizado de datos
            chunk_valido = chunk[mascara_valida]
            datos_crudos = chunk_valido[:, :2500].reshape((-1, 250, 10))

            # 8. Conversión a valores de 20 bits por eje
            for j in range(3):  # X, Y, Z
                # Extracción de 3 bytes por muestra
                dato_1 = datos_crudos[:, :, j * 3 + 1].flatten()
                dato_2 = datos_crudos[:, :, j * 3 + 2].flatten()
                dato_3 = datos_crudos[:, :, j * 3 + 3].flatten()

                # Reconstrucción de valor de 20 bits
                xValue = ((dato_1.astype(np.uint32) << 12) & 0xFF000) + \
                         ((dato_2.astype(np.uint32) << 4) & 0xFF0) + \
                         ((dato_3.astype(np.uint32) >> 4) & 0xF)

                # Complemento a 2 (manejo de negativos)
                xValue = xValue.astype(np.int32)
                mask = xValue >= 0x80000  # Bit 19 = 1 (negativo)
                xValue[mask] = -1 * ((~xValue[mask] + 1) & 0x7FFFF)

                datos[j].extend(xValue)

    # 9. Conversión a NumPy array
    datos_np = np.array(datos)

    # 10. Detección de segundos faltantes
    tiempos_np = np.array(tiempos)
    dif_segundos = np.diff(tiempos_np)

    saltos_grandes = dif_segundos[dif_segundos > 1]
    if len(saltos_grandes) > 0:
        total_faltantes = sum(int(x - 1) for x in saltos_grandes)
        logger.warning(f"Segundos faltantes: {total_faltantes}")

    missing_indices = np.where(dif_segundos > 1)[0]
    segundos_faltantes = []
    for idx in missing_indices:
        segundos_faltantes.extend(range(tiempos_np[idx] + 1,
                                        tiempos_np[idx + 1]))

    return datos_np, segundos_faltantes if segundos_faltantes else None
```

**Optimizaciones**:
- **Lectura por bloques**: 60 tramas (150 KB) en lugar de byte a byte
- **Operaciones vectorizadas**: NumPy reemplaza loops de Python
- **Reshape eficiente**: Manipulación de memoria sin copias innecesarias

**Ejemplo de chunk**:
```
chunk shape: (60, 2506)  # 60 segundos × 2506 bytes
datos_crudos shape: (60, 250, 10)  # 60s × 250 muestras × 10 bytes
xValue shape después de flatten: (15000,)  # 60s × 250 muestras
```

---

### 3. extraer_tiempo_binario()

**Propósito**: Extraer el timestamp inicial del archivo para nombrado y metadata.

**Líneas**: 214-250

**Parámetros**:
- `archivo` (str): Ruta al archivo .dat

**Retorno**: Diccionario con componentes de fecha/hora

**Estructura de retorno**:
```python
tiempo_binario = {
    "anio": 2025,          # int
    "anio_s": "2025",      # str
    "mes": 11,             # int (1-12)
    "mes_s": "11",         # str (zero-padded)
    "dia": 25,             # int (1-31)
    "dia_s": "25",         # str
    "hora": 14,            # int (0-23)
    "hora_s": "14",        # str
    "minuto": 30,          # int (0-59)
    "minuto_s": "30",      # str
    "segundo": 45,         # int (0-59)
    "segundo_s": "45",     # str
    "n_segundo": 52245     # int (segundos desde medianoche)
}
```

**Extracción de bytes**:
```python
# Lectura de primera trama (2506 bytes)
tramaDatos = np.fromfile(f, np.int8, 2506)

# Posiciones de timestamp (bytes finales)
anio = int(tramaDatos[2500]) + 2000  # Byte 2500: año - 2000
mes = int(tramaDatos[2501])          # Byte 2501: mes (1-12)
dia = int(tramaDatos[2502])          # Byte 2502: día (1-31)
hora = int(tramaDatos[2503])         # Byte 2503: hora (0-23)
minuto = int(tramaDatos[2504])       # Byte 2504: minuto (0-59)
segundo = int(tramaDatos[2505])      # Byte 2505: segundo (0-59)
```

**Validación**: Verificación de tamaño mínimo de trama.

---

### 4. nombrar_archivo_mseed()

**Propósito**: Generar nombre estándar para archivo Mini-SEED.

**Líneas**: 254-262

**Parámetros**:
- `codigo_estacion` (str): Código de la estación (ej. "RSA01")
- `tiempo_binario` (dict): Diccionario de timestamp

**Formato de salida**:
```
{CODIGO}_{YYYYMMDD}_{HHMMSS}.mseed

Ejemplos:
- RSA01_20251125_143045.mseed
- SNLC_20210315_080000.mseed
```

**Implementación**:
```python
def nombrar_archivo_mseed(codigo_estacion, tiempo_binario):
    fecha_string = (tiempo_binario["anio_s"] +
                   tiempo_binario["mes_s"] +
                   tiempo_binario["dia_s"])
    hora_string = (tiempo_binario["hora_s"] +
                  tiempo_binario["minuto_s"] +
                  tiempo_binario["segundo_s"])

    fileName = f'{codigo_estacion}_{fecha_string}_{hora_string}.mseed'
    return fileName
```

---

### 5. conversion_mseed_digital()

**Propósito**: Crear el archivo Mini-SEED con 3 canales.

**Líneas**: 266-281

**Parámetros**:
- `fileName` (str): Nombre del archivo de salida
- `path` (str): Directorio de salida
- `tiempo_binario` (dict): Timestamp inicial
- `datos_archivo_binario` (ndarray): Array (3, n_muestras) con datos
- `segundos_faltantes` (list): Segundos sin datos
- `parametros_mseed` (dict): Configuración de metadata
- `logger` (Logger): Logger para registros

**Flujo**:
```python
def conversion_mseed_digital(fileName, path, tiempo_binario,
                             datos_archivo_binario, segundos_faltantes,
                             parametros_mseed, logger):
    nombre = parametros_mseed["SENSOR(2)"]

    # 1. Crear una traza por canal
    trazaCH1 = obtenerTraza(nombre, 1, datos_archivo_binario[0],
                           tiempo_binario, segundos_faltantes, parametros_mseed)
    trazaCH2 = obtenerTraza(nombre, 2, datos_archivo_binario[1],
                           tiempo_binario, segundos_faltantes, parametros_mseed)
    trazaCH3 = obtenerTraza(nombre, 3, datos_archivo_binario[2],
                           tiempo_binario, segundos_faltantes, parametros_mseed)

    # 2. Crear Stream de ObsPy
    stData = Stream(traces=[trazaCH1, trazaCH2, trazaCH3])

    # 3. Escribir archivo Mini-SEED
    fileNameCompleto = path + fileName
    stData.write(fileNameCompleto, format='MSEED', encoding='STEIM1', reclen=512)

    logger.info(f"Archivo {fileName} creado con éxito")
```

**Parámetros de escritura**:
- `format='MSEED'`: Formato Mini-SEED estándar
- `encoding='STEIM1'`: Compresión STEIM1 (típica para datos sísmicos)
- `reclen=512`: Longitud de registro de 512 bytes (estándar)

---

### 6. obtenerTraza()

**Propósito**: Crear objeto `Trace` de ObsPy con metadata completo para un canal.

**Líneas**: 285-344

**Parámetros**:
- `nombreCanal` (str): Tipo de sensor (no usado, se recalcula)
- `num_canal` (int): Número de canal (1=X, 2=Y, 3=Z)
- `data` (ndarray): Datos del canal (valores enteros de 20 bits)
- `tiempo_binario` (dict): Timestamp inicial
- `segundos_faltantes` (list): Segundos sin datos
- `parametros_mseed` (dict): Configuración

**Lógica de nomenclatura de canales**:

```python
# Prefijo según frecuencia de muestreo
if fsample > 80:
    nombreCanal = 'E'  # Extremely short period / High broadband
else:
    nombreCanal = 'S'  # Short period

# Tipo de sensor
if parametros_mseed["SENSOR(2)"] == 'SISMICO':
    nombreCanal += 'L'  # Low gain (sismómetro)
else:
    nombreCanal += 'N'  # Accelerometer (acelerómetro)

# Componente (X/Y/Z → Z/N/E)
num_canal_mod = num_canal - 3 * (int((num_canal - 1) / 3))
nombreCanal += parametros_mseed["CANAL(18)"][num_canal_mod - 1:num_canal_mod]
```

**Ejemplos de nombres de canal**:
- `ENZ`: Acelerómetro de alta frecuencia (>80 Hz), componente Z
- `ENN`: Acelerómetro de alta frecuencia, componente N (norte)
- `ENE`: Acelerómetro de alta frecuencia, componente E (este)
- `SNZ`: Acelerómetro de baja frecuencia (<80 Hz), componente Z

**Metadata del Trace**:
```python
stats = {
    'network': parametros_mseed["RED(19)"],              # Ej. "CM" (Red Sismológica)
    'station': parametros_mseed["CODIGO(1)"],            # Ej. "RSA01"
    'location': str(parametros_mseed["UBICACION(17)"]),  # Ej. "00"
    'channel': nombreCanal,                              # Ej. "ENZ"
    'npts': len(data),                                   # Número de muestras
    'sampling_rate': fsample,                            # Ej. 250 Hz
    'mseed': {'dataquality': calidad},                   # Ej. "D" (provisional)
    'starttime': UTCDateTime(anio, mes, dia, horas, minutos, segundos, 0)
}
```

**Manejo de datos faltantes**:
```python
if segundos_faltantes is not None:
    segundo_inicio = (horas * 3600) + (minutos * 60) + segundos
    muestras_por_segundo = fsample

    # Crear array completo con tamaño final
    npts_completo = len(data) + int(len(segundos_faltantes) * muestras_por_segundo)
    data_completo = np.zeros(npts_completo, dtype=np.int32)
    data_completo[:len(data)] = data

    # Insertar ceros en posiciones de datos faltantes
    for segundo_faltante in segundos_faltantes:
        tiempo_muestra_faltante = int(segundo_faltante - segundo_inicio)
        indice_muestra_faltante = tiempo_muestra_faltante * muestras_por_segundo
        lista_ceros = np.zeros(muestras_por_segundo, dtype=np.int32)
        data_completo = np.insert(data_completo, indice_muestra_faltante, lista_ceros)

    traza = Trace(data=data_completo, header=stats)
else:
    traza = Trace(data=data, header=stats)
```

**Importante**: Los datos se mantienen en valores enteros (cuentas del ADC), no se convierten a unidades físicas. La conversión la realiza el usuario final con la respuesta instrumental.

---

### 7. obtener_logger()

**Propósito**: Crear o recuperar instancia de logger por estación.

**Líneas**: 348-365

**Parámetros**:
- `id_estacion` (str): Identificador de la estación
- `log_directory` (str): Directorio de logs
- `log_filename` (str): Nombre del archivo de log (ej. "mseed.log")

**Implementación**:
```python
loggers = {}  # Variable global

def obtener_logger(id_estacion, log_directory, log_filename):
    global loggers
    if id_estacion not in loggers:
        logger = logging.getLogger(id_estacion)
        logger.setLevel(logging.DEBUG)

        log_path = os.path.join(log_directory, log_filename)
        file_handler = logging.FileHandler(log_path)
        file_handler.setLevel(logging.DEBUG)

        formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        )
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)

        loggers[id_estacion] = logger
    return loggers[id_estacion]
```

**Formato de log**:
```
2025-11-25 14:30:45,123 - RSA01 - INFO - Archivo RSA01_20251125_143000.dat leído con éxito
2025-11-25 14:30:45,234 - RSA01 - WARNING - Segundos faltantes: 12
2025-11-25 14:30:46,345 - RSA01 - INFO - Archivo RSA01_20251125_143000.mseed creado con éxito
```

---

### 8. read_fileJSON()

**Propósito**: Leer archivo JSON con manejo de errores.

**Líneas**: 21-31

**Implementación**:
```python
def read_fileJSON(nameFile):
    try:
        with open(nameFile, 'r') as f:
            data = json.load(f)
        return data
    except FileNotFoundError:
        print(f"Archivo {nameFile} no encontrado.")
        return None
    except json.JSONDecodeError:
        print(f"Error al decodificar el archivo {nameFile}.")
        return None
```

---

## Formato de Datos

### Estructura del Archivo Binario (.dat)

Cada trama representa **1 segundo** de datos:

```
Bytes 0-2505 (total: 2506 bytes)

┌──────────┬──────────────────────────────┬────────────────────┐
│  Byte 0  │       Bytes 1-2500           │   Bytes 2500-2505  │
├──────────┼──────────────────────────────┼────────────────────┤
│ ID fuente│  250 muestras × 10 bytes     │   Timestamp        │
│  reloj   │  (X, Y, Z aceleraciones)     │   (6 bytes)        │
│ (1 byte) │      (2500 bytes)            │                    │
└──────────┴──────────────────────────────┴────────────────────┘

ID fuente: 0=RPi, 1=GPS, 2=RTC, 3-5=Errores
```

### Estructura de una Muestra (10 bytes)

```
Bytes 0-9 de cada muestra:

┌────┬───────────────┬───────────────┬───────────────┐
│ ID │   EJE X       │   EJE Y       │   EJE Z       │
│    │  (3 bytes)    │  (3 bytes)    │  (3 bytes)    │
├────┼───┬───┬───────┼───┬───┬───────┼───┬───┬───────┤
│ B0 │B1 │B2 │ B3    │B4 │B5 │ B6    │B7 │B8 │ B9    │
└────┴───┴───┴───────┴───┴───┴───────┴───┴───┴───────┘
       X2  X1  X0      Y2  Y1  Y0      Z2  Z1  Z0
```

**Conversión a valor de 20 bits**:
```python
# Cada eje usa 3 bytes para 20 bits de resolución
dato_1 = tramaDatos[j * 3 + 1]  # Byte más significativo
dato_2 = tramaDatos[j * 3 + 2]  # Byte medio
dato_3 = tramaDatos[j * 3 + 3]  # Byte menos significativo

# Reconstrucción del valor de 20 bits
xValue = ((dato_1 << 12) & 0xFF000) +   # Bits 19-12
         ((dato_2 << 4) & 0xFF0) +      # Bits 11-4
         ((dato_3 >> 4) & 0xF)          # Bits 3-0

# Complemento a 2 si es negativo (bit 19 = 1)
if xValue >= 0x80000:
    xValue = xValue & 0x7FFFF
    xValue = -1 * ((~xValue + 1) & 0x7FFFF)
```

### Timestamp (últimos 6 bytes)

```
┌─────────┬─────────┬─────────┬─────────┬─────────┬─────────┐
│ Byte    │ 2500    │ 2501    │ 2502    │ 2503    │ 2504    │ 2505    │
├─────────┼─────────┼─────────┼─────────┼─────────┼─────────┼─────────┤
│ Campo   │ Año-2000│  Mes    │  Día    │  Hora   │ Minuto  │ Segundo │
├─────────┼─────────┼─────────┼─────────┼─────────┼─────────┼─────────┤
│ Rango   │ 0-99    │ 1-12    │ 1-31    │ 0-23    │ 0-59    │ 0-59    │
├─────────┼─────────┼─────────┼─────────┼─────────┼─────────┼─────────┤
│ Ejemplo │ 25      │ 11      │ 25      │ 14      │ 30      │ 45      │
│         │ (2025)  │ (Nov)   │         │         │         │         │
└─────────┴─────────┴─────────┴─────────┴─────────┴─────────┴─────────┘
```

### Formato Mini-SEED de Salida

**Estructura general**:
```
Archivo .mseed
│
├─ Trace 1: Canal ENZ (eje Z)
│   ├─ Header: Metadata (red, estación, canal, etc.)
│   ├─ Blockettes: Información adicional
│   └─ Data records: Datos comprimidos (STEIM1)
│
├─ Trace 2: Canal ENN (eje N/Y)
│   └─ (misma estructura)
│
└─ Trace 3: Canal ENE (eje E/X)
    └─ (misma estructura)
```

**Ejemplo de metadata**:
```
Network: CM
Station: RSA01
Location: 00
Channels: 3
  - ENZ: vertical (Z)
  - ENN: norte-sur (Y/N)
  - ENE: este-oeste (X/E)
Sampling rate: 250.0 Hz
Start time: 2025-11-25T14:30:45.000000Z
Number of samples: 900000 (1 hora)
Data quality: D (provisional)
Encoding: STEIM1
Record length: 512 bytes
```

---

## Configuración

### 1. configuracion_mseed.json

**Ubicación**: `$PROJECT_LOCAL_ROOT/configuracion/configuracion_mseed.json`

**Campos utilizados**:
```json
{
  "CODIGO(1)": "RSA01",
  "SENSOR(2)": "SISMICO",
  "RED(19)": "CM",
  "CALIDAD(16)": "D",
  "UBICACION(17)": "00",
  "CANAL(18)": "ZNE",
  "MUESTREO(20)": "250"
}
```

**Descripción de campos**:
- `CODIGO(1)`: Código de estación (4-5 caracteres)
- `SENSOR(2)`: Tipo de sensor ("SISMICO" o "ACELEROGRAFO")
- `RED(19)`: Código de red sismológica (ej. "CM" = Red Sismológica de Colombia)
- `CALIDAD(16)`: Calidad de datos ("D"=provisional, "R"=raw, "Q"=QC, "M"=merged)
- `UBICACION(17)`: Código de ubicación ("00", "01", etc.)
- `CANAL(18)`: Orden de componentes ("ZNE" estándar sismológico)
- `MUESTREO(20)`: Frecuencia de muestreo en Hz (string)

### 2. configuracion_dispositivo.json

**Ubicación**: `$PROJECT_LOCAL_ROOT/configuracion/configuracion_dispositivo.json`

**Campos utilizados**:
```json
{
  "dispositivo": {
    "id": "RSA01"
  },
  "directorios": {
    "registro_continuo": "/home/rsa/resultados/registro-continuo/",
    "eventos_extraidos": "/home/rsa/resultados/eventos-extraidos/",
    "archivos_mseed": "/home/rsa/resultados/mseed/"
  }
}
```

### 3. Archivos Temporales

#### NombreArchivoRegistroContinuo.tmp

**Ubicación**: `$PROJECT_LOCAL_ROOT/tmp-files/NombreArchivoRegistroContinuo.tmp`

**Formato**:
```
RSA01_20251125_143000.dat
RSA01_20251125_143000.dat
```
Línea 2: Archivo anterior (para conversión)

#### NombreArchivoEventoExtraido.tmp

**Ubicación**: `$PROJECT_LOCAL_ROOT/tmp-files/NombreArchivoEventoExtraido.tmp`

**Formato**:
```
RSA01_251125-143045_030.dat
```
Línea 1: Nombre del evento extraído

---

## Modo de Uso

### Invocación desde Línea de Comandos

#### Sintaxis Simple (legado)
```bash
# Convertir registro continuo
python3 binary_to_mseed.py 1

# Convertir evento extraído
python3 binary_to_mseed.py 2
```

#### Sintaxis Nombrada (recomendada)
```bash
# Convertir registro continuo
python3 binary_to_mseed.py --modo rc

# Convertir evento extraído
python3 binary_to_mseed.py --modo ee

# Convertir archivo manual
python3 binary_to_mseed.py --modo archivo --nombre RSA01_20251125_143000.dat
```

### Integración con Sistema de Adquisición

#### 1. Conversión Automática Horaria

**Script de gestión** (ej. `gestor_archivos_acq.py`):
```python
# Después de que registro_continuo cierra archivo horario
subprocess.run([
    "python3",
    "/path/to/binary_to_mseed.py",
    "--modo", "rc"
])
```

#### 2. Conversión Post-Evento

**Después de extracción de evento**:
```bash
# extraer_evento_binario_2.1.1.c escribe .tmp
# Luego llamar:
python3 binary_to_mseed.py --modo ee
```

#### 3. Conversión en Batch

**Script para procesar múltiples archivos**:
```bash
#!/bin/bash
for archivo in /path/to/registro-continuo/*.dat; do
    nombre=$(basename "$archivo")
    python3 binary_to_mseed.py --modo archivo --nombre "$nombre"
done
```

### Ejemplo de Uso Manual

```bash
# 1. Configurar entorno
export PROJECT_LOCAL_ROOT=/home/rsa

# 2. Verificar configuración
cat $PROJECT_LOCAL_ROOT/configuracion/configuracion_mseed.json

# 3. Convertir archivo específico
cd $PROJECT_LOCAL_ROOT/scripts/operation/mseed
python3 binary_to_mseed.py --modo archivo --nombre RSA01_20251125_140000.dat

# 4. Verificar resultado
ls -lh $PROJECT_LOCAL_ROOT/resultados/mseed/
# RSA01_20251125_140000.mseed

# 5. Revisar log
tail -f $PROJECT_LOCAL_ROOT/log-files/mseed.log
```

### Análisis con ObsPy

**Lectura del archivo generado**:
```python
from obspy import read

# Leer archivo Mini-SEED
st = read("RSA01_20251125_140000.mseed")

# Información básica
print(st)
# 3 Trace(s) in Stream:
# CM.RSA01.00.ENZ | 2025-11-25T14:00:00.000000Z - ... | 250.0 Hz, 900000 samples
# CM.RSA01.00.ENN | 2025-11-25T14:00:00.000000Z - ... | 250.0 Hz, 900000 samples
# CM.RSA01.00.ENE | 2025-11-25T14:00:00.000000Z - ... | 250.0 Hz, 900000 samples

# Plot
st.plot()

# Filtrado
st.filter('highpass', freq=1.0)
st.filter('lowpass', freq=25.0)

# Espectrograma
st[0].spectrogram()
```

---

## Logging y Diagnóstico

### Sistema de Logging

**Archivo de log**: `$PROJECT_LOCAL_ROOT/log-files/mseed.log`

**Niveles de log utilizados**:
- `INFO`: Operaciones exitosas
- `WARNING`: Problemas no críticos (datos faltantes, tramas inválidas)
- `ERROR`: Errores críticos (archivos dañados)

### Mensajes Típicos

#### Conversión Exitosa
```
2025-11-25 14:30:45,123 - RSA01 - INFO - Convirtiendo el archivo binario: RSA01_20251125_140000.dat
2025-11-25 14:30:45,234 - RSA01 - INFO - Archivo RSA01_20251125_140000.dat leído con éxito
2025-11-25 14:30:45,345 - RSA01 - INFO - Tiempo primera muestra: 14:00:00. Tiempo última muestra: 14:59:59
2025-11-25 14:30:46,456 - RSA01 - INFO - Archivo RSA01_20251125_140000.mseed creado con éxito
```

#### Datos Faltantes
```
2025-11-25 14:30:45,234 - RSA01 - WARNING - Segundos faltantes: 12. Saltos mayores a 1 segundo: 3. Top 5: [2, 5, 5]
```
**Interpretación**: 3 saltos detectados, total de 12 segundos sin datos.

#### Tramas Inválidas
```
2025-11-25 14:30:45,123 - RSA01 - WARNING - Trama con tiempo inválido detectado: 25:00:00
2025-11-25 14:30:45,234 - RSA01 - WARNING - Se descartaron 5 tramas con tiempo inválido para mantener la alineación de datos.
```

#### Error Crítico
```
2025-11-25 14:30:45,123 - RSA01 - ERROR - Tamaño de trama insuficiente. Archivo binario podría estar dañado o incompleto
```

### Salida en Consola

**Durante conversión normal**:
```
Convirtiendo el archivo: RSA01_20251125_140000.dat
Primer elemento de tiempos_np: 50400
Último elemento de tiempos_np: 53999
Tiempo primer elemento: 14:00:00
Tiempo último elemento: 14:59:59
Tiempo de ejecución de leer_archivo_binario: 2.3456 segundos
RSA01_20251125_140000.mseed
Se ha creado el archivo: /home/rsa/resultados/mseed/RSA01_20251125_140000.mseed
Tiempo total de ejecución: 2.5678 segundos
```

**Interpretación de tiempos**:
- `tiempos_np`: Segundos desde medianoche (50400 = 14:00:00)
- `Tiempo primer elemento`: Formato legible HH:MM:SS
- Tiempos de ejecución típicos:
  - 1 hora (900,000 muestras): ~2-3 segundos
  - Evento corto (60s): ~0.2 segundos

---

## Consideraciones Importantes

### Rendimiento

1. **Procesamiento vectorizado con NumPy**:
   - 60 veces más rápido que loops de Python
   - Conversión de 1 hora: ~2-3 segundos en Raspberry Pi 4

2. **Lectura por bloques**:
   - Chunk de 60 segundos (150 KB) reduce llamadas al sistema
   - Uso eficiente de cache de CPU

3. **Memoria**:
   - Archivo de 1 hora: ~9 MB (binario) → ~27 MB en memoria (3 arrays float64)
   - Pico de memoria: ~50 MB para 1 hora de datos

### Integridad de Datos

1. **Validación de timestamps**:
   - Descarte de tramas con timestamp inválido
   - Detección de saltos temporales

2. **Datos faltantes**:
   - Rellenado con ceros (no interpolación)
   - Preserva continuidad temporal en Mini-SEED
   - Permite identificar gaps en análisis posterior

3. **Valores extremos**:
   - Rango válido: ±2^19 cuentas (±262,144)
   - Sin filtrado de outliers (se preservan todos los datos)

### Compatibilidad

1. **ObsPy**:
   - Compatible con ObsPy >= 1.2.0
   - Todas las funciones estándar soportadas

2. **Mini-SEED estándar**:
   - FDSN compliance
   - Importable en SAC, SeisComP, Earthworm, etc.

3. **STEIM1**:
   - Compresión sin pérdida
   - Típicamente 50-70% de reducción de tamaño

---

## Problemas Identificados

### 1. Función Duplicada leer_archivo_binario_0()

**Líneas**: 34-123

**Problema**: Existe una versión anterior de `leer_archivo_binario()` sin usar (sufijo `_0`).

**Diferencias con versión actual**:
- No valida tramas inválidas antes del procesamiento
- Menos robusto ante datos corruptos

**Recomendación**: Eliminar función obsoleta para reducir confusión.

### 2. Conversión a Unidades Físicas No Realizada

**Problema**: Los datos se escriben en cuentas del ADC, no en unidades físicas (cm/s², gales).

**Impacto**:
- Usuario debe aplicar calibración manualmente
- Requiere conocer el factor de conversión del ADXL355

**Conversión correcta** (no implementada):
```python
# Factor del ADXL355 (rango ±8g)
factor = 9.8 / (2 ** 18)  # gales por cuenta

# Convertir a gales
data_gales = data_cuentas * factor
```

**Recomendación**: Considerar agregar opción para escribir datos calibrados.

### 3. Manejo de Cambio de Fecha No Implementado

**Problema**: Si un archivo cruza medianoche (23:59:59 → 00:00:00), la detección de segundos faltantes falla.

**Ejemplo de fallo**:
```
tiempos_np = [86399, 0, 1, 2, ...]  # Medianoche
dif_segundos = [-86399, 1, 1, ...]  # Salto negativo enorme
```

**Impacto**: Falso reporte de ~24 horas de datos faltantes.

**Solución sugerida**:
```python
# Detectar cambio de día
cambios_dia = np.where(dif_segundos < 0)[0]
for idx in cambios_dia:
    dif_segundos[idx] = (86400 - tiempos_np[idx]) + tiempos_np[idx + 1]
```

### 4. Código de Subida a Drive Comentado

**Líneas**: 475-482

**Problema**: Funcionalidad de subida automática a Google Drive está deshabilitada.

**Impacto**: Requiere subida manual de archivos.

**Recomendación**:
- Rehabilitar o eliminar código muerto
- Considerar configuración opcional vía JSON

### 5. No Hay Validación de Espacio en Disco

**Problema**: No verifica espacio disponible antes de escribir archivo.

**Impacto**: Posible fallo en escritura parcial si disco lleno.

**Solución sugerida**:
```python
import shutil

# Verificar espacio disponible
stat = shutil.disk_usage(path_archivo_salida)
espacio_requerido = len(datos_np[0]) * 3 * 4  # 4 bytes por muestra × 3 canales
if stat.free < espacio_requerido * 1.5:  # Margen de seguridad
    logger.error(f"Espacio insuficiente en disco: {stat.free / 1e9:.2f} GB disponibles")
    return
```

### 6. Inserción Ineficiente de Datos Faltantes

**Líneas**: 335-338 en `obtenerTraza()`

**Problema**:
```python
for segundo_faltante in segundos_faltantes:
    # ...
    data_completo = np.insert(data_completo, indice_muestra_faltante, lista_ceros)
```

**Impacto**: `np.insert()` en loop es O(n²) debido a copias repetidas del array.

**Solución O(n)**:
```python
# Crear array final una sola vez
indices_faltantes = [int(s - segundo_inicio) * muestras_por_segundo
                     for s in segundos_faltantes]
indices_faltantes_sorted = sorted(indices_faltantes)

# Split y concatenación eficiente
segmentos = []
prev_idx = 0
for idx in indices_faltantes_sorted:
    segmentos.append(data[prev_idx:idx])
    segmentos.append(lista_ceros)
    prev_idx = idx
segmentos.append(data[prev_idx:])

data_completo = np.concatenate(segmentos)
```

### 7. No Hay Backup de Archivos Binarios Originales

**Problema**: Después de conversión, no hay copia de seguridad del .dat original.

**Riesgo**: Pérdida de datos si el .mseed tiene errores y el .dat se elimina.

**Recomendación**: Crear backup antes de conversión o después de verificación.

---

## Mejoras Potenciales

### 1. Procesamiento Paralelo

**Propuesta**: Procesar los 3 canales en paralelo con `multiprocessing`.

```python
from multiprocessing import Pool

def procesar_canal(args):
    canal_idx, data, tiempo_binario, segundos_faltantes, parametros = args
    return obtenerTraza(parametros["SENSOR(2)"], canal_idx + 1, data,
                       tiempo_binario, segundos_faltantes, parametros)

with Pool(3) as p:
    trazas = p.map(procesar_canal, [
        (0, datos[0], tiempo_binario, segundos_faltantes, parametros_mseed),
        (1, datos[1], tiempo_binario, segundos_faltantes, parametros_mseed),
        (2, datos[2], tiempo_binario, segundos_faltantes, parametros_mseed)
    ])
```

**Ventaja**: Reducción de ~30% en tiempo de procesamiento para archivos grandes.

### 2. Verificación Post-Conversión

**Propuesta**: Validar archivo Mini-SEED después de creación.

```python
def verificar_mseed(filename):
    try:
        st = read(filename)
        if len(st) != 3:
            return False, "Número incorrecto de canales"
        if st[0].stats.npts == 0:
            return False, "Sin muestras en canal 1"
        return True, "OK"
    except Exception as e:
        return False, str(e)

# Después de stData.write(...)
valido, mensaje = verificar_mseed(fileNameCompleto)
if not valido:
    logger.error(f"Archivo Mini-SEED inválido: {mensaje}")
```

### 3. Modo de Conversión a Unidades Físicas

**Propuesta**: Opción para escribir datos calibrados.

```python
# En configuracion_mseed.json
{
  "CONVERSION_FISICA": true,
  "FACTOR_CONVERSION": 3.73e-8  # 9.8 / 2^18
}

# En conversion_mseed_digital()
if parametros_mseed.get("CONVERSION_FISICA", False):
    factor = float(parametros_mseed["FACTOR_CONVERSION"])
    datos_archivo_binario = datos_archivo_binario * factor
```

### 4. Compresión STEIM2

**Propuesta**: Opción para usar STEIM2 (mayor compresión).

```python
# Configuración
stData.write(fileNameCompleto, format='MSEED',
            encoding='STEIM2',  # Mayor compresión
            reclen=512)
```

**Ventaja**: ~20-30% más compresión que STEIM1.

### 5. Metadatos Extendidos

**Propuesta**: Agregar respuesta instrumental al Mini-SEED.

```python
from obspy.core.inventory import Inventory, Network, Station, Channel
from obspy.core.inventory.response import Response

# Crear respuesta del ADXL355
response = Response()
# ... definir polos, ceros, ganancia ...

# Agregar a metadata del Stream
st[0].stats.response = response
```

**Ventaja**: Archivo auto-contenido con información de calibración.

### 6. Modo de Streaming

**Propuesta**: Conversión en tiempo real de named pipe.

```python
def convertir_streaming(pipe_path):
    with open(pipe_path, 'rb') as pipe:
        while True:
            chunk = pipe.read(2506)
            if len(chunk) < 2506:
                break
            # Procesamiento incremental
```

**Ventaja**: Conversión en tiempo real para monitoreo remoto.

---

## Resumen de Archivos Relacionados

### Scripts de Adquisición (C)
- [registro_continuo_4.5.0.c](../../../scripts/operation/acelerografo/registro_continuo_4.5.0.c): Genera archivos .dat
- [extraer_evento_binario_2.1.1.c](../../../scripts/operation/acelerografo/extraer_evento_binario_2.1.1.c): Extrae eventos

### Scripts de Conversión (Python)
- [binary_to_mseed.py](../../../scripts/operation/mseed/binary_to_mseed.py): Este script

### Configuración
- `configuracion_mseed.json`: Metadata de estación
- `configuracion_dispositivo.json`: Rutas y configuración

### Archivos Temporales
- `NombreArchivoRegistroContinuo.tmp`: Nombre de RC actual
- `NombreArchivoEventoExtraido.tmp`: Nombre de evento extraído

### Logs
- `mseed.log`: Registro de conversiones

---

## Documentos Relacionados

Para entender el contexto completo del sistema:

1. [firmware_context.md](firmware_context.md): Firmware del dsPIC y adquisición de hardware
2. [registro_continuo_context.md](registro_continuo_context.md): Adquisición en Raspberry Pi
3. [extraer_evento_context.md](extraer_evento_context.md): Extracción de eventos
4. [CLAUDE.md](../../../CLAUDE.md): Visión general del proyecto

---

**Última actualización**: 2025-11-25

**Estado**: Documentación completa de binary_to_mseed.py v488 (488 líneas)

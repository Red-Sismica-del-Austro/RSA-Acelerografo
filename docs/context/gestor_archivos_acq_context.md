# Contexto del Script gestor_archivos_acq.py

**Archivo**: [scripts/operation/drive/gestor_archivos_acq.py](../../../scripts/operation/drive/gestor_archivos_acq.py)

**Propósito**: Gestionar el ciclo de vida de archivos de adquisición (binarios y Mini-SEED), controlando espacio en disco y subida a Google Drive según el modo de operación.

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
6. [Modos de Operación](#modos-de-operación)
7. [Configuración](#configuración)
8. [Logging y Diagnóstico](#logging-y-diagnóstico)
9. [Gestión de Espacio en Disco](#gestión-de-espacio-en-disco)
10. [Integración con Google Drive](#integración-con-google-drive)
11. [Modo de Uso](#modo-de-uso)
12. [Consideraciones Importantes](#consideraciones-importantes)
13. [Problemas Identificados](#problemas-identificados)
14. [Mejoras Potenciales](#mejoras-potenciales)

---

## Arquitectura del Sistema

### Posición en el Flujo de Datos

```
┌─────────────────────────────────────────────────────────────────┐
│                    SISTEMA COMPLETO                             │
│                                                                 │
│  1. ADQUISICIÓN                                                 │
│     registro_continuo_4.5.0.c                                   │
│           ↓                                                     │
│     Archivos .dat (binarios)                                    │
│           ↓                                                     │
│  2. CONVERSIÓN                                                  │
│     binary_to_mseed.py                                          │
│           ↓                                                     │
│     Archivos .mseed                                             │
│           ↓                                                     │
│  ┌─────────────────────────────────────────┐                    │
│  │  gestor_archivos_acq.py                 │◄─── Este programa  │
│  │  (este programa)                        │                    │
│  │                                         │                    │
│  │  Modo OFFLINE:                          │                    │
│  │  • Borra archivos .dat antiguos         │                    │
│  │  • Mantiene solo el más reciente        │                    │
│  │  • Controla espacio .mseed (<10%)       │                    │
│  │  • Borra .mseed más antiguo si necesario│                    │
│  │                                         │                    │
│  │  Modo ONLINE:                           │                    │
│  │  • Verifica conexión a internet         │                    │
│  │  • Sube archivos .mseed a Drive         │                    │
│  │  • Controla espacio en ambos directorios│                    │
│  │  • Borra archivos más antiguos          │                    │
│  └─────────────────┬───────────────────────┘                    │
│                    │                                            │
│                    ├─────────────────┐                          │
│                    │                 │                          │
│                    ↓                 ↓                          │
│            (modo offline)     (modo online)                     │
│                    │                 │                          │
│                    ↓                 ↓                          │
│         Almacenamiento local   Google Drive                     │
│         (gestión de espacio)   (respaldo en nube)               │
└─────────────────────────────────────────────────────────────────┘
```

### Rol en el Sistema

El gestor de archivos actúa como **orquestador de almacenamiento**:

1. **Supervisor de recursos**: Monitorea espacio en disco disponible
2. **Limpiador automático**: Elimina archivos antiguos según política FIFO
3. **Conector con nube**: Integra con Google Drive en modo online
4. **Registrador de eventos**: Mantiene log detallado de operaciones

---

## Propósito y Casos de Uso

### Propósito Principal

Gestionar el almacenamiento de archivos de adquisición sismológica, optimizando el uso de disco y permitiendo operación continua en dos modos:

1. **Offline**: Estación aislada sin conexión a internet
2. **Online**: Estación conectada con respaldo en nube

### Casos de Uso

#### 1. Estación en Modo Offline

**Contexto**: Estación remota sin conectividad, almacenamiento limitado (ej. SD card de 32 GB).

**Escenario**:
```
- Archivos .dat: 9 MB/hora × 24 horas = 216 MB/día
- Archivos .mseed: 3 MB/hora × 24 horas = 72 MB/día
- Capacidad SD: 32 GB
- Duración sin limpieza: ~45 días
```

**Acción del gestor**:
1. Borra todos los archivos .dat excepto el más reciente (en uso por registro_continuo)
2. Si espacio libre < 10%: borra archivos .mseed más antiguos
3. Permite operación continua indefinida

**Invocación**:
```bash
# Ejecutado cada hora por cron
0 * * * * python3 /path/to/gestor_archivos_acq.py
```

#### 2. Estación en Modo Online

**Contexto**: Estación con conectividad WiFi/Ethernet estable.

**Flujo**:
1. Verifica conexión a internet (8.8.8.8:53)
2. Sube archivos .mseed a Google Drive
3. Controla espacio en disco para ambos tipos de archivos
4. Si conexión falla: mantiene archivos localmente y controla espacio

**Ventajas**:
- Respaldo automático en nube
- Recuperación ante falla de hardware
- Acceso remoto a datos

**Invocación**:
```bash
# Ejecutado cada hora por cron
0 * * * * python3 /path/to/gestor_archivos_acq.py
```

#### 3. Recuperación de Espacio Crítico

**Escenario**: Espacio en disco < 10% (umbral configurable).

**Ejemplo de log**:
```
2025-11-25 14:00:00 - RSA01 - WARNING - Espacio disponible es menor al 10%.
2025-11-25 14:00:00 - RSA01 - INFO - Se borró el archivo más antiguo: RSA01_20251115_140000.mseed
2025-11-25 14:00:01 - RSA01 - INFO - Espacio libre: 12.34%
```

#### 4. Transición Offline → Online

**Escenario**: Estación sin conexión recupera conectividad.

**Comportamiento**:
1. Próxima ejecución detecta conexión
2. Sube todos los archivos .mseed acumulados
3. Libera espacio en disco local

---

## Dependencias y Librerías

### Librerías Estándar de Python

```python
import os           # Operaciones de sistema de archivos
import subprocess   # Llamadas a scripts externos (subir_archivo.py)
import shutil       # Cálculo de espacio en disco
import socket       # Verificación de conexión a internet
import json         # Lectura de configuración
import logging      # Sistema de logging
```

### Dependencias Externas

1. **Script de subida a Drive**: [subir_archivo.py](../../../scripts/operation/drive/subir_archivo.py)
   - Requiere credenciales de Google Drive API
   - Debe estar configurado previamente

2. **Archivos de configuración**:
   - `configuracion_dispositivo.json`

3. **Variable de entorno**: `PROJECT_LOCAL_ROOT`

---

## Flujo de Ejecución Principal

### Diagrama de Flujo

```
main()
    ↓
┌──────────────────────────────────────────┐
│ 1. Validación de entorno                 │
│    - PROJECT_LOCAL_ROOT definida         │
│    - Directorios existen                 │
└──────────────────────────────────────────┘
    ↓
┌──────────────────────────────────────────┐
│ 2. Carga de configuración                │
│    - read_fileJSON(config_dispositivo)   │
│    - Extrae modo_adquisicion             │
│    - Extrae id_estacion                  │
│    - Extrae umbral_espacio_minimo        │
└──────────────────────────────────────────┘
    ↓
┌──────────────────────────────────────────┐
│ 3. Inicialización de logger              │
│    - obtener_logger(id_estacion)         │
│    - Log en gestor_acq.log               │
└──────────────────────────────────────────┘
    ↓
┌──────────────────────────────────────────┐
│ 4. Escaneo de archivos                   │
│    - Lista archivos .mseed               │
│    - Lista archivos .dat                 │
│    - Registra conteo en log              │
└──────────────────────────────────────────┘
    ↓
┌──────────────────────────────────────────┐
│ 5. Decisión según modo                   │
│    ├─ offline → Flujo A                  │
│    └─ online  → Flujo B                  │
└──────────────────────────────────────────┘
    ↓
┌──────────────────────────────────────────┐
│ FLUJO A (OFFLINE):                       │
│                                          │
│ 5.1. Identificar .dat más reciente       │
│      - max(files, key=os.path.getmtime)  │
│                                          │
│ 5.2. Borrar todos los .dat antiguos      │
│      - Excepto el más reciente           │
│                                          │
│ 5.3. Verificar espacio en /mseed         │
│      - get_free_space_percentage()       │
│                                          │
│ 5.4. Si espacio < umbral:                │
│      - delete_oldest_file(.mseed)        │
└──────────────────────────────────────────┘

┌──────────────────────────────────────────┐
│ FLUJO B (ONLINE):                        │
│                                          │
│ 5.1. Verificar conexión a internet       │
│      - check_internet_connection()       │
│                                          │
│ 5.2. Si hay conexión:                    │
│      ├─ Subir cada archivo .mseed        │
│      │   - subprocess.run(subir_archivo) │
│      │   - Log de éxito/error            │
│      └─ Verificar espacio en /binarios   │
│          - Si < umbral: borrar más viejo │
│                                          │
│ 5.3. Si NO hay conexión:                 │
│      ├─ Verificar espacio en /mseed      │
│      │   - Si < umbral: borrar más viejo │
│      └─ Verificar espacio en /binarios   │
│          - Si < umbral: borrar más viejo │
└──────────────────────────────────────────┘
```

---

## Funciones Principales

### 1. main()

**Propósito**: Orquesta el flujo completo de gestión de archivos.

**Líneas**: 91-215

**Lógica resumida**:
```python
def main():
    # 1. Validación de entorno
    project_local_root = os.getenv("PROJECT_LOCAL_ROOT")
    if not project_local_root:
        logging.error("Variable PROJECT_LOCAL_ROOT no definida")
        return

    # 2. Definición de rutas
    script_subir_archivo_drive = os.path.join(project_local_root, "scripts", "drive", "subir_archivo.py")
    mseed_directory = os.path.join(project_local_root, "resultados", "mseed")
    binary_directory = os.path.join(project_local_root, "resultados", "registro-continuo")
    config_dispositivo_path = os.path.join(project_local_root, "configuracion", "configuracion_dispositivo.json")

    # 3. Verificación de existencia de directorios
    if not os.path.isdir(mseed_directory):
        logging.error(f"Directorio mseed no existe: {mseed_directory}")
        return

    # 4. Carga de configuración
    config_dispositivo = read_fileJSON(config_dispositivo_path)
    mode_acq = config_dispositivo.get("dispositivo", {}).get("modo_adquisicion", "Unknown")
    id_estacion = config_dispositivo.get("dispositivo", {}).get("id", "Unknown")
    min_free_space_threshold = config_dispositivo.get("dispositivo", {}).get("umbral_espacio_minimo", 10)

    # 5. Inicialización de logger
    logger = obtener_logger(id_estacion, log_directory, "gestor_acq.log")

    # 6. Escaneo de archivos
    archivos_mseed = [f for f in os.listdir(mseed_directory) if f.endswith(".mseed")]
    archivos_binarios = [f for f in os.listdir(binary_directory) if f.endswith(".dat")]
    logger.info(f"Encontrados {len(archivos_mseed)} mseed y {len(archivos_binarios)} binarios.")

    # 7. Decisión según modo
    if mode_acq == "offline":
        # FLUJO OFFLINE (ver sección Modos de Operación)
        ...
    elif mode_acq == "online":
        # FLUJO ONLINE (ver sección Modos de Operación)
        ...
    else:
        logger.error(f"Modo desconocido: {mode_acq}")
```

---

### 2. read_fileJSON()

**Propósito**: Leer archivo JSON con manejo robusto de errores.

**Líneas**: 17-28

**Parámetros**:
- `nameFile` (str): Ruta al archivo JSON

**Retorno**: Diccionario con datos o `None` en caso de error

**Implementación**:
```python
def read_fileJSON(nameFile):
    try:
        with open(nameFile, 'r') as f:
            data = json.load(f)
        logging.info(f"Archivo {nameFile} leído correctamente.")
        return data
    except FileNotFoundError:
        logging.error(f"Archivo {nameFile} no encontrado.")
        return None
    except json.JSONDecodeError:
        logging.error(f"Error al decodificar {nameFile}.")
        return None
```

**Ventajas**:
- Manejo explícito de errores comunes
- Logging para diagnóstico
- Retorno consistente (`None` indica fallo)

---

### 3. get_free_space_percentage()

**Propósito**: Calcular porcentaje de espacio libre en una partición.

**Líneas**: 31-34

**Parámetros**:
- `path` (str): Ruta a cualquier archivo/directorio en la partición

**Retorno**: Float con porcentaje de espacio libre (0-100)

**Implementación**:
```python
def get_free_space_percentage(path):
    total, used, free = shutil.disk_usage(path)
    percentage = (free / total) * 100
    return percentage
```

**Ejemplo de uso**:
```python
free_space = get_free_space_percentage("/home/rsa/resultados/mseed")
# Retorno: 15.67 (significa 15.67% libre)

if free_space < 10:
    print("¡Espacio crítico!")
```

**Importante**: `shutil.disk_usage()` retorna información de la **partición completa**, no solo del directorio específico.

---

### 4. check_internet_connection()

**Propósito**: Verificar conectividad a internet de forma rápida y confiable.

**Líneas**: 37-47

**Parámetros**:
- `logger` (Logger): Instancia para logging
- `host` (str): IP del servidor a probar (default: "8.8.8.8" - DNS Google)
- `port` (int): Puerto a conectar (default: 53 - DNS)
- `timeout` (int): Timeout en segundos (default: 3)

**Retorno**: Boolean (`True` si hay conexión, `False` si no)

**Implementación**:
```python
def check_internet_connection(logger, host="8.8.8.8", port=53, timeout=3):
    try:
        socket.setdefaulttimeout(timeout)
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.connect((host, port))
        sock.close()
        logger.info("Conexión a internet verificada.")
        return True
    except Exception as e:
        logger.warning(f"Fallo en conexión: {e}")
        return False
```

**Estrategia de verificación**:
1. Intenta conexión TCP a 8.8.8.8:53 (DNS de Google)
2. Timeout de 3 segundos (evita bloqueos largos)
3. Cierra conexión inmediatamente (no envía datos)

**Ventajas**:
- Más rápido que ping
- No requiere permisos especiales (como ICMP)
- Funciona detrás de firewalls que bloquean ICMP

**Alternativas consideradas**:
```python
# Opción 1: HTTP request (más lento, más robusto)
import urllib.request
urllib.request.urlopen('http://www.google.com', timeout=3)

# Opción 2: DNS lookup (requiere resolver configurado)
import socket
socket.gethostbyname('www.google.com')

# Opción elegida: TCP socket (rápido, simple, confiable)
```

---

### 5. delete_oldest_file()

**Propósito**: Borrar el archivo más antiguo con extensión específica en un directorio.

**Líneas**: 50-61

**Parámetros**:
- `directory` (str): Directorio donde buscar
- `extension` (str): Extensión de archivos a considerar (ej. ".mseed", ".dat")
- `logger` (Logger): Instancia para logging

**Implementación**:
```python
def delete_oldest_file(directory, extension, logger):
    # 1. Listar archivos con extensión específica
    files = [os.path.join(directory, f)
             for f in os.listdir(directory)
             if f.endswith(extension)]

    # 2. Verificar que hay archivos
    if not files:
        logger.warning(f"No hay archivos {extension} en {directory}.")
        return

    # 3. Encontrar el más antiguo por timestamp de modificación
    oldest_file = min(files, key=os.path.getmtime)
    filename = os.path.basename(oldest_file)

    # 4. Intentar borrar
    try:
        os.remove(oldest_file)
        logger.info(f"Borrado archivo más antiguo: {filename}")
    except Exception as e:
        logger.error(f"Error al borrar {filename}: {e}")
```

**Algoritmo FIFO** (First In, First Out):
- Usa `os.path.getmtime()`: timestamp de última modificación
- `min()` encuentra el archivo con timestamp más antiguo
- Política: "El primero en llegar, el primero en salir"

**Ejemplo**:
```
Archivos en /resultados/mseed:
- RSA01_20251120_140000.mseed  (mtime: 1732118400)  ← MÁS ANTIGUO
- RSA01_20251121_140000.mseed  (mtime: 1732204800)
- RSA01_20251122_140000.mseed  (mtime: 1732291200)

delete_oldest_file("/resultados/mseed", ".mseed", logger)
→ Borra: RSA01_20251120_140000.mseed
```

---

### 6. obtener_logger()

**Propósito**: Crear o recuperar instancia de logger por estación (patrón singleton).

**Líneas**: 64-88

**Parámetros**:
- `id_estacion` (str): Identificador de la estación
- `log_directory` (str): Directorio donde crear el archivo de log
- `log_filename` (str): Nombre del archivo de log

**Retorno**: Instancia de `logging.Logger`

**Implementación**:
```python
loggers = {}  # Variable global (caché de loggers)

def obtener_logger(id_estacion, log_directory, log_filename):
    global loggers

    # 1. Verificar si ya existe el logger
    if id_estacion not in loggers:
        # 2. Crear nuevo logger
        logger = logging.getLogger(id_estacion)
        logger.setLevel(logging.DEBUG)

        # 3. Crear directorio de logs si no existe
        if not os.path.isdir(log_directory):
            os.makedirs(log_directory)

        # 4. Configurar handler de archivo
        log_path = os.path.join(log_directory, log_filename)
        file_handler = logging.FileHandler(log_path)
        file_handler.setLevel(logging.DEBUG)

        # 5. Configurar formato
        formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        )
        file_handler.setFormatter(formatter)

        # 6. Agregar handler y cachear
        logger.addHandler(file_handler)
        loggers[id_estacion] = logger

    return loggers[id_estacion]
```

**Ventajas del patrón singleton**:
- Un solo archivo de log por estación
- Sin duplicación de mensajes
- Reutilización eficiente de recursos

**Formato de log**:
```
2025-11-25 14:30:45,123 - RSA01 - INFO - Se encontraron 24 archivos mseed
2025-11-25 14:30:45,234 - RSA01 - WARNING - Espacio libre: 8.5%
```

---

## Modos de Operación

### Modo OFFLINE

**Configuración**:
```json
{
  "dispositivo": {
    "modo_adquisicion": "offline"
  }
}
```

**Comportamiento** (líneas 137-163):

```python
if mode_acq == "offline":
    logger.info("Modo offline activado.")

    # 1. Gestión de archivos binarios (.dat)
    binary_files = [os.path.join(binary_directory, f) for f in archivos_binarios]
    if binary_files:
        # Encontrar el más reciente
        most_recent_file = max(binary_files, key=os.path.getmtime)
        filename_bin_recent = os.path.basename(most_recent_file)
        logger.info(f"Archivo binario más reciente: {filename_bin_recent}")

        # Borrar TODOS excepto el más reciente
        for path_archivo in binary_files:
            if path_archivo != most_recent_file:
                filename_bin = os.path.basename(path_archivo)
                os.remove(path_archivo)
                logger.info(f"Archivo binario borrado: {filename_bin}")

    # 2. Gestión de archivos Mini-SEED (.mseed)
    free_space = get_free_space_percentage(mseed_directory)
    logger.info(f"Espacio libre en mseed: {free_space:.2f}%")

    if free_space < min_free_space_threshold:
        logger.warning(f"Espacio < {min_free_space_threshold}%. Borrando .mseed más antiguo.")
        delete_oldest_file(mseed_directory, ".mseed", logger)
```

**Políticas**:

1. **Archivos .dat**:
   - Mantiene **solo el más reciente** (el que está siendo escrito por registro_continuo)
   - Borra todos los demás inmediatamente
   - Razón: Los .dat son grandes (~9 MB/hora) y ya fueron convertidos a .mseed

2. **Archivos .mseed**:
   - Mantiene todos mientras haya espacio > umbral (default 10%)
   - Cuando espacio < 10%: borra el más antiguo (FIFO)
   - Razón: Los .mseed son el formato de distribución, se preservan para análisis

**Ejemplo de cronología**:

```
14:00 - Gestor ejecuta:
        - Archivos .dat: [13:00.dat, 14:00.dat (actual)]
        - Borra: 13:00.dat
        - Mantiene: 14:00.dat
        - Archivos .mseed: 100 archivos, espacio: 15%
        - No borra ningún .mseed

15:00 - Gestor ejecuta:
        - Archivos .dat: [14:00.dat, 15:00.dat (actual)]
        - Borra: 14:00.dat
        - Mantiene: 15:00.dat
        - Archivos .mseed: 101 archivos, espacio: 8%
        - Borra .mseed más antiguo (FIFO)
```

---

### Modo ONLINE

**Configuración**:
```json
{
  "dispositivo": {
    "modo_adquisicion": "online",
    "umbral_espacio_minimo": 10
  },
  "drive": {
    "max_reintentos": 3,
    "tiempo_espera": 1
  }
}
```

**Comportamiento** (líneas 165-208):

```python
elif mode_acq == "online":
    logger.info("Modo online activado.")

    # 1. Verificar conexión a internet
    if check_internet_connection(logger):
        logger.info("Conexión establecida. Subiendo archivos mseed a Drive.")

        if archivos_mseed:
            # Obtener parámetros de subida
            max_reintentos = str(config_dispositivo.get("drive", {}).get("max_reintentos", 3))
            tiempo_espera = str(config_dispositivo.get("drive", {}).get("tiempo_espera", 1))

            # Subir cada archivo .mseed
            for archivo in archivos_mseed:
                logger.info(f"Subiendo: {archivo}")
                result = subprocess.run(
                    ["python3", script_subir_archivo_drive, archivo, max_reintentos, tiempo_espera],
                    capture_output=True,
                    text=True
                )
                if result.returncode == 0:
                    logger.info(f"{archivo} subido exitosamente.")
                else:
                    logger.error(f"Error al subir {archivo}. Código: {result.returncode}")

        # Verificar espacio en binarios después de subida
        free_space = get_free_space_percentage(binary_directory)
        if free_space < min_free_space_threshold:
            delete_oldest_file(binary_directory, ".dat", logger)

    else:
        # Sin conexión: gestionar espacio localmente
        free_space = get_free_space_percentage(mseed_directory)
        if free_space < min_free_space_threshold:
            delete_oldest_file(mseed_directory, ".mseed", logger)

        free_space = get_free_space_percentage(binary_directory)
        if free_space < min_free_space_threshold:
            delete_oldest_file(binary_directory, ".dat", logger)
```

**Flujo detallado con conexión**:

```
┌─────────────────────────────────────────┐
│ 1. check_internet_connection()          │
│    → True (conexión OK)                 │
└─────────────────────────────────────────┘
             ↓
┌─────────────────────────────────────────┐
│ 2. Para cada archivo .mseed:            │
│    ├─ subprocess.run(subir_archivo.py)  │
│    ├─ Captura stdout/stderr             │
│    └─ Log resultado                     │
└─────────────────────────────────────────┘
             ↓
┌─────────────────────────────────────────┐
│ 3. Verificar espacio en /binarios       │
│    Si < umbral: delete_oldest_file()    │
└─────────────────────────────────────────┘
```

**Flujo detallado sin conexión**:

```
┌─────────────────────────────────────────┐
│ 1. check_internet_connection()          │
│    → False (sin conexión)               │
└─────────────────────────────────────────┘
             ↓
┌─────────────────────────────────────────┐
│ 2. Verificar espacio en /mseed          │
│    Si < umbral: delete_oldest_file()    │
└─────────────────────────────────────────┘
             ↓
┌─────────────────────────────────────────┐
│ 3. Verificar espacio en /binarios       │
│    Si < umbral: delete_oldest_file()    │
└─────────────────────────────────────────┘
```

**Comportamiento resiliente**:
- Si no hay conexión: opera como modo offline temporalmente
- Cuando conexión se recupera: sube archivos acumulados
- Garantiza operación continua independiente de conectividad

---

## Configuración

### configuracion_dispositivo.json

**Ubicación**: `$PROJECT_LOCAL_ROOT/configuracion/configuracion_dispositivo.json`

**Campos utilizados**:

```json
{
  "dispositivo": {
    "id": "RSA01",
    "modo_adquisicion": "online",
    "umbral_espacio_minimo": 10
  },
  "drive": {
    "max_reintentos": 3,
    "tiempo_espera": 1
  },
  "directorios": {
    "registro_continuo": "/home/rsa/resultados/registro-continuo/",
    "archivos_mseed": "/home/rsa/resultados/mseed/"
  }
}
```

**Descripción de campos**:

| Campo | Tipo | Default | Descripción |
|-------|------|---------|-------------|
| `dispositivo.id` | string | - | Identificador único de la estación |
| `dispositivo.modo_adquisicion` | string | - | "online" o "offline" |
| `dispositivo.umbral_espacio_minimo` | int | 10 | Porcentaje mínimo de espacio libre (%) |
| `drive.max_reintentos` | int | 3 | Intentos de subida antes de fallar |
| `drive.tiempo_espera` | int | 1 | Segundos entre reintentos |

**Valores recomendados**:

```json
// Estación remota con SD card de 32 GB
{
  "dispositivo": {
    "modo_adquisicion": "offline",
    "umbral_espacio_minimo": 15  // Mayor margen de seguridad
  }
}

// Estación en oficina con conexión estable
{
  "dispositivo": {
    "modo_adquisicion": "online",
    "umbral_espacio_minimo": 5   // Menor umbral, Drive es respaldo
  },
  "drive": {
    "max_reintentos": 5,           // Más reintentos para conexiones lentas
    "tiempo_espera": 2
  }
}
```

---

## Logging y Diagnóstico

### Archivo de Log

**Ubicación**: `$PROJECT_LOCAL_ROOT/log-files/gestor_acq.log`

**Formato**:
```
%(asctime)s - %(name)s - %(levelname)s - %(message)s
```

**Ejemplo**:
```
2025-11-25 14:00:00,123 - RSA01 - INFO - Archivo configuracion_dispositivo.json leído correctamente.
2025-11-25 14:00:00,234 - RSA01 - INFO - Modo online activado.
2025-11-25 14:00:00,345 - RSA01 - INFO - Se encontraron 24 archivos mseed y 2 archivos binarios.
2025-11-25 14:00:00,456 - RSA01 - INFO - Conexión a internet verificada.
2025-11-25 14:00:01,567 - RSA01 - INFO - Subiendo el archivo: RSA01_20251125_130000.mseed
2025-11-25 14:00:15,678 - RSA01 - INFO - Archivo RSA01_20251125_130000.mseed subido exitosamente a Google Drive.
2025-11-25 14:00:15,789 - RSA01 - INFO - Espacio libre en directorio binarios: 23.45%
```

### Niveles de Log Utilizados

#### INFO
**Uso**: Operaciones normales exitosas

**Ejemplos**:
```
- Archivo de configuración leído correctamente
- Modo online/offline activado
- Conexión a internet verificada
- Archivo subido exitosamente
- Espacio libre: X%
- Se borró el archivo más antiguo: X.mseed
```

#### WARNING
**Uso**: Situaciones anómalas pero no críticas

**Ejemplos**:
```
- Fallo en la conexión a internet: [Errno 111] Connection refused
- No se encontraron archivos con extensión .mseed en /path/
- El espacio disponible es menor al 10%
```

#### ERROR
**Uso**: Errores que impiden operaciones

**Ejemplos**:
```
- Archivo configuracion_dispositivo.json no encontrado
- El directorio mseed no existe: /path/
- Error al borrar el archivo X.dat: [Errno 13] Permission denied
- Error al subir el archivo X.mseed. Código de retorno: 1
```

### Diagnóstico de Problemas Comunes

#### 1. Espacio en disco agotándose rápidamente

**Síntoma en log**:
```
14:00 - INFO - Espacio libre: 12.34%
15:00 - WARNING - Espacio libre: 8.45%. Se procederá a borrar...
16:00 - WARNING - Espacio libre: 7.23%. Se procederá a borrar...
```

**Causas posibles**:
1. Umbral demasiado bajo (aumentar `umbral_espacio_minimo`)
2. Conversión a Mini-SEED no está ejecutándose
3. Tasa de adquisición mayor a esperada

**Solución**:
```bash
# Verificar conversión
cat /path/to/log-files/mseed.log | grep "creado con éxito"

# Aumentar umbral
# En configuracion_dispositivo.json:
"umbral_espacio_minimo": 20
```

#### 2. Archivos no se suben a Drive

**Síntoma en log**:
```
14:00 - INFO - Subiendo el archivo: RSA01_20251125_130000.mseed
14:00 - ERROR - Error al subir el archivo RSA01_20251125_130000.mseed. Código de retorno: 1
14:00 - ERROR - Error: Failed to authenticate with Google Drive
```

**Causas**:
1. Credenciales de Drive expiradas
2. Script subir_archivo.py no configurado
3. Permisos insuficientes

**Solución**:
```bash
# Probar script manualmente
python3 /path/to/subir_archivo.py test.mseed 3 1

# Revisar credenciales
ls -l ~/.credentials/
```

#### 3. Gestor no elimina archivos antiguos

**Síntoma**: Disco lleno, pero no hay mensajes de borrado en log.

**Causas**:
1. Gestor no está siendo ejecutado (verificar cron)
2. Permisos insuficientes para borrar archivos
3. Directorio incorrecto en configuración

**Solución**:
```bash
# Verificar cron
crontab -l | grep gestor_archivos_acq

# Verificar permisos
ls -l /path/to/resultados/mseed/

# Ejecutar manualmente
python3 /path/to/gestor_archivos_acq.py
```

---

## Gestión de Espacio en Disco

### Cálculo de Capacidad Requerida

**Parámetros**:
- Frecuencia de muestreo: 250 Hz
- Canales: 3 (X, Y, Z)
- Tamaño de trama binaria: 2506 bytes/segundo
- Tamaño de archivo .mseed (comprimido STEIM1): ~3 MB/hora

**Cálculo por día**:
```
Archivos .dat (sin compresión):
- 2506 bytes/segundo × 3600 segundos/hora = 9.02 MB/hora
- 9.02 MB/hora × 24 horas/día = 216.5 MB/día

Archivos .mseed (comprimidos):
- ~3 MB/hora × 24 horas/día = 72 MB/día

Total por día: 216.5 + 72 = 288.5 MB/día
```

**Capacidad recomendada por modo**:

| Modo | Capacidad Mínima | Capacidad Recomendada | Duración de Almacenamiento |
|------|------------------|----------------------|---------------------------|
| Offline | 8 GB | 32 GB | ~45 días (solo .mseed) |
| Online | 4 GB | 16 GB | Respaldo temporal hasta subida |

### Estrategia de Limpieza por Modo

#### Modo Offline

**Objetivo**: Maximizar duración de almacenamiento local.

**Política**:
```
Archivos .dat:
- Mantiene SOLO el actual (siendo escrito por registro_continuo)
- Borra todos los demás inmediatamente
- Libera ~216 MB/día

Archivos .mseed:
- Mantiene TODOS mientras espacio > umbral
- Si espacio < umbral: borra el más antiguo (FIFO)
```

**Ejemplo con SD de 32 GB**:
```
Espacio disponible: 30 GB
Consumo diario: 72 MB (solo .mseed)
Duración: 30000 MB / 72 MB/día = 416 días

Con umbral de 10%:
Duración real: 27000 MB / 72 MB/día = 375 días
```

#### Modo Online

**Objetivo**: Mantener respaldo temporal hasta subida a Drive.

**Política**:
```
Con conexión:
- Sube .mseed a Drive
- Archivos .mseed pueden borrarse después (manual o automático)
- Archivos .dat: borra más antiguo si espacio < umbral

Sin conexión:
- Opera como modo offline temporalmente
- Acumula .mseed hasta recuperar conexión
```

**Ejemplo con disco de 16 GB**:
```
Espacio disponible: 15 GB
Consumo diario: 288 MB (ambos tipos)

Sin conexión prolongada:
15000 MB / 288 MB/día = 52 días de autonomía

Con conexión normal:
Autonomía indefinida (Drive es storage principal)
```

### Monitoreo de Espacio

**Comando manual**:
```bash
# Espacio total en partición
df -h /home/rsa/resultados/

# Espacio por tipo de archivo
du -sh /home/rsa/resultados/mseed/
du -sh /home/rsa/resultados/registro-continuo/

# Conteo de archivos
ls /home/rsa/resultados/mseed/*.mseed | wc -l
```

**Alerta temprana**:
```bash
# Script de monitoreo adicional (no incluido)
#!/bin/bash
THRESHOLD=15
CURRENT=$(df /home/rsa/resultados/ | tail -1 | awk '{print 100-$5}' | sed 's/%//')
if [ $CURRENT -lt $THRESHOLD ]; then
    echo "¡Alerta! Espacio libre: ${CURRENT}%"
    # Enviar email o notificación MQTT
fi
```

---

## Integración con Google Drive

### Arquitectura de Subida

```
gestor_archivos_acq.py
         ↓
    subprocess.run()
         ↓
   subir_archivo.py
         ↓
   Google Drive API
         ↓
   Carpeta en Drive
```

### Llamada a subir_archivo.py

**Líneas**: 176-180

**Comando**:
```python
result = subprocess.run(
    ["python3", script_subir_archivo_drive, archivo, max_reintentos, tiempo_espera],
    capture_output=True,
    text=True
)
```

**Parámetros pasados**:
1. `archivo`: Nombre del archivo .mseed (ej. "RSA01_20251125_130000.mseed")
2. `max_reintentos`: Número de intentos antes de fallar (string)
3. `tiempo_espera`: Segundos entre reintentos (string)

**Ejemplo**:
```bash
python3 /path/to/subir_archivo.py RSA01_20251125_130000.mseed 3 1
#                                  └─────────┬─────────┘       │ │
#                                     Archivo a subir          │ │
#                                                   Reintentos ─┘ │
#                                                      Espera (s) ─┘
```

### Manejo de Resultado

```python
if result.returncode == 0:
    # Éxito
    logger.info(f"Archivo {archivo} subido exitosamente.")
    if result.stdout:
        logger.debug(f"Salida: {result.stdout.strip()}")
else:
    # Error
    logger.error(f"Error al subir {archivo}. Código: {result.returncode}")
    if result.stderr:
        logger.error(f"Error: {result.stderr.strip()}")
```

**Códigos de retorno esperados**:
- `0`: Subida exitosa
- `1`: Error general (credenciales, permisos, etc.)
- `2`: Archivo no encontrado
- `3`: Timeout o error de red

### Configuración de Drive

**Requisitos previos** (no manejados por este script):
1. Credenciales de Google Drive API configuradas
2. Script `subir_archivo.py` funcional
3. Permisos de escritura en carpeta de Drive

**Verificación**:
```bash
# Probar subida manual
python3 /path/to/subir_archivo.py test.mseed 3 1

# Verificar credenciales
ls ~/.credentials/credentials.json

# Ver log de subir_archivo.py
cat /path/to/log-files/drive.log
```

---

## Modo de Uso

### Instalación y Configuración

#### 1. Configurar variables de entorno

```bash
# En ~/.bashrc o /etc/environment
export PROJECT_LOCAL_ROOT=/home/rsa
```

#### 2. Crear estructura de directorios

```bash
mkdir -p $PROJECT_LOCAL_ROOT/resultados/mseed
mkdir -p $PROJECT_LOCAL_ROOT/resultados/registro-continuo
mkdir -p $PROJECT_LOCAL_ROOT/log-files
```

#### 3. Configurar archivo JSON

```bash
nano $PROJECT_LOCAL_ROOT/configuracion/configuracion_dispositivo.json
```

```json
{
  "dispositivo": {
    "id": "RSA01",
    "modo_adquisicion": "online",
    "umbral_espacio_minimo": 10
  },
  "drive": {
    "max_reintentos": 3,
    "tiempo_espera": 1
  },
  "directorios": {
    "registro_continuo": "/home/rsa/resultados/registro-continuo/",
    "archivos_mseed": "/home/rsa/resultados/mseed/"
  }
}
```

### Ejecución Manual

```bash
# Ejecutar una vez
python3 /path/to/gestor_archivos_acq.py

# Ver log en tiempo real
tail -f $PROJECT_LOCAL_ROOT/log-files/gestor_acq.log
```

### Automatización con Cron

**Configuración recomendada**:

```bash
# Editar crontab
crontab -e

# Agregar entrada (ejecutar cada hora)
0 * * * * export PROJECT_LOCAL_ROOT=/home/rsa && /usr/bin/python3 /home/rsa/scripts/operation/drive/gestor_archivos_acq.py >> /home/rsa/log-files/cron_gestor.log 2>&1
```

**Frecuencias alternativas**:

```bash
# Cada 30 minutos
*/30 * * * * ...

# Cada 6 horas
0 */6 * * * ...

# Diariamente a las 2 AM
0 2 * * * ...
```

### Verificación de Funcionamiento

```bash
# 1. Verificar que cron está activo
systemctl status cron

# 2. Ver última ejecución
tail -20 $PROJECT_LOCAL_ROOT/log-files/gestor_acq.log

# 3. Verificar espacio en disco
df -h /home/rsa/resultados/

# 4. Contar archivos
ls $PROJECT_LOCAL_ROOT/resultados/mseed/*.mseed | wc -l
ls $PROJECT_LOCAL_ROOT/resultados/registro-continuo/*.dat | wc -l
```

---

## Consideraciones Importantes

### 1. Sincronización con Otros Procesos

**Archivos .dat en uso**:
- `registro_continuo_4.5.0.c` mantiene archivo abierto en modo append
- El gestor NUNCA debe borrar el archivo más reciente
- Identificación por timestamp de modificación (más reciente = actual)

**Archivos .mseed**:
- Generados por `binary_to_mseed.py` después de cerrar .dat
- Seguros para borrar una vez subidos a Drive (modo online)
- Son el formato de distribución (preservar en modo offline)

### 2. Manejo de Medianoche

**Problema**: Cambio de día puede afectar identificación de archivo más reciente.

**Escenario**:
```
23:59 - Archivo actual: RSA01_20251125_230000.dat
00:00 - Nuevo archivo: RSA01_20251126_000000.dat
00:05 - Gestor ejecuta
```

**Solución implementada**: Uso de `os.path.getmtime()` (timestamp absoluto, independiente de fecha).

### 3. Permisos de Archivos

**Requisitos**:
- Usuario que ejecuta el gestor debe tener permisos de lectura/escritura en:
  - `/resultados/mseed/`
  - `/resultados/registro-continuo/`
  - `/log-files/`

**Configuración recomendada**:
```bash
# Crear usuario específico
sudo useradd -m rsa-gestor

# Asignar permisos
sudo chown -R rsa-gestor:rsa-gestor /home/rsa/resultados/
sudo chown -R rsa-gestor:rsa-gestor /home/rsa/log-files/

# Ejecutar cron como ese usuario
sudo crontab -u rsa-gestor -e
```

### 4. Comportamiento en Fallas

**Falla de Drive**:
- No detiene ejecución
- Log de error
- Archivos se acumulan localmente
- Próxima ejecución reintenta subida

**Disco lleno**:
- `os.remove()` puede fallar
- Log de error
- Sistema continúa operando (puede llenar disco completamente)

**Configuración corrupta**:
- Script termina inmediatamente
- Log de error
- No borra archivos (safe-fail)

---

## Problemas Identificados

### 1. No Elimina Archivos .mseed Después de Subir a Drive

**Líneas**: 165-189 (modo online con conexión)

**Problema**: Después de subir exitosamente un archivo .mseed a Drive, el script NO lo elimina del disco local.

**Impacto**:
- Acumulación de archivos .mseed en disco
- Eventualmente llena el disco (aunque con gestión posterior)
- Duplicación innecesaria (Drive + local)

**Comportamiento actual**:
```python
if result.returncode == 0:
    logger.info(f"Archivo {archivo} subido exitosamente.")
    # ¡Falta: os.remove(archivo)!
```

**Solución recomendada**:
```python
if result.returncode == 0:
    logger.info(f"Archivo {archivo} subido exitosamente a Google Drive.")
    try:
        os.remove(os.path.join(mseed_directory, archivo))
        logger.info(f"Archivo local {archivo} eliminado después de subida.")
    except Exception as e:
        logger.error(f"Error al eliminar {archivo} local: {e}")
```

### 2. Ausencia de Validación de Integridad de Subida

**Problema**: No verifica que el archivo subido a Drive esté completo y sin corrupción.

**Riesgo**:
- Archivo corrupto en Drive
- Archivo local borrado (si se implementa #1)
- Pérdida de datos

**Solución sugerida**:
```python
# En subir_archivo.py, retornar checksum
# En gestor, comparar antes de borrar local
import hashlib

def calculate_md5(filepath):
    hash_md5 = hashlib.md5()
    with open(filepath, "rb") as f:
        for chunk in iter(lambda: f.read(4096), b""):
            hash_md5.update(chunk)
    return hash_md5.hexdigest()

local_md5 = calculate_md5(os.path.join(mseed_directory, archivo))
# Comparar con MD5 retornado por subir_archivo.py
```

### 3. Falta de Rate Limiting en Subidas

**Problema**: Si hay muchos archivos .mseed acumulados, el script intenta subirlos todos secuencialmente sin pausas.

**Impacto**:
- Posible throttling por Google Drive API (cuotas)
- Uso intensivo de CPU/red
- Bloqueo prolongado del script

**Código problemático** (líneas 174-188):
```python
for archivo in archivos_mseed:
    # Sube inmediatamente sin pausa
    subprocess.run(...)
```

**Solución sugerida**:
```python
import time

max_files_per_run = 10  # Configurable
for i, archivo in enumerate(archivos_mseed[:max_files_per_run]):
    subprocess.run(...)
    if i < len(archivos_mseed) - 1:
        time.sleep(5)  # Pausa entre subidas
```

### 4. No Maneja Archivos Parciales o Corruptos

**Problema**: Si `binary_to_mseed.py` falla durante conversión, puede dejar archivos .mseed incompletos.

**Impacto**:
- Script intenta subir archivo corrupto
- Falla repetidamente
- Bloquea procesamiento de archivos válidos

**Solución sugerida**:
```python
def is_valid_mseed(filepath):
    try:
        from obspy import read
        st = read(filepath)
        return len(st) == 3  # Debe tener 3 canales
    except:
        return False

# Antes de subir
if not is_valid_mseed(os.path.join(mseed_directory, archivo)):
    logger.warning(f"Archivo {archivo} parece corrupto. Moviendo a quarantine/")
    shutil.move(os.path.join(mseed_directory, archivo),
                os.path.join(mseed_directory, "quarantine", archivo))
    continue
```

### 5. Logging Básico en Lugar de Básico+Rotación

**Problema**: El archivo `gestor_acq.log` crece indefinidamente.

**Impacto**:
- Eventualmente ocupa mucho espacio
- Dificulta lectura y análisis

**Solución sugerida**:
```python
from logging.handlers import RotatingFileHandler

handler = RotatingFileHandler(
    log_path,
    maxBytes=10*1024*1024,  # 10 MB
    backupCount=5           # Mantener 5 archivos de respaldo
)
```

### 6. No Hay Notificaciones de Estado

**Problema**: Solo logging local, sin alertas proactivas.

**Impacto**:
- Operador debe revisar logs manualmente
- Fallas pueden pasar desapercibidas días/semanas

**Solución sugerida**:
```python
def enviar_alerta_mqtt(mensaje, nivel="warning"):
    # Publicar en tópico MQTT para monitoreo remoto
    import paho.mqtt.publish as publish
    publish.single("rsa/estaciones/RSA01/alertas",
                   payload=mensaje,
                   hostname="mqtt.example.com")

# Al detectar espacio crítico
if free_space < min_free_space_threshold:
    enviar_alerta_mqtt(f"Espacio crítico: {free_space:.1f}%", "warning")
```

---

## Mejoras Potenciales

### 1. Dashboard Web de Monitoreo

**Propuesta**: Interfaz web para visualizar estado de estaciones.

```python
# Agregar endpoint Flask
from flask import Flask, jsonify

app = Flask(__name__)

@app.route('/status')
def get_status():
    return jsonify({
        "estacion": id_estacion,
        "modo": mode_acq,
        "espacio_mseed": get_free_space_percentage(mseed_directory),
        "espacio_binarios": get_free_space_percentage(binary_directory),
        "archivos_mseed": len(archivos_mseed),
        "ultima_subida": get_last_upload_time()
    })
```

### 2. Compresión Adicional de Archivos Antiguos

**Propuesta**: Comprimir archivos .mseed antes de borrar.

```python
import gzip

def compress_and_move(filepath, archive_dir):
    with open(filepath, 'rb') as f_in:
        with gzip.open(f"{archive_dir}/{os.path.basename(filepath)}.gz", 'wb') as f_out:
            shutil.copyfileobj(f_in, f_out)
    os.remove(filepath)
```

**Ventaja**: Mantener más datos históricos en mismo espacio.

### 3. Modo Híbrido (Online/Offline Automático)

**Propuesta**: Cambiar automáticamente según disponibilidad de red.

```python
# Eliminar configuración estática de modo
# Detectar automáticamente en cada ejecución
if check_internet_connection(logger):
    mode_acq = "online"
else:
    mode_acq = "offline"
```

### 4. Priorización de Subidas

**Propuesta**: Subir eventos detectados antes que registro continuo.

```python
# Separar archivos por tipo
eventos = [f for f in archivos_mseed if "_EVT_" in f]
continuos = [f for f in archivos_mseed if "_EVT_" not in f]

# Subir eventos primero
for archivo in eventos + continuos:
    subprocess.run(...)
```

### 5. Estadísticas de Uso

**Propuesta**: Generar reporte de uso de disco y subidas.

```python
# Al final de main()
generar_reporte_estadisticas()

def generar_reporte_estadisticas():
    report = {
        "timestamp": datetime.now().isoformat(),
        "archivos_borrados_hoy": count_deleted_today(),
        "archivos_subidos_hoy": count_uploaded_today(),
        "espacio_liberado_mb": calculate_space_freed()
    }
    with open(f"{log_directory}/stats_{datetime.now().date()}.json", 'w') as f:
        json.dump(report, f, indent=2)
```

### 6. Health Check Endpoint

**Propuesta**: Endpoint para monitoreo externo (Prometheus, Nagios, etc.).

```python
@app.route('/health')
def health_check():
    free_space_mseed = get_free_space_percentage(mseed_directory)
    free_space_binary = get_free_space_percentage(binary_directory)

    if free_space_mseed < 5 or free_space_binary < 5:
        return jsonify({"status": "critical"}), 500
    elif free_space_mseed < 10 or free_space_binary < 10:
        return jsonify({"status": "warning"}), 200
    else:
        return jsonify({"status": "ok"}), 200
```

---

## Resumen de Archivos Relacionados

### Scripts de Procesamiento
- [registro_continuo_4.5.0.c](../../../scripts/operation/acelerografo/registro_continuo_4.5.0.c): Genera archivos .dat
- [binary_to_mseed.py](../../../scripts/operation/mseed/binary_to_mseed.py): Convierte .dat a .mseed
- [gestor_archivos_acq.py](../../../scripts/operation/drive/gestor_archivos_acq.py): Este script
- [subir_archivo.py](../../../scripts/operation/drive/subir_archivo.py): Sube archivos a Drive

### Configuración
- `configuracion_dispositivo.json`: Configuración del sistema

### Logs
- `gestor_acq.log`: Log de este script
- `mseed.log`: Log de conversión a Mini-SEED
- `drive.log`: Log de subidas a Drive (si existe)

---

## Documentos Relacionados

Para entender el contexto completo del sistema:

1. [firmware_context.md](firmware_context.md): Firmware del dsPIC
2. [registro_continuo_context.md](registro_continuo_context.md): Adquisición en RPi
3. [binary_to_mseed_context.md](binary_to_mseed_context.md): Conversión a Mini-SEED
4. [gestor_archivos_acq_context.md](gestor_archivos_acq_context.md): Este documento
5. [CLAUDE.md](../../../CLAUDE.md): Visión general del proyecto

---

**Última actualización**: 2025-11-25

**Estado**: Documentación completa de gestor_archivos_acq.py v216 (216 líneas)

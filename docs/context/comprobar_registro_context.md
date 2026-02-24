# Contexto del Programa Comprobar Registro - Sistema de Acelerógrafo

## Resumen Ejecutivo

Este documento describe el programa de utilidad `comprobar_registro_5.0.0.c`, una herramienta de diagnóstico que se ejecuta en la **Raspberry Pi** para verificar el estado del archivo de registro continuo activo. El programa lee la última trama registrada en el archivo binario `.dat`, extrae información de timestamp y aceleración, y muestra el estado actual del sistema de adquisición.

**Ubicación**: `/home/rsa/git/montajes/acelerografo/scripts/operation/acelerografo/`
**Versión**: 5.0.0
**Lenguaje**: C (código para Raspberry Pi)
**Propósito**: Diagnóstico rápido del estado de adquisición sin interrumpir el registro continuo

---

## Arquitectura del Sistema

### Posición en el Flujo de Datos

```
┌────────────────────────────────────────────────────────────┐
│                    SISTEMA COMPLETO                        │
│                                                            │
│  registro_continuo_4.5.0 (proceso principal)               │
│           ↓ (escribe cada segundo)                         │
│  ┌─────────────────────────────────────┐                   │
│  │  Archivo .dat (binario)             │                   │
│  │  - 2506 bytes por segundo           │                   │
│  │  - Crecimiento continuo             │                   │
│  │  - Última trama = estado actual     │                   │
│  └─────────────────┬───────────────────┘                   │
│                    │                                       │
│                    │ (lee última trama)                    │
│                    ↓                                       │
│  ┌─────────────────────────────────────┐                   │
│  │  comprobar_registro_5.0.0           │◄─── Este programa │
│  │  (este programa)                    │                   │
│  │                                     │                   │
│  │  • Lee configuración JSON           │                   │
│  │  • Encuentra archivo RC actual      │                   │
│  │  • Lee última trama (2506 bytes)    │                   │
│  │  • Extrae timestamp y aceleración   │                   │
│  │  • Muestra estado en consola        │                   │
│  └─────────────────────────────────────┘                   │
│                    ↓                                       │
│             Salida en consola:                             │
│   | GPS 25/01/21 14:30:45-52245 | X: 0.00123 Y: -0.00089   │
│                                     Z: 9.80125 |           │
└────────────────────────────────────────────────────────────┘
```

---

## Propósito y Casos de Uso

### Propósito Principal

Proporcionar una forma **rápida y no invasiva** de verificar:
1. ¿Está funcionando el registro continuo?
2. ¿Cuál es el timestamp de la última muestra registrada?
3. ¿Cuál es la fuente de tiempo utilizada (GPS/RTC/RPi)?
4. ¿Hay errores de sincronización temporal?
5. ¿Los valores de aceleración son razonables?

### Ventajas sobre Alternativas

```
Alternativa 1: tail -c 2506 archivo.dat | hexdump
  ❌ Difícil de interpretar (hexadecimal)
  ❌ Requiere cálculos manuales
  ❌ No muestra fuente de tiempo

Alternativa 2: ps aux | grep registro_continuo
  ❌ Solo verifica que el proceso está activo
  ❌ No confirma que esté escribiendo datos
  ❌ No muestra timestamp actual

Alternativa 3: ls -lh archivo.dat (verificar tamaño)
  ❌ No muestra contenido
  ❌ Puede crecer sin datos válidos
  ❌ No detecta errores de tiempo

Este programa (comprobar_registro_5.0.0):
  ✅ Interpretación automática de datos
  ✅ Formato legible para humanos
  ✅ Muestra fuente de tiempo y errores
  ✅ Verifica aceleraciones
  ✅ Ejecución instantánea (<100ms)
  ✅ No interrumpe el registro continuo
```

### Casos de Uso Típicos

#### 1. Verificación Rutinaria

```bash
$ comprobar_registro_5.0.0

Tiempo del sistema:
25/01/21 14:32:18

Archivo actual: 'CHA01_250121-143025.dat'
Tamaño del archivo: 627500

Datos de la trama:
| GPS 25/01/21 14:32:17-52337 | X: 0.00125 Y: -0.00089 Z: 9.80145 |
```

**Interpretación**:
- ✅ Sistema activo (archivo existe)
- ✅ GPS funcionando (fuente: GPS)
- ✅ Timestamp reciente (hace 1 segundo)
- ✅ Aceleración Z ≈ 9.8 m/s² (sensor en reposo, vertical)

#### 2. Detección de Problema Temporal

```bash
$ comprobar_registro_5.0.0

Tiempo del sistema:
25/01/21 14:35:42

Archivo actual: 'CHA01_250121-143025.dat'
Tamaño del archivo: 627500

Datos de la trama:
| E5 25/01/21 14:32:17-52337 | X: 0.00125 Y: -0.00089 Z: 9.80145 |
**Error E5/RTC: El GPS no responde
```

**Interpretación**:
- ⚠️ GPS perdió señal
- ⚠️ Sistema usando RTC como fallback
- ⚠️ Timestamp desactualizado (hace 3 minutos)
- ✅ Archivo no está creciendo → Investigar `registro_continuo`

#### 3. Archivo Vacío o Corrupto

```bash
$ comprobar_registro_5.0.0

Tiempo del sistema:
25/01/21 14:38:05

Archivo actual: 'CHA01_250121-143025.dat'
Tamaño del archivo: 0

Error: No se pudo abrir el archivo.
```

**Interpretación**:
- ❌ Archivo existe pero está vacío
- ❌ `registro_continuo` no está escribiendo
- → Verificar proceso: `ps aux | grep registro_continuo`

---

## Análisis del Código Fuente

### Constantes y Definiciones

```c
const int tramaSize = 2506;     // Tamaño de una trama completa
#define NUM_MUESTRAS 249        // (No usado en este programa)
```

**Nota**: `NUM_MUESTRAS` está definido pero no se utiliza en este programa. Es un remanente de versiones anteriores.

### Variables Globales

```c
// Tiempo
unsigned int tiempoSegundos;         // Timestamp en segundos desde 00:00:00

// Control de flujo
unsigned short fuenteReloj;          // 0:RPi, 1:GPS, 2:RTC, 3-5:Error
unsigned short banErrorReloj;        // Flag de error en fuente de reloj

// Configuración
char id[10];                         // ID de la estación
char dir_archivos_temporales[100];  // Ruta de archivos temporales
char dir_registro_continuo[100];    // Ruta de archivos RC
char nombreActualARC[25];           // Nombre del archivo actual
char filenameActualRegistroContinuo[100];  // Ruta completa

// Datos de aceleración (primera muestra de la trama)
unsigned short xData[3], yData[3], zData[3];  // Bytes crudos
int xValue, yValue, zValue;                   // Valores enteros (20 bits)
double xAceleracion, yAceleracion, zAceleracion;  // m/s²

// Archivos
FILE *lf;                           // Archivo de registro continuo
FILE *ftmp;                         // Archivo temporal con nombre RC
```

---

## Flujo del Programa

### Diagrama de Flujo Principal

```
┌─────────────────────────────┐
│  INICIO                     │
└──────────┬──────────────────┘
           ↓
┌─────────────────────────────┐
│ 1. Muestra tiempo del       │
│    sistema (strftime)       │
└──────────┬──────────────────┘
           ↓
┌─────────────────────────────┐
│ 2. Valida variable de       │
│    entorno PROJECT_LOCAL_   │
│    ROOT                     │
└──────────┬──────────────────┘
           ↓
┌─────────────────────────────┐
│ 3. Lee configuración JSON   │
│    - compilar_json()        │
│    - Extrae: id, dirs       │
└──────────┬──────────────────┘
           ↓
┌─────────────────────────────┐
│ 4. Lee archivo temporal     │
│    NombreArchivoRegistro    │
│    Continuo.tmp             │
│    - Obtiene nombre actual  │
└──────────┬──────────────────┘
           ↓
┌─────────────────────────────┐
│ 5. Construye ruta completa  │
│    del archivo .dat         │
└──────────┬──────────────────┘
           ↓
┌─────────────────────────────┐
│ 6. Abre archivo RC en modo  │
│    binario lectura          │
└──────────┬──────────────────┘
           ↓
┌─────────────────────────────┐
│ 7. Calcula tamaño y posición│
│    de última trama:         │
│    lastFrameIndex =         │
│      (fileSize/2506) - 1    │
│    lastFrameStart =         │
│      lastFrameIndex * 2506  │
└──────────┬──────────────────┘
           ↓
┌─────────────────────────────┐
│ 8. fseek() a última trama   │
│    fread(tramaDatos, 2506)  │
└──────────┬──────────────────┘
           ↓
┌─────────────────────────────┐
│ 9. Extrae datos:            │
│    - fuenteReloj [0]        │
│    - timestamp [2500-2505]  │
│    - aceleración [1-9]      │
└──────────┬──────────────────┘
           ↓
┌─────────────────────────────┐
│ 10. Convierte aceleración:  │
│     - Reconstruye 20 bits   │
│     - Complemento a 2       │
│     - Multiplica por factor │
└──────────┬──────────────────┘
           ↓
┌─────────────────────────────┐
│ 11. Imprime resultado       │
│     formateado              │
└──────────┬──────────────────┘
           ↓
┌─────────────────────────────┐
│ 12. Si error de reloj,      │
│     imprime descripción     │
└──────────┬──────────────────┘
           ↓
┌─────────────────────────────┐
│ 13. Cierra archivos         │
│     Libera memoria          │
│     return 0                │
└─────────────────────────────┘
```

---

## Análisis Detallado por Secciones

### Sección 1: Inicialización y Configuración

```c
int main(void) {
    // 1. Obtiene y muestra tiempo del sistema
    time_t t;
    struct tm *tm_info;
    t = time(NULL);
    time(&t);  // Redundante, pero inofensivo
    tm_info = localtime(&t);

    char formattedTime[20];
    strftime(formattedTime, 20, "%y/%m/%d %H:%M:%S", tm_info);

    printf("\nTiempo del sistema:\n");
    printf("%s\n", formattedTime);
```

**Propósito**: Mostrar la hora del sistema para comparar con el timestamp de la última trama.

**Formato de salida**:
```
Tiempo del sistema:
25/01/21 14:32:18
```

### Sección 2: Validación de Entorno

```c
    // 2. Valida PROJECT_LOCAL_ROOT
    const char *project_local_root = getenv("PROJECT_LOCAL_ROOT");
    if (project_local_root == NULL) {
        fprintf(stderr, "Error: La variable de entorno PROJECT_LOCAL_ROOT no está configurada.\n");
        return 1;
    }

    static char config_path[256];
    snprintf(config_path, sizeof(config_path),
             "%s/configuracion/configuracion_dispositivo.json",
             project_local_root);
    config_filename = config_path;
```

**Propósito**: Asegurar portabilidad del programa usando variable de entorno estándar del sistema.

**Valor típico**:
```bash
PROJECT_LOCAL_ROOT=/home/rsa/projects/acelerografo
config_path=/home/rsa/projects/acelerografo/configuracion/configuracion_dispositivo.json
```

### Sección 3: Lectura de Configuración JSON

```c
    // 3. Lee configuración JSON
    struct datos_config *config = compilar_json(config_filename);
    if (config == NULL) {
        fprintf(stderr, "Error al leer el archivo de configuracion JSON.\n");
        return 1;
    }

    // Extrae valores necesarios
    strncpy(id, config->id, sizeof(id) - 1);
    strncpy(dir_archivos_temporales, config->archivos_temporales,
            sizeof(dir_archivos_temporales) - 1);
    strncpy(dir_registro_continuo, config->registro_continuo,
            sizeof(dir_registro_continuo) - 1);

    // Asegura terminación nula
    id[sizeof(id) - 1] = '\0';
    dir_archivos_temporales[sizeof(dir_archivos_temporales) - 1] = '\0';
    dir_registro_continuo[sizeof(dir_registro_continuo) - 1] = '\0';
```

**Campos utilizados del JSON**:
- `dispositivo.id`: ID de la estación (ej: "CHA01")
- `directorios.archivos_temporales`: Ruta de archivos temporales
- `directorios.registro_continuo`: Ruta de archivos de registro continuo

**Nota**: No lee `fuente_reloj` ni `deteccion_eventos` porque no los necesita para su operación.

### Sección 4: Identificación del Archivo Actual

```c
    // 4. Lee archivo temporal con nombre del RC actual
    snprintf(filenameArchivoTemporal, sizeof(filenameArchivoTemporal),
             "%sNombreArchivoRegistroContinuo.tmp",
             dir_archivos_temporales);

    ftmp = fopen(filenameArchivoTemporal, "rt");
    if (ftmp == NULL) {
        fprintf(stderr, "Error al abrir el archivo temporal para nombres de archivos RC.\n");
        free(config);
        return 1;
    }

    fgets(nombreActualARC, sizeof(nombreActualARC), ftmp);
    nombreActualARC[strcspn(nombreActualARC, "\r\n")] = 0;  // Elimina salto de línea
    fclose(ftmp);

    // Construye ruta completa
    snprintf(filenameActualRegistroContinuo,
             sizeof(filenameActualRegistroContinuo),
             "%s%s",
             dir_registro_continuo,
             nombreActualARC);

    printf("\nArchivo actual: '%s'\n", nombreActualARC);
```

**Archivo temporal**: `{dir_archivos_temporales}/NombreArchivoRegistroContinuo.tmp`

**Contenido típico del archivo temporal**:
```
CHA01_250121-143025.dat
CHA01_250121-142015.dat
```

**Línea 1**: Nombre del archivo actual
**Línea 2**: Nombre del archivo anterior

El programa solo lee la primera línea.

**Ruta completa construida**: `/home/rsa/projects/acelerografo/datos/RC/CHA01_250121-143025.dat`

### Sección 5: Lectura de la Última Trama

```c
    // 5. Abre archivo en modo binario
    lf = fopen(filenameActualRegistroContinuo, "rb");
    if (lf == NULL) {
        fprintf(stderr, "No se pudo abrir el archivo.\n");
        free(config);
        return 1;
    }

    // 6. Calcula tamaño del archivo
    fseek(lf, 0, SEEK_END);
    long fileSize = ftell(lf);
    printf("Tamaño del archivo:%d\n", fileSize);

    // 7. Calcula posición de la última trama
    long lastFrameIndex = (fileSize / tramaSize) - 1;
    long lastFrameStart = lastFrameIndex * tramaSize;

    // 8. Posiciona el cursor al inicio de la última trama
    fseek(lf, lastFrameStart, SEEK_SET);

    // 9. Lee la última trama
    char tramaDatos[tramaSize];
    fread(tramaDatos, sizeof(char), tramaSize, lf);
```

**Ejemplo de cálculo**:
```
fileSize = 627500 bytes
tramaSize = 2506 bytes

lastFrameIndex = (627500 / 2506) - 1 = 250 - 1 = 249
lastFrameStart = 249 × 2506 = 623994 bytes

Se posiciona en byte 623994 y lee 2506 bytes
(del byte 623994 al 626499)
```

**Nota importante en el código**:
```c
// Línea 150: Lee la última trama
fread(tramaDatos, sizeof(char), tramaSize, lf);

// Línea 155: ¡Lee de nuevo! (BUG POTENCIAL)
fread(tramaDatos, sizeof(char), tramaSize, lf);
```

**Análisis del bug**:
- La línea 155 ejecuta un segundo `fread()` que sobrescribe `tramaDatos`
- Como el cursor ya está al final del archivo, este `fread()` retorna 0 bytes
- **Resultado**: `tramaDatos` contiene basura o ceros
- **Impacto**: Si el archivo tiene exactamente una trama más después de `lastFrameStart`, funciona por casualidad
- **Solución**: Eliminar línea 155

**Corrección recomendada**:
```c
// Eliminar la línea 155
// fread(tramaDatos, sizeof(char), tramaSize, lf);  // ← ELIMINAR

// Alternativa correcta si se quiere leer la última trama completa:
fseek(lf, -tramaSize, SEEK_END);  // Retrocede 2506 bytes desde el final
fread(tramaDatos, sizeof(char), tramaSize, lf);
```

### Sección 6: Extracción de Timestamp

```c
    // 10. Calcula tiempo en segundos
    tiempoSegundos = (3600 * tramaDatos[tramaSize - 3]) +
                     (60 * tramaDatos[tramaSize - 2]) +
                     (tramaDatos[tramaSize - 1]);

    // Extrae fuente de reloj
    fuenteReloj = tramaDatos[0];
```

**Estructura del timestamp** (últimos 6 bytes de la trama):
```
tramaDatos[2500] = año   (ej: 25 = 2025)
tramaDatos[2501] = mes   (ej: 1 = enero)
tramaDatos[2502] = día   (ej: 21)
tramaDatos[2503] = hora  (ej: 14)
tramaDatos[2504] = min   (ej: 32)
tramaDatos[2505] = seg   (ej: 17)

tiempoSegundos = 14×3600 + 32×60 + 17 = 52337 segundos desde medianoche
```

**Fuente de reloj**:
```
tramaDatos[0] = fuenteReloj
  0 = RPi (tiempo de Raspberry Pi)
  1 = GPS (sincronizado con GPS)
  2 = RTC (reloj de tiempo real DS3234)
  3 = E3 (error: trama GPS inválida)
  4 = E4 (error: no se pudo recuperar GPS)
  5 = E5 (error: GPS no responde)
```

### Sección 7: Impresión de Información Temporal

```c
    // 11. Imprime datos de la trama
    printf("\nDatos de la trama:\n");
    printf("| ");

    // Imprime fuente de reloj
    switch (fuenteReloj) {
        case 0:
            printf("RPi ");
            break;
        case 1:
            printf("GPS ");
            break;
        case 2:
            printf("RTC ");
            break;
        default:
            printf("E%d ", fuenteReloj);
            banErrorReloj = 1;
            break;
    }

    // Imprime fecha y hora
    printf("%0.2d/", tramaDatos[tramaSize - 6]);  // aa
    printf("%0.2d/", tramaDatos[tramaSize - 5]);  // mm
    printf("%0.2d ", tramaDatos[tramaSize - 4]);  // dd
    printf("%0.2d:", tramaDatos[tramaSize - 3]);  // hh
    printf("%0.2d:", tramaDatos[tramaSize - 2]);  // mm
    printf("%0.2d-", tramaDatos[tramaSize - 1]);  // ss
    printf("%d ", tiempoSegundos);
    printf("| ");
```

**Formato de salida**:
```
| GPS 25/01/21 14:32:17-52337 |
  ↑   ↑        ↑        ↑
  │   │        │        └─ Segundos desde medianoche
  │   │        └────────── Timestamp (AA/MM/DD HH:MM:SS)
  │   └─────────────────── Fecha
  └─────────────────────── Fuente de tiempo
```

### Sección 8: Extracción de Aceleración

```c
    // 12. Lee bytes de aceleración (primera muestra de la trama)
    for (x = 0; x < 3; x++) {
        xData[x] = tramaDatos[x + 1];  // Bytes 1, 2, 3
        yData[x] = tramaDatos[x + 4];  // Bytes 4, 5, 6
        zData[x] = tramaDatos[x + 7];  // Bytes 7, 8, 9
    }
```

**Estructura de la primera muestra**:
```
Byte 0:    ID de muestra (0)
Bytes 1-3: Eje X (X3, X2, X1)
Bytes 4-6: Eje Y (Y3, Y2, Y1)
Bytes 7-9: Eje Z (Z3, Z2, Z1)
```

### Sección 9: Conversión de Aceleración

```c
    // 13. Convierte bytes a valor entero de 20 bits
    xValue = ((xData[0] << 12) & 0xFF000) +
             ((xData[1] << 4) & 0xFF0) +
             ((xData[2] >> 4) & 0xF);

    // 14. Aplica complemento a 2 si es negativo
    if (xValue >= 0x80000) {
        xValue = xValue & 0x7FFFF;  // Elimina bit de signo
        xValue = -1 * (((~xValue) + 1) & 0x7FFFF);
    }

    // 15. Convierte a m/s²
    xAceleracion = xValue * (9.8 / pow(2, 18));
```

**Proceso de conversión**:

1. **Reconstrucción de 20 bits**:
   ```
   X3 = 0x01 (00000001)
   X2 = 0x23 (00100011)
   X1 = 0x45 (01000101)

   Paso 1: X3 << 12 = 0x01000
   Paso 2: X2 << 4  = 0x230
   Paso 3: X1 >> 4  = 0x4
   Resultado: 0x01234 (valor de 20 bits)
   ```

2. **Complemento a 2** (si bit 19 = 1):
   ```
   Si xValue >= 0x80000:
     xValue AND 0x7FFFF  (quita bit 19)
     NOT xValue
     +1
     AND 0x7FFFF
     × -1
   ```

3. **Conversión a aceleración**:
   ```
   Factor = 9.8 / 2^18 = 9.8 / 262144 = 0.00003738 m/s² por LSB

   Rango del ADXL355 ±2g:
   ±2g = ±19.6 m/s²
   Resolución: 19.6 / 2^19 = 0.00003738 m/s²
   ```

**Nota sobre la conversión**:
- El código usa `9.8 / pow(2, 18)` = 0.00003738 m/s²/LSB
- Esto es correcto para el rango ±2g del ADXL355
- Alternativa en gales (cm/s²): `980 / pow(2, 18)` = 3.738 gal/LSB

**Mismo proceso para ejes Y y Z**:
```c
    // Eje Y
    yValue = ((yData[0] << 12) & 0xFF000) + ((yData[1] << 4) & 0xFF0) + ((yData[2] >> 4) & 0xF);
    if (yValue >= 0x80000) {
        yValue = yValue & 0x7FFFF;
        yValue = -1 * (((~yValue) + 1) & 0x7FFFF);
    }
    yAceleracion = yValue * (9.8 / pow(2, 18));

    // Eje Z
    zValue = ((zData[0] << 12) & 0xFF000) + ((zData[1] << 4) & 0xFF0) + ((zData[2] >> 4) & 0xF);
    if (zValue >= 0x80000) {
        zValue = zValue & 0x7FFFF;
        zValue = -1 * (((~zValue) + 1) & 0x7FFFF);
    }
    zAceleracion = zValue * (9.8 / pow(2, 18));
```

### Sección 10: Impresión de Aceleraciones

```c
    printf("X: ");
    printf("%2.8f ", xAceleracion);
    printf("Y: ");
    printf("%2.8f ", yAceleracion);
    printf("Z: ");
    printf("%2.8f ", zAceleracion);
    printf("|\n");
```

**Formato de salida**:
```
X: 0.00125896 Y: -0.00089542 Z: 9.80145623 |
   ↑            ↑             ↑
   │            │             └─ Aceleración gravitacional (~9.8 m/s²)
   │            └─────────────── Pequeñas variaciones por ruido
   └──────────────────────────── Formato: 8 decimales
```

**Interpretación de valores típicos**:

| Condición | X (m/s²) | Y (m/s²) | Z (m/s²) | Interpretación |
|-----------|----------|----------|----------|----------------|
| Reposo horizontal | ~0 | ~0 | ~9.8 | Sensor vertical, sin movimiento |
| Reposo inclinado | ±0.1-1 | ±0.1-1 | 8-10 | Sensor ligeramente inclinado |
| Vibraciones | ±0.01-0.1 | ±0.01-0.1 | 9.7-9.9 | Vibraciones ambientales |
| Ruido electrónico | ±0.001-0.01 | ±0.001-0.01 | ±0.001-0.01 | Ruido del ADC |
| **Sismo pequeño** | **±0.1-1** | **±0.1-1** | **9-11** | Evento sísmico detectable |
| **Sismo grande** | **±1-10** | **±1-10** | **0-20** | Evento sísmico significativo |

### Sección 11: Impresión de Errores

```c
    // Imprime el tipo de error si es que existe
    if (banErrorReloj == 1) {
        switch (fuenteReloj) {
            case 3:
                printf("**Error E3/GPS: No se pudo comprobar la trama GPRS\n");
                break;
            case 4:
                printf("**Error E4/RTC: No se pudo recuperar la trama GPRS\n");
                break;
            case 5:
                printf("**Error E5/RTC: El GPS no responde\n");
                break;
        }
    }
```

**Códigos de error**:

| Código | Mensaje | Significado | Acción recomendada |
|--------|---------|-------------|-------------------|
| E3 | No se pudo comprobar la trama GPRS | Trama GPS recibida pero flag de validez != 'A' | Verificar antena GPS |
| E4 | No se pudo recuperar la trama GPRS | Cabecera GPS incorrecta | Verificar conexión UART GPS |
| E5 | El GPS no responde | Timeout esperando trama GPS (>1.2s) | Verificar alimentación GPS |

**Nota**: El mensaje dice "GPRS" pero debería decir "GPRMC" (trama NMEA).

### Sección 12: Finalización

```c
    fclose(lf);
    free(config);
    return 0;
}
```

---

## Ejemplos de Salida

### Ejemplo 1: Operación Normal con GPS

```
$ comprobar_registro_5.0.0

Tiempo del sistema:
25/01/21 14:32:18

Archivo actual: 'CHA01_250121-143025.dat'
Tamaño del archivo: 627500

Datos de la trama:
| GPS 25/01/21 14:32:17-52337 | X: 0.00125896 Y: -0.00089542 Z: 9.80145623 |
```

**Análisis**:
- ✅ Sistema funcionando correctamente
- ✅ GPS activo y sincronizado
- ✅ Timestamp hace 1 segundo (normal)
- ✅ Z ≈ 9.8 m/s² (sensor en reposo vertical)
- ✅ X, Y ≈ 0 (sin movimiento horizontal)

### Ejemplo 2: Operación con RTC (GPS sin señal)

```
$ comprobar_registro_5.0.0

Tiempo del sistema:
25/01/21 15:45:23

Archivo actual: 'CHA01_250121-143025.dat'
Tamaño del archivo: 5012000

Datos de la trama:
| E5 25/01/21 15:45:22-56722 | X: 0.00089123 Y: -0.00112456 Z: 9.79887654 |
**Error E5/RTC: El GPS no responde
```

**Análisis**:
- ⚠️ GPS no responde
- ✅ Sistema usando RTC como fallback
- ✅ Timestamp hace 1 segundo (RTC funcionando)
- ✅ Aceleraciones normales
- → Acción: Verificar antena GPS, esperar recuperación automática

### Ejemplo 3: Archivo Creciendo Normalmente

```
$ comprobar_registro_5.0.0
...
Tamaño del archivo: 627500

$ sleep 10

$ comprobar_registro_5.0.0
...
Tamaño del archivo: 652560
```

**Cálculo**:
```
Diferencia = 652560 - 627500 = 25060 bytes
Tiempo transcurrido = 10 segundos
Tramas escritas = 25060 / 2506 = 10 tramas

✅ 1 trama por segundo (correcto)
```

### Ejemplo 4: Sistema Detenido

```
$ comprobar_registro_5.0.0

Tiempo del sistema:
25/01/21 16:15:42

Archivo actual: 'CHA01_250121-143025.dat'
Tamaño del archivo: 1253000

Datos de la trama:
| GPS 25/01/21 16:10:35-58235 | X: 0.00145896 Y: -0.00079542 Z: 9.81145623 |

$ sleep 10

$ comprobar_registro_5.0.0
...
Tamaño del archivo: 1253000   ← ¡Sin cambio!
...
| GPS 25/01/21 16:10:35-58235 | ... ← ¡Mismo timestamp!
```

**Análisis**:
- ❌ Archivo no está creciendo
- ❌ Timestamp desactualizado (hace 5 minutos)
- → Acción: Verificar proceso `registro_continuo`

```bash
$ ps aux | grep registro_continuo
# Si no aparece:
$ sudo /usr/local/bin/registrocontinuo start
```

### Ejemplo 5: Sensor Durante Sismo

```
$ comprobar_registro_5.0.0

Tiempo del sistema:
25/01/21 17:23:45

Archivo actual: 'CHA01_250121-143025.dat'
Tamaño del archivo: 3765180

Datos de la trama:
| GPS 25/01/21 17:23:44-62624 | X: 2.45896123 Y: -1.89542876 Z: 11.25145623 |
```

**Análisis**:
- ⚠️ Aceleraciones anormales (X: 2.4 m/s², Y: -1.9 m/s²)
- ⚠️ Z fuera del rango normal (11.25 m/s² vs esperado 9.8)
- → **Posible evento sísmico en curso**
- → Verificar logs de detección de eventos
- → Consultar archivo de eventos detectados

---

## Integración con el Sistema

### Uso en Scripts de Monitoreo

```bash
#!/bin/bash
# Script: monitor_continuo.sh
# Verifica cada 60 segundos si el registro está activo

while true; do
    OUTPUT=$(comprobar_registro_5.0.0 2>&1)

    # Extrae timestamp
    TIMESTAMP=$(echo "$OUTPUT" | grep "Datos de la trama" | awk '{print $5}')

    # Extrae tamaño
    SIZE=$(echo "$OUTPUT" | grep "Tamaño del archivo" | awk '{print $4}')

    echo "$(date '+%Y-%m-%d %H:%M:%S') - Timestamp: $TIMESTAMP, Size: $SIZE"

    # Detecta errores
    if echo "$OUTPUT" | grep -q "Error"; then
        ERROR=$(echo "$OUTPUT" | grep "Error")
        echo "ALERTA: $ERROR"
        # Enviar notificación
    fi

    sleep 60
done
```

### Uso en Crontab

```cron
# Verifica estado cada 5 minutos y guarda en log
*/5 * * * * /home/rsa/ejecutables/comprobar_registro_5.0.0 >> /home/rsa/projects/acelerografo/log-files/verificacion.log 2>&1
```

### Integración con Alertas

```bash
#!/bin/bash
# Script: alerta_registro.sh
# Envía alerta si el timestamp está desactualizado

OUTPUT=$(comprobar_registro_5.0.0 2>&1)

# Extrae timestamp en segundos
TIMESTAMP_SEC=$(echo "$OUTPUT" | grep -oP '(?<=-)[0-9]+')

# Obtiene hora actual en segundos
CURRENT_SEC=$(date '+%H * 3600 + %M * 60 + %S' | bc)

# Calcula diferencia
DIFF=$((CURRENT_SEC - TIMESTAMP_SEC))

if [ $DIFF -gt 60 ]; then
    echo "ALERTA: Registro desactualizado ($DIFF segundos)" | mail -s "Alerta Acelerógrafo" admin@example.com
fi
```

---

## Compilación y Despliegue

### Dependencias

```bash
# Librería JSON (jansson)
sudo apt-get install libjansson-dev

# Librería matemática (libm)
# Ya incluida en el sistema
```

### Comando de Compilación

```bash
gcc -o comprobar_registro_5.0.0 \
    comprobar_registro_5.0.0.c \
    -I./libraries \
    -L./libraries \
    -llector_json \
    -ljansson \
    -lm \
    -O2 \
    -Wall
```

### Instalación

```bash
# Copia ejecutable al directorio de ejecutables
sudo cp comprobar_registro_5.0.0 /usr/local/bin/

# Otorga permisos de ejecución
sudo chmod +x /usr/local/bin/comprobar_registro_5.0.0

# Crea enlace simbólico (opcional)
sudo ln -s /usr/local/bin/comprobar_registro_5.0.0 /usr/local/bin/comprobador
```

### Uso

```bash
# Ejecución directa
comprobar_registro_5.0.0

# O usando el enlace simbólico
comprobador

# Con redirección de salida
comprobar_registro_5.0.0 > estado.txt
```

---

## Análisis de Errores y Problemas Conocidos

### Problema 1: Doble fread() (Líneas 150 y 155)

**Código problemático**:
```c
// Línea 150
fread(tramaDatos, sizeof(char), tramaSize, lf);

// Línea 155 (PROBLEMA)
fread(tramaDatos, sizeof(char), tramaSize, lf);
```

**Análisis**:
- El segundo `fread()` sobrescribe los datos del primero
- Como ya se está al final del archivo, retorna 0 bytes
- `tramaDatos` queda con datos basura o ceros

**Impacto**:
- ⚠️ Puede mostrar valores incorrectos
- ⚠️ Puede mostrar "00/00/00 00:00:00" si el buffer no se inicializó

**Solución**:
```c
// ELIMINAR la línea 155
// fread(tramaDatos, sizeof(char), tramaSize, lf);
```

### Problema 2: Conversión de Aceleración en m/s² vs gales

**Código actual**:
```c
xAceleracion = xValue * (9.8 / pow(2, 18));  // m/s²
```

**Contexto**:
- El sistema usa **gales** (cm/s²) en otros módulos (detector_eventos.c)
- Este programa usa **m/s²**
- Factor de conversión: 1 m/s² = 100 gal

**Implicación**:
- Para comparar con umbrales de detección, convertir:
  ```
  xAceleracion_gal = xAceleracion * 100;
  ```

### Problema 3: No Verifica si el Archivo Tiene al Menos una Trama

**Código problemático**:
```c
long lastFrameIndex = (fileSize / tramaSize) - 1;
```

**Análisis**:
- Si `fileSize < tramaSize`, `lastFrameIndex` es negativo
- `fseek()` con valor negativo puede fallar o comportarse incorrectamente

**Solución recomendada**:
```c
if (fileSize < tramaSize) {
    fprintf(stderr, "Error: Archivo demasiado pequeño (< 2506 bytes)\n");
    fclose(lf);
    free(config);
    return 1;
}

long lastFrameIndex = (fileSize / tramaSize) - 1;
```

### Problema 4: Variable tiempoSegundos Declarada Dos Veces

**Código**:
```c
// Línea 15
unsigned int tiempoSegundos;

// Línea 48
unsigned int tiempoSegundos;  // Duplicado
```

**Análisis**:
- Declaración duplicada (error de compilación en modo estricto)
- Funciona porque los compiladores modernos ignoran esto

**Solución**:
```c
// Eliminar una de las declaraciones (línea 48)
```

---

## Mejoras Potenciales

### Mejora 1: Modo Verbose

```c
int verbose = 0;

if (verbose) {
    printf("Índice de última trama: %ld\n", lastFrameIndex);
    printf("Posición en archivo: %ld bytes\n", lastFrameStart);
    printf("Fuente de reloj (raw): 0x%02X\n", fuenteReloj);
    printf("Timestamp (raw): %02d %02d %02d %02d %02d %02d\n",
           tramaDatos[2500], tramaDatos[2501], tramaDatos[2502],
           tramaDatos[2503], tramaDatos[2504], tramaDatos[2505]);
}
```

### Mejora 2: Opción para Mostrar Múltiples Muestras

```c
// Mostrar las primeras N muestras de la trama
void mostrar_muestras(unsigned char *trama, int num_muestras) {
    for (int i = 0; i < num_muestras; i++) {
        int idx = 1 + i * 10;
        // Extraer y mostrar aceleración
        // ...
    }
}
```

### Mejora 3: Modo JSON para Integración con Scripts

```c
void imprimir_json(/* datos */) {
    printf("{\n");
    printf("  \"timestamp_sistema\": \"%s\",\n", formattedTime);
    printf("  \"archivo\": \"%s\",\n", nombreActualARC);
    printf("  \"tamaño\": %ld,\n", fileSize);
    printf("  \"fuente_reloj\": \"%s\",\n", fuente_str);
    printf("  \"timestamp\": \"%02d/%02d/%02d %02d:%02d:%02d\",\n", ...);
    printf("  \"aceleracion\": {\n");
    printf("    \"x\": %.8f,\n", xAceleracion);
    printf("    \"y\": %.8f,\n", yAceleracion);
    printf("    \"z\": %.8f\n", zAceleracion);
    printf("  }\n");
    printf("}\n");
}
```

### Mejora 4: Comparación con Timestamp del Sistema

```c
// Calcula diferencia en segundos
time_t now = time(NULL);
struct tm *tm_now = localtime(&now);
int sistema_segundos = tm_now->tm_hour * 3600 + tm_now->tm_min * 60 + tm_now->tm_sec;

int diferencia = abs(sistema_segundos - tiempoSegundos);

if (diferencia > 5) {
    printf("⚠️  ADVERTENCIA: Timestamp desactualizado (%d segundos)\n", diferencia);
}
```

### Mejora 5: Verificación de Valores Razonables

```c
// Verifica que Z esté cerca de 9.8 m/s²
double desv_z = fabs(zAceleracion - 9.8);

if (desv_z > 2.0) {
    printf("⚠️  ADVERTENCIA: Z fuera de rango normal (%.2f m/s²)\n", zAceleracion);
    printf("   Esperado: ~9.8 m/s² (sensor en reposo vertical)\n");
}

// Verifica que X e Y sean pequeños (en reposo)
if (fabs(xAceleracion) > 1.0 || fabs(yAceleracion) > 1.0) {
    printf("⚠️  ADVERTENCIA: Aceleración horizontal alta\n");
    printf("   X: %.2f, Y: %.2f m/s²\n", xAceleracion, yAceleracion);
    printf("   Posible movimiento o sismo en curso\n");
}
```

---

## Resumen de Funcionalidad

### Entrada

- **Configuración**: `configuracion_dispositivo.json`
- **Archivo temporal**: `NombreArchivoRegistroContinuo.tmp`
- **Archivo de datos**: `{dir_registro_continuo}/{nombre}.dat`

### Procesamiento

1. Lee configuración desde JSON
2. Identifica archivo actual desde archivo temporal
3. Calcula posición de última trama
4. Lee última trama (2506 bytes)
5. Extrae timestamp (6 bytes finales)
6. Extrae aceleraciones (primera muestra)
7. Convierte de bytes a valores físicos

### Salida

**Formato en consola**:
```
Tiempo del sistema:
25/01/21 14:32:18

Archivo actual: 'CHA01_250121-143025.dat'
Tamaño del archivo: 627500

Datos de la trama:
| GPS 25/01/21 14:32:17-52337 | X: 0.00125896 Y: -0.00089542 Z: 9.80145623 |
```

**Información mostrada**:
- ✅ Hora del sistema (referencia)
- ✅ Nombre del archivo actual
- ✅ Tamaño del archivo (indicador de actividad)
- ✅ Fuente de tiempo (GPS/RTC/RPi)
- ✅ Timestamp de última muestra
- ✅ Aceleraciones en 3 ejes (m/s²)
- ✅ Mensajes de error si aplica

---

## Conclusión

### Fortalezas

1. **Simplicidad**: Programa pequeño (~260 líneas), fácil de entender
2. **Rapidez**: Ejecución instantánea (<100ms)
3. **No invasivo**: Solo lee, no modifica archivos
4. **Información útil**: Muestra datos clave para diagnóstico
5. **Portabilidad**: Usa variable de entorno `PROJECT_LOCAL_ROOT`
6. **Integrable**: Salida parseable por scripts

### Limitaciones

1. **Bug de doble fread()**: Puede mostrar datos incorrectos (línea 155)
2. **Sin validación de tamaño**: No verifica si archivo tiene al menos una trama
3. **Variable duplicada**: `tiempoSegundos` declarada dos veces
4. **Solo primera muestra**: No muestra estadísticas de toda la trama
5. **Sin opciones CLI**: No acepta argumentos (archivo, modo verbose, etc.)
6. **Unidades inconsistentes**: Usa m/s² mientras el resto del sistema usa gales

### Propósito Cumplido

A pesar de sus limitaciones, el programa cumple eficazmente su propósito:
- ✅ Verificación rápida del estado del registro
- ✅ Diagnóstico de problemas temporales
- ✅ Monitoreo de valores de aceleración
- ✅ Detección de archivos estancados

Es una herramienta **simple pero efectiva** para operación y mantenimiento del sistema de acelerografía.

---

**Documento generado para**: Sistema de Acelerografía RSA
**Fecha**: 2025-01-21
**Versión del programa**: 5.0.0
**Mantenido por**: Claude Code Analysis

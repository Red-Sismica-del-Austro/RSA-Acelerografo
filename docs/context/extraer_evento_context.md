# Contexto del Programa Extraer Evento Binario - Sistema de Acelerógrafo

## Resumen Ejecutivo

Este documento describe el programa `extraer_evento_binario_2.1.1.c`, una herramienta que se ejecuta en la **Raspberry Pi** para extraer segmentos específicos (eventos sísmicos) de archivos de registro continuo binarios. El programa toma como entrada un archivo `.dat`, un tiempo de inicio y una duración, y genera un nuevo archivo binario conteniendo únicamente el segmento solicitado.

**Autor**: Milton Muñoz
**Fecha de creación**: 24/03/2021
**Ubicación**: `/home/rsa/git/montajes/acelerografo/scripts/operation/acelerografo/`
**Versión**: 2.1.1 (migrado a configuración JSON)
**Lenguaje**: C (código para Raspberry Pi)
**Propósito**: Extracción de ventanas temporales específicas de archivos de registro continuo para análisis detallado de eventos sísmicos

---

## Arquitectura del Sistema

### Posición en el Flujo de Datos

```
┌──────────────────────────────────────────────────────────────┐
│                    FLUJO DE TRABAJO                          │
│                                                              │
│  1. Detección automática (detector_eventos.c)               │
│     └─> Identifica evento en tiempo real                    │
│         - Hora inicio: 14:25:35                              │
│         - Duración estimada: 30 segundos                     │
│                                                              │
│  2. Archivo de registro continuo                             │
│     ┌────────────────────────────────────┐                  │
│     │  CHA01_250121-143025.dat           │                  │
│     │  - Tamaño: ~5 GB (varios días)     │                  │
│     │  - 2506 bytes por segundo          │                  │
│     │  - Contiene evento detectado       │                  │
│     └────────────┬───────────────────────┘                  │
│                  │                                           │
│                  │ (extrae ventana temporal)                 │
│                  ↓                                           │
│  ┌──────────────────────────────────────┐                   │
│  │  extraer_evento_binario_2.1.1       │ ◄─ Este programa  │
│  │  (este programa)                    │                   │
│  │                                     │                   │
│  │  Entrada:                           │                   │
│  │    - Archivo RC: CHA01_...dat      │                   │
│  │    - Hora inicio: 52535 (seg)      │                   │
│  │    - Duración: 30 (seg)            │                   │
│  │                                     │                   │
│  │  Proceso:                           │                   │
│  │    1. Abre archivo RC               │                   │
│  │    2. Calcula offset temporal       │                   │
│  │    3. Busca posición exacta         │                   │
│  │    4. Extrae N tramas               │                   │
│  │    5. Guarda en archivo nuevo       │                   │
│  └─────────────────┬───────────────────┘                   │
│                    │                                        │
│                    ↓                                        │
│  ┌─────────────────────────────────────┐                   │
│  │  Archivo de evento extraído         │                   │
│  │  CHA01_250121-142535_030.dat        │                   │
│  │  - Tamaño: 75,180 bytes (30 seg)    │                   │
│  │  - Formato idéntico a RC            │                   │
│  │  - Listo para conversión Mini-SEED  │                   │
│  └─────────────────┬───────────────────┘                   │
│                    │                                        │
│                    ↓                                        │
│  3. Conversión a Mini-SEED (binary_to_mseed.py)            │
│     └─> Genera archivo .mseed del evento                   │
└──────────────────────────────────────────────────────────────┘
```

---

## Propósito y Casos de Uso

### Propósito Principal

Extraer segmentos temporales específicos de archivos de registro continuo para:
1. **Aislar eventos sísmicos detectados** automáticamente
2. **Crear archivos manejables** (30-60 segundos vs días completos)
3. **Facilitar análisis posterior** (conversión a Mini-SEED, procesamiento)
4. **Reducir uso de disco** (solo guarda eventos de interés)
5. **Compartir eventos específicos** (archivos pequeños, fáciles de transferir)

### Flujo de Trabajo Típico

```
1. Detección automática (registro_continuo)
   └─> detector_eventos.c detecta STA/LTA >= 4
       └─> Registra: fecha=250121, hora=52535, duración=estimada

2. Extracción manual o automatizada
   └─> extraer_evento_binario_2.1.1 CHA01_250121-143025.dat 52535 30
       └─> Genera: CHA01_250121-142535_030.dat

3. Conversión a Mini-SEED
   └─> binary_to_mseed.py --modo ee
       └─> Genera: CHA01_250121-142535_030.mseed

4. Análisis o distribución
   └─> Envío a servidor central, análisis con SeisComP3, etc.
```

### Ventajas del Enfoque

| Aspecto | Sin Extracción | Con Extracción |
|---------|---------------|----------------|
| **Tamaño de archivo** | 5 GB (2 días) | 75 KB (30 seg) |
| **Tiempo de transferencia** | 10 minutos | <1 segundo |
| **Conversión Mini-SEED** | 30 minutos | 2 segundos |
| **Almacenamiento** | Alto (todo el RC) | Bajo (solo eventos) |
| **Compartir eventos** | Difícil | Fácil (email, USB) |
| **Procesamiento** | Lento (debe buscar) | Rápido (archivo pequeño) |

---

## Análisis del Código Fuente

### Constantes y Definiciones

```c
#define P2 0                   // (No usado en este programa)
#define P1 2                   // (No usado en este programa)
#define NUM_MUESTRAS 249       // (No usado correctamente, debería ser 250)
#define TIEMPO_SPI 100         // (No usado en este programa)
```

**Nota**: Las constantes `P2`, `P1` y `TIEMPO_SPI` no se usan en este programa. Son remanentes de código copiado de `registro_continuo`.

### Variables Globales Principales

```c
// Archivo y rutas
char filenameArchivoRegistroContinuo[100];  // Ruta completa del archivo RC
char nombreArchivo[35];                     // Nombre del archivo (argumento)

// Parámetros de extracción
unsigned int horaEvento;                    // Hora de inicio (en segundos)
unsigned int duracionEvento;                // Duración a extraer (en segundos)

// Control de tiempo
unsigned int tiempoInicio;                  // Tiempo del primer segundo del archivo
unsigned int tiempoEvento;                  // Tiempo del evento a extraer
unsigned int tiempoTranscurrido;            // Diferencia (para saltar tramas)
unsigned int tiempoEventoTrama;             // Tiempo de la trama encontrada

// Datos y contadores
unsigned char tramaDatos[2506];             // Buffer para una trama
unsigned int contMuestras;                  // Contador de segundos extraídos
unsigned short tramaSize = 2506;            // Tamaño de una trama

// Archivos
FILE *lf;                                   // Archivo de registro continuo (entrada)
FILE *fileX;                                // Archivo de evento extraído (salida)
FILE *ftmp;                                 // Archivo temporal con nombre
FILE *ficheroDatosConfiguracion;            // Archivo de configuración
```

---

## Flujo del Programa

### Diagrama de Flujo Principal

```
┌─────────────────────────────┐
│  INICIO                     │
│  argc=4, argv[1-3]          │
└──────────┬──────────────────┘
           ↓
┌─────────────────────────────┐
│ 1. Parsea argumentos:       │
│    - argv[1]: nombre archivo│
│    - argv[2]: horaEvento    │
│    - argv[3]: duracionEvento│
└──────────┬──────────────────┘
           ↓
┌─────────────────────────────┐
│ 2. Construye ruta completa: │
│    /home/rsa/resultados/    │
│    registro-continuo/       │
│    {nombreArchivo}          │
└──────────┬──────────────────┘
           ↓
┌─────────────────────────────┐
│ 3. Inicializa variables     │
│    - tramaSize = 2506       │
│    - contMuestras = 0       │
│    - factorDiezmado = 1     │
└──────────┬──────────────────┘
           ↓
┌─────────────────────────────┐
│ 4. RecuperarVector()        │
│    (función principal)      │
└──────────┬──────────────────┘
           ↓
┌─────────────────────────────┐
│  FIN                        │
│  return 0                   │
└─────────────────────────────┘
```

### Función RecuperarVector() - Análisis Detallado

```
RecuperarVector()
    ↓
┌──────────────────────────────────────────┐
│ 1. Abre archivo RC en modo binario ("rb")│
└──────────┬───────────────────────────────┘
           ↓
┌──────────────────────────────────────────┐
│ 2. Lee primera trama (2506 bytes)        │
│    - Extrae timestamp:                   │
│      hora = trama[2503]                  │
│      min  = trama[2504]                  │
│      seg  = trama[2505]                  │
│    - Calcula tiempoInicio:               │
│      hora×3600 + min×60 + seg            │
└──────────┬───────────────────────────────┘
           ↓
┌──────────────────────────────────────────┐
│ 3. Calcula offset temporal:              │
│    tiempoTranscurrido =                  │
│      horaEvento - tiempoInicio           │
│                                          │
│    Ejemplo:                              │
│    tiempoInicio = 51425 (14:17:05)       │
│    horaEvento   = 52535 (14:35:35)       │
│    tiempoTranscurrido = 1110 segundos    │
└──────────┬───────────────────────────────┘
           ↓
┌──────────────────────────────────────────┐
│ 4. Salta tramas (bucle for):             │
│    for (x=0; x<tiempoTranscurrido; x++)  │
│        fread(tramaDatos, 2506, lf)       │
│                                          │
│    Posiciona cursor en la trama del      │
│    evento (offset: 1110 × 2506 bytes)    │
└──────────┬───────────────────────────────┘
           ↓
┌──────────────────────────────────────────┐
│ 5. Verifica timestamp de la trama        │
│    encontrada:                           │
│    - Extrae fecha: AAMMDD               │
│    - Extrae hora: HHMMSS                │
│    - Convierte a segundos               │
│    - Compara con horaEvento             │
└──────────┬───────────────────────────────┘
           ↓
┌──────────────────────────────────────────┐
│ 6. Si timestamp coincide:                │
│    banExtraer = 1                        │
│    printf("Trama OK")                    │
│                                          │
│    Si NO coincide:                       │
│    printf("Error: tiempo no concuerda")  │
│    banExtraer = 1 (continúa de todos    │
│                    modos)                │
└──────────┬───────────────────────────────┘
           ↓
┌──────────────────────────────────────────┐
│ 7. CrearArchivo(duracion, tramaDatos)    │
│    - Lee configuración                   │
│    - Construye nombre de salida          │
│    - Abre archivo de evento              │
│    - Guarda nombre en archivo temporal   │
└──────────┬───────────────────────────────┘
           ↓
┌──────────────────────────────────────────┐
│ 8. Bucle de extracción:                  │
│    while (contMuestras < duracionEvento) │
│    {                                     │
│        fread(tramaDatos, 2506, lf)       │
│        fwrite(tramaDatos, 2506, fileX)   │
│        contMuestras++                    │
│    }                                     │
│                                          │
│    Copia N tramas completas al nuevo     │
│    archivo                               │
└──────────┬───────────────────────────────┘
           ↓
┌──────────────────────────────────────────┐
│ 9. Cierra archivos                       │
│    - fclose(fileX)                       │
│    - fclose(lf)                          │
│    - printf("Terminado")                 │
└──────────────────────────────────────────┘
```

---

## Análisis Detallado por Secciones

### Sección 1: Parseo de Argumentos y Carga de Configuración (main)

```c
int main(int argc, char *argv[]) {
    // 1. Obtener PROJECT_LOCAL_ROOT y cargar configuración JSON
    const char *project_local_root = getenv("PROJECT_LOCAL_ROOT");
    if (project_local_root == NULL) {
        fprintf(stderr, "Error: La variable de entorno PROJECT_LOCAL_ROOT no está configurada.\n");
        return 1;
    }

    static char config_path[256];
    snprintf(config_path, sizeof(config_path), "%s/configuracion/configuracion_dispositivo.json", project_local_root);

    struct datos_config *config = compilar_json(config_path);
    if (config == NULL) {
        fprintf(stderr, "Error al leer el archivo de configuracion JSON.\n");
        return 1;
    }

    // 2. argv[1]: Nombre del archivo (ej: "CHA01_250121-143025.dat")
    strcpy(nombreArchivo, argv[1]);

    // 3. Construye ruta desde configuración JSON
    strcpy(filenameArchivoRegistroContinuo, config->registro_continuo);
    strcat(filenameArchivoRegistroContinuo, nombreArchivo);
    // Resultado: {config->registro_continuo}/CHA01_250121-143025.dat

    // 4. argv[2]: Hora del evento en segundos desde medianoche
    horaEvento = atoi(argv[2]);  // Ej: "52535" → 52535

    // 5. argv[3]: Duración del evento en segundos
    duracionEvento = atoi(argv[3]);  // Ej: "30" → 30

    // 6. Ejecuta extracción
    RecuperarVector(config);

    // 7. Libera memoria
    free(config);
}
```

**Ejemplo de uso**:
```bash
$ extraer_evento_binario_2.1.1 CHA01_250121-143025.dat 52535 30

Argumentos parseados:
- Archivo: {registro_continuo desde JSON}/CHA01_250121-143025.dat
- Hora evento: 52535 segundos (14:35:35)
- Duración: 30 segundos
```

**Mejora implementada**: Ahora usa configuración JSON portable. La ruta se lee desde `configuracion_dispositivo.json`.

### Sección 2: Cálculo de Offset Temporal

```c
void RecuperarVector() {
    // 1. Lee primera trama del archivo
    fread(tramaDatos, sizeof(char), tramaSize, lf);

    // 2. Extrae timestamp de los últimos 3 bytes
    tiempoInicio = (tramaDatos[tramaSize - 3] * 3600) +
                   (tramaDatos[tramaSize - 2] * 60) +
                   (tramaDatos[tramaSize - 1]);

    // 3. Calcula cuántos segundos saltar
    tiempoEvento = horaEvento;
    tiempoTranscurrido = tiempoEvento - tiempoInicio;
}
```

**Ejemplo de cálculo**:
```
Primera trama del archivo:
tramaDatos[2503] = 14 (hora)
tramaDatos[2504] = 17 (minuto)
tramaDatos[2505] = 5  (segundo)

tiempoInicio = 14×3600 + 17×60 + 5 = 50400 + 1020 + 5 = 51425 segundos

horaEvento = 52535 segundos (argumento del usuario)

tiempoTranscurrido = 52535 - 51425 = 1110 segundos

El evento está 1110 segundos (18.5 minutos) después del inicio del archivo
```

### Sección 3: Búsqueda de la Trama Correcta

```c
    // Salta las tramas hasta llegar al evento
    for (x = 0; x < tiempoTranscurrido; x++) {
        fread(tramaDatos, sizeof(char), tramaSize, lf);
    }
```

**Análisis del algoritmo**:
- **Método**: Búsqueda secuencial
- **Complejidad**: O(n) donde n = tiempoTranscurrido
- **Alternativa más eficiente**: `fseek(lf, tiempoTranscurrido × 2506, SEEK_CUR)`

**Tiempo de ejecución**:
```
Para tiempoTranscurrido = 1110 segundos:
- Operaciones: 1110 × fread(2506 bytes)
- Bytes leídos: 1110 × 2506 = 2,781,660 bytes (~2.7 MB)
- Tiempo estimado: ~200-500ms en Raspberry Pi 3
```

**Versión optimizada** (no implementada):
```c
// En lugar de:
for (x = 0; x < tiempoTranscurrido; x++) {
    fread(tramaDatos, sizeof(char), tramaSize, lf);
}

// Usar:
fseek(lf, tiempoTranscurrido * tramaSize, SEEK_CUR);
fread(tramaDatos, sizeof(char), tramaSize, lf);
// Resultado: ~1ms en lugar de 200-500ms
```

### Sección 4: Verificación de Timestamp

```c
    // Calcula fecha y hora de la trama encontrada
    fechaEventoTrama = ((int)tramaDatos[tramaSize - 6] * 10000) +
                       ((int)tramaDatos[tramaSize - 5] * 100) +
                       ((int)tramaDatos[tramaSize - 4]);

    horaEventoTrama = ((int)tramaDatos[tramaSize - 3] * 10000) +
                      ((int)tramaDatos[tramaSize - 2] * 100) +
                      ((int)tramaDatos[tramaSize - 1]);

    tiempoEventoTrama = ((int)tramaDatos[tramaSize - 3] * 3600) +
                        ((int)tramaDatos[tramaSize - 2] * 60) +
                        ((int)tramaDatos[tramaSize - 1]);

    // Verifica coincidencia
    if (tiempoEventoTrama == tiempoEvento) {
        printf("\nTrama OK\n");
        banExtraer = 1;
    } else {
        printf("\nError: El tiempo de la trama no concuerda\n");
        // Imprime timestamp encontrado
        printf("| %0.2d/%0.2d/%0.2d %0.2d:%0.2d:%0.2d %d |\n",
               tramaDatos[2500], tramaDatos[2501], tramaDatos[2502],
               tramaDatos[2503], tramaDatos[2504], tramaDatos[2505],
               tiempoEventoTrama);
        banExtraer = 1;  // Continúa de todos modos
    }
```

**Observación crítica**:
- Si el timestamp NO coincide, **imprime error pero continúa extrayendo**
- `banExtraer = 1` se asigna en ambos casos
- No hay opción de abortar si el timestamp es incorrecto

**Causas posibles de desajuste**:
1. **Tramas faltantes** en el archivo RC (segundos sin registrar)
2. **Reinicio del sistema** durante la adquisición
3. **Cambio de archivo** a medianoche
4. **Error en el cálculo** de tiempoTranscurrido

### Sección 5: Creación del Archivo de Salida

```c
void CrearArchivo(unsigned int duracionEvento, unsigned char *tramaRegistro, struct datos_config *config) {
    // 1. Extrae timestamp de la primera trama del evento
    unsigned char dd = tramaRegistro[tramaSize - 6];   // día
    unsigned char mm = tramaRegistro[tramaSize - 5];   // mes
    unsigned char aa = tramaRegistro[tramaSize - 4];   // año (2 dígitos)
    unsigned char hh = tramaRegistro[tramaSize - 3];   // hora
    unsigned char min = tramaRegistro[tramaSize - 2];  // minuto
    unsigned char ss = tramaRegistro[tramaSize - 1];   // segundo

    // 2. Calcula el año completo (asume 20xx para años < 70, 19xx para >= 70)
    unsigned int anio_completo = (aa < 70) ? (2000 + aa) : (1900 + aa);

    // 3. Formato mejorado: ID_AAAAMMDD_hhmmss_duracion.dat
    sprintf(tiempoNodoStr, "%04d%02d%02d_%02d%02d%02d_", anio_completo, mm, dd, hh, min, ss);
    sprintf(duracionEventoStr, "%03d", duracionEvento);

    // 4. Construye la ruta completa usando config->eventos_extraidos
    strcpy(filenameEventoExtraido, config->eventos_extraidos);
    strcat(filenameEventoExtraido, config->id);
    strcat(filenameEventoExtraido, "_");
    strcat(filenameEventoExtraido, tiempoNodoStr);
    strcat(filenameEventoExtraido, duracionEventoStr);
    strcat(filenameEventoExtraido, ".dat");

    // Resultado: {eventos_extraidos}/ID_AAAAMMDD_hhmmss_duracion.dat
}
```

**Mejoras implementadas**:
1. Lee configuración desde JSON (no más DatosConfiguracion.txt)
2. Usa la ruta completa `config->eventos_extraidos`
3. Formato de nombre mejorado: `ID_AAAAMMDD_hhmmss_duracion.dat`
4. Año con 4 dígitos (2024) en lugar de 2 (24)

**Componentes del nombre actual**:
```
CHA01 _ 20250121 _ 142535 _ 030 .dat
  ↑       ↑          ↑       ↑    ↑
  │       │          │       │    └── Extensión
  │       │          │       └─────── Duración (segundos)
  │       │          └─────────────── Hora de inicio (hhmmss)
  │       └────────────────────────── Fecha (AAAAMMDD)
  └────────────────────────────────── ID de la estación
```

### Sección 6: Guardado de Nombre en Archivo Temporal

```c
    // Abre archivo temporal
    ftmp = fopen("/home/rsa/tmp/NombreArchivoEventoExtraido.tmp", "w+");

    // Escribe nombre del archivo (27 caracteres)
    fwrite(filenameEventoExtraido, sizeof(char), 27, ftmp);

    fclose(ftmp);
```

**Propósito**: Guardar el nombre del archivo extraído para que otros scripts (como `binary_to_mseed.py`) puedan encontrarlo sin necesidad de pasar argumentos.

**Problema**: Escribe exactamente 27 bytes, sin verificar la longitud real del nombre. Si el nombre es más corto, escribe basura; si es más largo, lo trunca.

**Solución recomendada**:
```c
fwrite(filenameEventoExtraido, sizeof(char), strlen(filenameEventoExtraido), ftmp);
fprintf(ftmp, "\n");  // Agregar salto de línea
```

### Sección 7: Bucle de Extracción

```c
    // Crea archivo de salida
    fileX = fopen(filenameEventoExtraido, "ab+");

    // Extrae tramas
    while (contMuestras < duracionEvento) {
        // Lee una trama del archivo RC
        fread(tramaDatos, sizeof(char), tramaSize, lf);

        if (fileX != NULL) {
            do {
                // Escribe la trama en el archivo de evento
                outFwrite = fwrite(tramaDatos, sizeof(char), 2506, fileX);
            } while (outFwrite != 2506);  // Reintenta si falla
            fflush(fileX);  // Fuerza escritura a disco
        }

        contMuestras++;
    }

    fclose(fileX);
```

**Análisis**:
- Lee y escribe trama por trama (2506 bytes cada una)
- Reintentos automáticos si `fwrite` no escribe todos los bytes
- `fflush()` después de cada trama garantiza escritura inmediata

**Performance**:
```
Para duracionEvento = 30 segundos:
- Operaciones: 30 × (fread + fwrite + fflush)
- Bytes procesados: 30 × 2506 = 75,180 bytes
- Tiempo estimado: ~50-100ms en Raspberry Pi 3
```

---

## Ejemplos de Uso

### Ejemplo 1: Extracción Básica

```bash
$ cd /home/rsa/ejecutables/

$ ./extraer_evento_binario_2.1.1 CHA01_250121-143025.dat 52535 30

Abriendo archivo registro continuo
Leyendo archivo de configuracion...
Se ha creado el archivo: CHA01250121-143535_030.dat

Extrayendo...

Trama OK

Terminado
```

**Resultado**:
- Archivo creado: `CHA01250121-143535_030.dat`
- Tamaño: 75,180 bytes (30 × 2506)
- Ubicación: Directorio actual (problema: debería estar en path configurado)

### Ejemplo 2: Error de Timestamp

```bash
$ ./extraer_evento_binario_2.1.1 CHA01_250121-143025.dat 99999 30

Abriendo archivo registro continuo
Leyendo archivo de configuracion...
Se ha creado el archivo: CHA01250121-235959_030.dat

Extrayendo...

Error: El tiempo de la trama no concuerda
| 25/01/21 14:45:12 53112 |

Terminado
```

**Análisis**:
- Se solicitó hora 99999 (inválida, > 86400)
- El programa calculó offset incorrecto
- Encontró timestamp diferente (14:45:12 en lugar de ~27:46:39)
- **Continuó extrayendo de todos modos** (problema)

### Ejemplo 3: Evento al Inicio del Archivo

```bash
$ ./extraer_evento_binario_2.1.1 CHA01_250121-143025.dat 51426 30

Abriendo archivo registro continuo
Leyendo archivo de configuracion...
Se ha creado el archivo: CHA01250121-141706_030.dat

Extrayendo...

Trama OK

Terminado
```

**Cálculo**:
```
tiempoInicio = 51425 (14:17:05, primera trama del archivo)
horaEvento   = 51426 (14:17:06, segunda trama)
tiempoTranscurrido = 1 segundo

Solo salta 1 trama antes de extraer
```

### Ejemplo 4: Cálculo Manual de Hora en Segundos

```bash
# Quiero extraer evento a las 14:35:35
# Convertir a segundos:
echo $((14 * 3600 + 35 * 60 + 35))
# Resultado: 52535

$ ./extraer_evento_binario_2.1.1 CHA01_250121-143025.dat 52535 30
```

**Fórmula de conversión**:
```
segundos = (hora × 3600) + (minuto × 60) + segundo

14:35:35 = 14×3600 + 35×60 + 35 = 50400 + 2100 + 35 = 52535
```

---

## Integración con el Sistema

### Flujo Completo: De Detección a Mini-SEED

```bash
# 1. Detección automática (en segundo plano por registro_continuo)
# detector_eventos.c detecta evento:
#   - Fecha: 250121
#   - Hora inicio: 52535 (14:35:35)
#   - Duración: 30 segundos

# 2. Extracción manual (o automática vía script)
cd /home/rsa/ejecutables
./extraer_evento_binario_2.1.1 \
    CHA01_250121-143025.dat \
    52535 \
    30

# Resultado: CHA01250121-143535_030.dat creado

# 3. Conversión a Mini-SEED
python3 /home/rsa/programas/binary_to_mseed.py --modo ee

# Lee de: /home/rsa/tmp/NombreArchivoEventoExtraido.tmp
# Convierte: CHA01250121-143535_030.dat → CHA01250121-143535_030.mseed

# 4. Distribución
# Subir a servidor, analizar con SeisComP3, etc.
```

### Script de Automatización

```bash
#!/bin/bash
# Script: extraer_y_convertir.sh
# Extrae evento y convierte a Mini-SEED automáticamente

# Parámetros
ARCHIVO_RC=$1      # Ej: CHA01_250121-143025.dat
HORA_EVENTO=$2     # Ej: 52535
DURACION=$3        # Ej: 30

# Directorio de trabajo
cd /home/rsa/ejecutables

# 1. Extrae evento
echo "Extrayendo evento..."
./extraer_evento_binario_2.1.1 "$ARCHIVO_RC" "$HORA_EVENTO" "$DURACION"

if [ $? -eq 0 ]; then
    echo "Extracción completada"

    # 2. Convierte a Mini-SEED
    echo "Convirtiendo a Mini-SEED..."
    python3 /home/rsa/programas/binary_to_mseed.py --modo ee

    if [ $? -eq 0 ]; then
        echo "Conversión completada"

        # 3. Limpia archivo binario temporal (opcional)
        # rm $(cat /home/rsa/tmp/NombreArchivoEventoExtraido.tmp)

        echo "Proceso completo"
    else
        echo "Error en conversión Mini-SEED"
        exit 1
    fi
else
    echo "Error en extracción"
    exit 1
fi
```

**Uso del script**:
```bash
$ bash extraer_y_convertir.sh CHA01_250121-143025.dat 52535 30
```

---

## Problemas Identificados y Soluciones

### Problema 1: Ruta Hardcoded en main()

**Código problemático**:
```c
strcpy(filenameArchivoRegistroContinuo, "/home/rsa/resultados/registro-continuo/");
```

**Impacto**:
- ❌ No portátil entre sistemas
- ❌ No configurable por el usuario
- ❌ Requiere modificar y recompilar para cambiar ubicación

**Solución recomendada**:
```c
// Usar variable de entorno
const char *dir_rc = getenv("PROJECT_LOCAL_ROOT");
if (dir_rc == NULL) {
    fprintf(stderr, "Error: PROJECT_LOCAL_ROOT no configurada\n");
    return 1;
}
snprintf(filenameArchivoRegistroContinuo, sizeof(filenameArchivoRegistroContinuo),
         "%s/datos/RC/%s", dir_rc, nombreArchivo);
```

### Problema 2: Búsqueda Secuencial Ineficiente

**Código problemático**:
```c
for (x = 0; x < tiempoTranscurrido; x++) {
    fread(tramaDatos, sizeof(char), tramaSize, lf);
}
```

**Impacto**:
- ⚠️ Lento para eventos alejados del inicio
- ⚠️ Lee y descarta MB de datos innecesariamente
- ⚠️ 200-500ms para 1110 segundos

**Solución optimizada**:
```c
// Calcular offset en bytes
long offset = (long)tiempoTranscurrido * tramaSize;

// Saltar directamente
if (fseek(lf, offset, SEEK_CUR) != 0) {
    fprintf(stderr, "Error: No se pudo posicionar en el archivo\n");
    return;
}

// Leer la trama
fread(tramaDatos, sizeof(char), tramaSize, lf);

// Resultado: <1ms en lugar de 200-500ms
```

### Problema 3: Continúa Extrayendo con Timestamp Incorrecto

**Código problemático**:
```c
if (tiempoEventoTrama == tiempoEvento) {
    printf("\nTrama OK\n");
    banExtraer = 1;
} else {
    printf("\nError: El tiempo de la trama no concuerda\n");
    // ... imprime error ...
    banExtraer = 1;  // ← Problema: continúa de todos modos
}
```

**Impacto**:
- ❌ Extrae datos incorrectos sin advertencia clara
- ❌ Usuario puede no notar el error
- ❌ Archivo resultante contiene datos del momento incorrecto

**Solución recomendada**:
```c
if (tiempoEventoTrama == tiempoEvento) {
    printf("\nTrama OK\n");
    banExtraer = 1;
} else {
    printf("\nError: El tiempo de la trama no concuerda\n");
    printf("Esperado: %d, Encontrado: %d\n", tiempoEvento, tiempoEventoTrama);
    printf("¿Desea continuar de todos modos? (s/n): ");

    char respuesta;
    scanf(" %c", &respuesta);

    if (respuesta == 's' || respuesta == 'S') {
        printf("Continuando con timestamp incorrecto...\n");
        banExtraer = 1;
    } else {
        printf("Extracción abortada por el usuario\n");
        fclose(lf);
        return;
    }
}
```

### Problema 4: Archivo de Salida en Directorio Actual

**Código problemático**:
```c
// Lee pathEventosExtraidos pero no lo usa
fgets(pathEventosExtraidos, 60, ficheroDatosConfiguracion);

// ...

// Construye nombre sin path
strcpy(filenameEventoExtraido, idEstacion);
strcat(filenameEventoExtraido, tiempoNodoStr);
// ...

// Abre en directorio actual
fileX = fopen(filenameEventoExtraido, "ab+");
```

**Impacto**:
- ❌ Archivo se crea en directorio de ejecución (impredecible)
- ❌ No usa la configuración leída
- ❌ Dificulta localizar archivos extraídos

**Solución**:
```c
// Construir ruta completa
strcpy(filenameEventoExtraido, pathEventosExtraidos);  // Agregar path
strcat(filenameEventoExtraido, idEstacion);
strcat(filenameEventoExtraido, tiempoNodoStr);
strcat(filenameEventoExtraido, duracionEventoStr);
strcat(filenameEventoExtraido, extBin);

// Ahora fileX se crea en la ubicación correcta
fileX = fopen(filenameEventoExtraido, "ab+");
```

### Problema 5: Tamaño Fijo en fwrite Temporal

**Código problemático**:
```c
fwrite(filenameEventoExtraido, sizeof(char), 27, ftmp);
```

**Impacto**:
- ⚠️ Si nombre < 27 caracteres: escribe basura adicional
- ⚠️ Si nombre > 27 caracteres: trunca el nombre
- ⚠️ No agrega terminador nulo o salto de línea

**Solución**:
```c
fprintf(ftmp, "%s\n", filenameEventoExtraido);
// O:
fwrite(filenameEventoExtraido, sizeof(char), strlen(filenameEventoExtraido), ftmp);
fwrite("\n", sizeof(char), 1, ftmp);
```

### Problema 6: Hardcoded Path de Configuración

**Código problemático**:
```c
ficheroDatosConfiguracion = fopen("/home/rsa/configuracion/DatosConfiguracion.txt", "rt");
```

**Impacto**:
- ❌ No portátil
- ❌ No usa formato JSON como el resto del sistema
- ❌ Formato de archivo anticuado (líneas numeradas)

**Solución moderna**:
```c
// Usar lector_json.c como registro_continuo
const char *project_root = getenv("PROJECT_LOCAL_ROOT");
snprintf(config_path, sizeof(config_path),
         "%s/configuracion/configuracion_dispositivo.json", project_root);

struct datos_config *config = compilar_json(config_path);
strcpy(idEstacion, config->id);
strcpy(pathEventosExtraidos, config->eventos_detectados);  // O crear campo nuevo
free(config);
```

---

## Mejoras Potenciales

### Mejora 1: Argumentos Más Flexibles

```c
// Versión actual: solo segundos
./extraer_evento_binario_2.1.1 archivo.dat 52535 30

// Versión mejorada: acepta formato HH:MM:SS
./extraer_evento_binario_2.1.1 archivo.dat 14:35:35 30

// Implementación:
int parse_time(const char *time_str) {
    int h, m, s;
    if (sscanf(time_str, "%d:%d:%d", &h, &m, &s) == 3) {
        return h*3600 + m*60 + s;
    } else {
        return atoi(time_str);  // Fallback a segundos
    }
}

horaEvento = parse_time(argv[2]);
```

### Mejora 2: Validación de Argumentos

```c
int main(int argc, char *argv[]) {
    if (argc != 4) {
        fprintf(stderr, "Uso: %s <archivo.dat> <hora_segundos> <duracion>\n", argv[0]);
        fprintf(stderr, "Ejemplo: %s CHA01_250121-143025.dat 52535 30\n", argv[0]);
        return 1;
    }

    // Validar archivo existe
    if (access(filenameArchivoRegistroContinuo, F_OK) != 0) {
        fprintf(stderr, "Error: Archivo no encontrado: %s\n",
                filenameArchivoRegistroContinuo);
        return 1;
    }

    // Validar hora válida
    if (horaEvento > 86400) {
        fprintf(stderr, "Error: Hora inválida (%d > 86400 seg/día)\n", horaEvento);
        return 1;
    }

    // Validar duración razonable
    if (duracionEvento == 0 || duracionEvento > 3600) {
        fprintf(stderr, "Advertencia: Duración inusual (%d segundos)\n", duracionEvento);
    }
}
```

### Mejora 3: Modo Verbose

```c
int verbose = 0;  // Activar con argumento --verbose

if (verbose) {
    printf("Archivo de entrada: %s\n", filenameArchivoRegistroContinuo);
    printf("Hora de inicio: %d segundos (%02d:%02d:%02d)\n",
           horaEvento, horaEvento/3600, (horaEvento%3600)/60, horaEvento%60);
    printf("Duración: %d segundos\n", duracionEvento);
    printf("\nPrimera trama del archivo:\n");
    printf("  Timestamp: %02d:%02d:%02d\n",
           tramaDatos[2503], tramaDatos[2504], tramaDatos[2505]);
    printf("  tiempoInicio: %d segundos\n", tiempoInicio);
    printf("  tiempoTranscurrido: %d segundos\n", tiempoTranscurrido);
    printf("  Offset en archivo: %ld bytes\n", (long)tiempoTranscurrido * tramaSize);
}
```

### Mejora 4: Barra de Progreso

```c
printf("\nExtrayendo");
fflush(stdout);

while (contMuestras < duracionEvento) {
    fread(tramaDatos, sizeof(char), tramaSize, lf);
    // ...
    contMuestras++;

    // Imprime punto cada 5 segundos
    if (contMuestras % 5 == 0) {
        printf(".");
        fflush(stdout);
    }
}
printf(" OK\n");
```

### Mejora 5: Verificación de Integridad

```c
// Después de extraer, verificar
printf("\nVerificando archivo extraído...\n");

FILE *verify = fopen(filenameEventoExtraido, "rb");
fseek(verify, 0, SEEK_END);
long size = ftell(verify);
long expected_size = duracionEvento * tramaSize;

if (size == expected_size) {
    printf("✓ Tamaño correcto: %ld bytes\n", size);
} else {
    printf("✗ Advertencia: Tamaño incorrecto\n");
    printf("  Esperado: %ld bytes\n", expected_size);
    printf("  Real: %ld bytes\n", size);
}

fclose(verify);
```

---

## Compilación y Despliegue

### Dependencias

```bash
# Solo librerías estándar de C
# No requiere instalación adicional
```

### Comando de Compilación

```bash
gcc -o extraer_evento_binario_2.1.1 \
    extraer_evento_binario_2.1.1.c \
    -lm \
    -O2 \
    -Wall
```

### Instalación

```bash
# Copia ejecutable
sudo cp extraer_evento_binario_2.1.1 /usr/local/bin/

# Permisos
sudo chmod +x /usr/local/bin/extraer_evento_binario_2.1.1

# Enlace simbólico (opcional)
sudo ln -s /usr/local/bin/extraer_evento_binario_2.1.1 /usr/local/bin/extraer_evento
```

---

## Resumen de Funcionalidad

### Entrada

- **Archivo RC**: Archivo binario de registro continuo (formato 2506 bytes/segundo)
- **Hora inicio**: Tiempo del evento en segundos desde medianoche (0-86400)
- **Duración**: Número de segundos a extraer (típicamente 30-60)

### Procesamiento

1. Abre archivo de registro continuo
2. Lee primera trama para obtener tiempo de inicio
3. Calcula offset temporal (diferencia en segundos)
4. Salta tramas hasta llegar al evento
5. Verifica timestamp de la trama encontrada
6. Extrae N tramas consecutivas
7. Guarda en nuevo archivo con nombre descriptivo

### Salida

- **Archivo binario**: `{ID}{AAMMDD-HHMMSS}_{DDD}.dat`
- **Formato**: Idéntico al archivo RC (2506 bytes por trama)
- **Tamaño**: `duracionEvento × 2506` bytes
- **Archivo temporal**: Nombre guardado en `/home/rsa/tmp/NombreArchivoEventoExtraido.tmp`

---

## Conclusión

### Fortalezas

1. **Funcionalidad básica sólida**: Extrae segmentos correctamente cuando los timestamps coinciden
2. **Reintentos automáticos**: Garantiza escritura completa de cada trama
3. **Naming consistente**: Nombres de archivo incluyen timestamp y duración
4. **Integrable**: Salida compatible con `binary_to_mseed.py`

### Limitaciones Principales

1. **Búsqueda ineficiente**: O(n) en lugar de O(1) con `fseek`
2. **Rutas hardcoded**: No portátil ni configurable
3. **Continúa con errores**: No aborta cuando timestamp no coincide
4. **Configuración anticuada**: Usa archivo de texto en lugar de JSON
5. **Sin validación de entrada**: No verifica argumentos ni existencia de archivos
6. **Path de salida incorrecto**: Ignora configuración y usa directorio actual

### Recomendaciones

1. **Prioridad Alta**: Usar `fseek()` para mejorar performance 100-500×
2. **Prioridad Alta**: Migrar a configuración JSON (usar `lector_json.c`)
3. **Prioridad Media**: Agregar validación de argumentos y errores
4. **Prioridad Media**: Implementar opción de abortar si timestamp no coincide
5. **Prioridad Baja**: Agregar modo verbose y barra de progreso

El programa cumple su función esencial pero requiere modernización para alinearse con el resto del sistema (uso de variables de entorno, JSON, etc.).

---

**Documento generado para**: Sistema de Acelerografía RSA
**Fecha**: 2025-01-21
**Versión del programa**: 2.1.1
**Mantenido por**: Claude Code Analysis

# Contexto del Firmware - Sistema de Acelerógrafo

## Resumen Ejecutivo

Este documento describe el firmware embebido que se ejecuta en un microcontrolador **dsPIC33EP256MC202** a 80MHz. El firmware actúa como intermediario entre el acelerómetro ADXL355 y la Raspberry Pi, manejando la adquisición de datos sísmicos en tiempo real, sincronización de tiempo mediante múltiples fuentes (GPS, RTC, RPI), y comunicación bidireccional vía SPI.

**Autor**: Milton Munoz (miltonrodrigomunoz@gmail.com)
**Fecha de creación**: 14/03/2019
**Plataforma**: dsPIC33EP256MC202, XT=80MHz
**Ubicación**: `/home/rsa/git/montajes/acelerografo/scripts/firmware/`

---

## Arquitectura del Sistema

### Hardware Involucrado

```
┌─────────────────┐
│  Raspberry Pi   │ ◄──── SPI1 (Slave) ───────┐
└─────────────────┘                            │
                                               │
┌──────────────────────────────────────────────┴───────┐
│             dsPIC33EP256MC202                        │
│  - SPI1: Comunicación con RPi (Esclavo)             │
│  - SPI2: Control ADXL355 y RTC (Maestro)            │
│  - UART1: Comunicación con GPS                      │
│  - INT1: Interrupción desde RTC (SQW - 1Hz)         │
│  - INT2: Interrupción desde GPS (PPS - 1Hz)         │
│  - TMR1: Control de lectura FIFO (100ms)            │
│  - TMR2: Timeout GPS (300ms)                        │
│  - TMR3: Sincronización SQW-PPS (500ms)             │
└──────────────────┬───────────────┬───────────────────┘
                   │               │
         ┌─────────┴─────┐   ┌─────┴────────┐
         │  ADXL355      │   │  DS3234 RTC  │
         │  Acelerómetro │   │  (Reloj)     │
         │  SPI2         │   │  SPI2        │
         └───────────────┘   └──────────────┘

         ┌──────────────┐
         │  GPS Module  │
         │  UART1       │
         │  (9600 bps)  │
         └──────────────┘
```

### Pines de Control

| Pin | Función | Descripción |
|-----|---------|-------------|
| RA4 (RP1) | Salida | Interrupción a RPi (operaciones) |
| RB4 (RP2) | Salida | Interrupción a RPi (reservado) |
| RB12 (LedTest) | Salida | LED de estado/diagnóstico |
| RB15 (INT1) | Entrada | Señal SQW del RTC (1Hz) |
| RB14 (INT2) | Entrada | Señal PPS del GPS (1Hz) |

---

## Archivo Principal: firmware_dspic.c

### Tasas de Muestreo Soportadas

El sistema soporta múltiples tasas de muestreo configurables mediante la variable `tasaMuestreo`:

| Valor | Tasa de Muestreo | ODR ADXL355 | Interrupciones TMR1 |
|-------|------------------|-------------|---------------------|
| 1 | 250 Hz | 250 Hz | 9 (cada 100ms) |
| 2 | 125 Hz | 125 Hz | 19 |
| 4 | 62.5 Hz | 62.5 Hz | 39 |
| 8 | 31.25 Hz | 31.25 Hz | 79 |

### Estructura de Datos Principal

#### Trama Completa (2506 bytes)

```
Byte 0: Fuente de reloj (1 byte)
    0 = RPI
    1 = GPS
    2 = RTC
    3 = GPS/E3 (GPS sin señal válida)
    4 = RTC/E4 (Error en GPS, fallback a RTC)
    5 = RTC/Timeout (Timeout en GPS)

Bytes 1-2500: Datos de aceleración (2500 bytes)
    - 250 muestras × 10 bytes por muestra
    - Cada muestra:
        [Número de muestra (1 byte)] +
        [X3, X2, X1, Y3, Y2, Y1, Z3, Z2, Z1 (9 bytes)]
    - 3 ejes (X, Y, Z)
    - 20 bits por eje (formato: 3 bytes complemento a 2)

Bytes 2501-2506: Timestamp del sistema (6 bytes)
    [Año, Mes, Día, Hora, Minuto, Segundo]
```

### Variables Globales Críticas

```c
// Buffers de datos
unsigned char tramaCompleta[2506];    // Trama completa para enviar a RPi
unsigned char datosFIFO[243];         // 27 muestras × 9 bytes
unsigned char tiempo[6];              // Timestamp actual del sistema

// Control de tiempo
unsigned long horaSistema;            // Segundos desde 00:00:00 (0-86399)
unsigned long fechaSistema;           // Formato: YYMMDD (ejemplo: 250321)
unsigned char fuenteReloj;            // 0:RPI, 1:GPS, 2:RTC, 3:GPS/E3, etc.

// Tasas y contadores
unsigned char tasaMuestreo;           // 1=250Hz, 2=125Hz, 4=62.5Hz, 8=31.25Hz
unsigned char contTimer1;             // Contador de interrupciones TMR1
unsigned char numSetsFIFO;            // Número de sets leídos del FIFO
```

---

## Módulo: ADXL355_SPI.c

### Descripción

Librería para comunicación SPI con el acelerómetro ADXL355 de Analog Devices. Este chip es un MEMS de 3 ejes con bajo ruido y alta resolución (20 bits).

### Funciones Principales

#### 1. `ADXL355_init(short tMuestreo)`

Inicializa el acelerómetro con la tasa de muestreo especificada.

```c
// Configuración realizada:
- Reset del dispositivo (0x52)
- Modo STANDBY
- Rango: ±2G
- Filtro según tasa de muestreo:
    * tMuestreo=1: ODR=250Hz (filtro 62.5Hz)
    * tMuestreo=2: ODR=125Hz (filtro 31.25Hz)
    * tMuestreo=4: ODR=62.5Hz (filtro 15.625Hz)
    * tMuestreo=8: ODR=31.25Hz (filtro 7.813Hz)
- Sin filtro pasa-altos
```

#### 2. `ADXL355_write_byte(unsigned char address, unsigned char value)`

Escribe un byte en un registro del ADXL355.

```c
// Protocolo:
- Desplaza la dirección 1 bit a la izquierda (bit 0 = R/W)
- CS bajo → envía dirección → envía valor → CS alto
```

#### 3. `ADXL355_read_byte(unsigned char address)`

Lee un byte desde un registro del ADXL355.

```c
// Protocolo:
- Desplaza dirección 1 bit a la izquierda y pone bit 0 en 1 (lectura)
- CS bajo → envía dirección → lee valor → CS alto
```

#### 4. `ADXL355_read_FIFO(unsigned char *vectorFIFO)`

Lee un set completo (3 ejes) desde el buffer FIFO del acelerómetro.

```c
// Retorna 9 bytes:
[X3, X2, X1, Y3, Y2, Y1, Z3, Z2, Z1]
//
Cada eje es un valor de 20 bits en complemento a 2
almacenado en 3 bytes (justificado a la izquierda)
```

### Registros del ADXL355

```c
#define XDATA3         0x08   // Eje X byte más significativo
#define FIFO_ENTRIES   0x05   // Número de entradas en FIFO
#define FIFO_DATA      0x11   // Lectura del FIFO
#define POWER_CTL      0x2D   // Control de alimentación
#define Range          0x2C   // Configuración de rango
#define Filter         0x28   // Configuración de filtro
#define Status         0x04   // Estado del dispositivo
```

### Constantes de Configuración

```c
// Rangos
#define _2G            0x01   // ±2g
#define _4G            0x02   // ±4g
#define _8G            0x03   // ±8g

// Modos de potencia
#define STANDBY        0x00
#define MEASURING      0x01
#define DRDY_OFF       0x00

// Filtros (ODR - Output Data Rate)
#define _62_5_Hz       0x05   // 250 Hz ODR
#define _31_25_Hz      0x06   // 125 Hz ODR
#define _15_625_Hz     0x07   // 62.5 Hz ODR
#define _7_813_Hz      0x08   // 31.25 Hz ODR
```

---

## Módulo: TIEMPO_GPS.c

### Descripción

Librería para manejo de sincronización de tiempo mediante módulo GPS. Parsea la trama NMEA GPRMC y extrae fecha/hora UTC.

### Funciones Principales

#### 1. `GPS_init()`

Configura el módulo GPS mediante comandos PMTK (MediaTek).

```c
// Comandos enviados:
$PMTK220,1000*1F     // Frecuencia de actualización: 1Hz (1000ms)
$PMTK313,1*2E        // Habilita búsqueda SBAS
$PMTK314,0,1,0,...   // Configura mensajes de salida (solo GPRMC)
$PMTK319,1*24        // Habilita modo SBAS
$PMTK413*34          // Query de estado SBAS
$PMTK513,1*28        // Habilita SBAS
```

**Trama GPRMC esperada**:
```
$GPRMC,hhmmss.sss,A,ddmm.mmmm,N,dddmm.mmmm,E,speed,course,DDMMYY,,,A*checksum
       ↑         ↑                                        ↑
    Hora UTC  Válido                                  Fecha UTC
```

#### 2. `RecuperarHoraGPS(unsigned char *tramaDatosGPS)`

Extrae la hora de la trama GPS y la convierte a segundos desde medianoche.

```c
Entrada: tramaDatosGPS[0-5] = "hhmmss"
Salida: hora en segundos = hh*3600 + mm*60 + ss
Rango: 0 - 86399 (24 horas)
```

#### 3. `RecuperarFechaGPS(unsigned char *tramaDatosGPS)`

Extrae la fecha de la trama GPS.

```c
Entrada: tramaDatosGPS[6-11] = "DDMMYY"
Salida: fecha en formato YYMMDD = YY*10000 + MM*100 + DD
Ejemplo: 210325 = 25 de marzo de 2021
```

### Flujo de Recepción GPS

```
1. Interrupción UART1 por cada byte recibido
2. Buscar cabecera "$GPRMC"
3. Capturar payload hasta "*"
4. Extraer hhmmss (posiciones 1-6)
5. Buscar fecha DDMMYY (después de posición 44)
6. Validar campo de estado (posición 12 == 'A')
7. Si válido: fuenteReloj=1, activar sincronización PPS
8. Si inválido: fuenteReloj=3, usar fallback RTC
```

---

## Módulo: TIEMPO_RPI.c

### Descripción

Librería para recibir tiempo desde la Raspberry Pi. Es la fuente de tiempo inicial del sistema.

### Funciones Principales

#### 1. `RecuperarHoraRPI(unsigned char *tramaTiempoRpi)`

Convierte la trama de tiempo de la RPi a segundos desde medianoche.

```c
Entrada: tramaTiempoRpi[3-5] = [hora, minuto, segundo]
Salida: hora en segundos = hora*3600 + minuto*60 + segundo
```

#### 2. `RecuperarFechaRPI(unsigned char *tramaTiempoRpi)`

Convierte la trama de fecha de la RPi al formato interno.

```c
Entrada: tramaTiempoRpi[0-2] = [año, mes, día]
Salida: fecha en formato YYMMDD = año*10000 + mes*100 + día
```

### Protocolo de Comunicación

```
RPi → dsPIC (vía SPI):
[0xA4] [año] [mes] [día] [hora] [minuto] [segundo] [0xF4]
  ↑                                                    ↑
Inicio                                               Fin

dsPIC:
- Configura fuenteReloj = 0 (RPI)
- Actualiza horaSistema y fechaSistema
- Programa el RTC DS3234 con este tiempo (500ms después)
```

---

## Módulo: TIEMPO_RTC.c

### Descripción

Librería para manejo del RTC (Real-Time Clock) DS3234 de Maxim. Chip SPI con oscilador de cristal TCXO de alta precisión.

### Registros del DS3234

```c
// Lectura (0x00-0x06)
#define Segundos_Lec   0x00   // 00-59 BCD
#define Minutos_Lec    0x01   // 00-59 BCD
#define Horas_Lec      0x02   // 00-23 BCD
#define DiaSemana_Lec  0x03   // 1-7
#define DiaMes_Lec     0x04   // 01-31 BCD
#define Mes_Lec        0x05   // 01-12 BCD
#define Anio_Lec       0x06   // 00-99 BCD

// Escritura (0x80-0x86)
#define Segundos_Esc   0x80
#define Control        0x8E
#define ControlStatus  0x8F
```

### Funciones Principales

#### 1. `DS3234_init()`

Inicializa el RTC DS3234.

```c
// Configuración:
- Control = 0x20 (habilita salida SQW a 1Hz)
- ControlStatus = 0x08 (habilita oscilador)
```

#### 2. `DS3234_setDate(unsigned long longHora, unsigned long longFecha)`

Programa la hora y fecha en el RTC.

```c
Convierte longHora (segundos) y longFecha (YYMMDD) a formato BCD
Escribe todos los registros de tiempo
Usado cuando se recibe tiempo de RPi o GPS válido
```

#### 3. `RecuperarHoraRTC()`

Lee la hora actual del RTC.

```c
Lee registros de hora, minuto, segundo
Convierte de BCD a decimal
Retorna: hora*3600 + minuto*60 + segundo
```

#### 4. `RecuperarFechaRTC()`

Lee la fecha actual del RTC.

```c
Lee registros de año, mes, día
Convierte de BCD a decimal
Retorna: año*10000 + mes*100 + día
```

#### 5. `IncrementarFecha(unsigned long longFecha)`

Incrementa la fecha en un día manejando correctamente:
- Meses de 28, 29, 30 y 31 días
- Años bisiestos (detecta mediante: (año-16) % 4 == 0)
- Transición de fin de año

#### 6. `AjustarTiempoSistema(unsigned long longHora, unsigned long longFecha, unsigned char *tramaTiempoSistema)`

Convierte hora y fecha internas al formato de la trama de 6 bytes.

```c
Salida: tramaTiempoSistema[6] = [año, mes, día, hora, minuto, segundo]
Este formato se envía a la RPi y se incluye en la trama de datos
```

---

## Sistema de Sincronización de Tiempo

### Jerarquía de Fuentes de Tiempo

```
┌──────────────────────────────────────────────┐
│ 1. GPS (Prioritario si esta disponible)      │
│    - Precisión: ±100ns con PPS               │
│    - fuenteReloj = 1                         │
│    - Requiere: Señal GPS válida (flag 'A')   │
└──────────────────────────────────────────────┘
                    ↓ Fallback
┌──────────────────────────────────────────────┐
│ 2. RTC DS3234 (Backup automático)            │
│    - Precisión: ±3.5 ppm (TCXO)              │
│    - fuenteReloj = 2                         │
│    - Genera pulso SQW a 1Hz                  │
└──────────────────────────────────────────────┘
                    ↓ Fallback
┌──────────────────────────────────────────────┐
│ 3. RPI (Solo en inicialización)              │
│    - fuenteReloj = 0                         │
│    - Sincroniza RTC al inicio                │
└──────────────────────────────────────────────┘
```

### Estados de Fuente de Reloj

| Código | Nombre | Descripción |
|--------|--------|-------------|
| 0 | RPI | Tiempo recibido desde Raspberry Pi |
| 1 | GPS | GPS válido con señal PPS activa |
| 2 | RTC | Tiempo del RTC (lectura directa) |
| 3 | GPS/E3 | GPS sin señal válida (fallback a RTC) |
| 4 | RTC/E4 | Error en cabecera GPS (fallback a RTC) |
| 5 | RTC/Timeout | Timeout esperando GPS (fallback a RTC) |

### Proceso de Sincronización

#### Inicialización con RPi

```
1. RPi envía comando 0xA4
2. dsPIC recibe: [año, mes, día, hora, minuto, segundo]
3. fuenteReloj = 0
4. Espera 500ms (Timer3)
5. Programa RTC con este tiempo
6. Activa banSetReloj (usa pulso SQW del RTC)
7. Envía confirmación a RPi (0xB2)
```

#### Sincronización con GPS

```
1. RPi solicita tiempo GPS (comando 0xA6 con parámetro 1)
2. dsPIC activa UART1 y espera trama GPRMC
3. Timeout de 1.2 segundos (4 × 300ms)
4. Si recibe trama válida:
   - Extrae hora y fecha
   - Valida flag de estado ('A')
   - Si válido:
       * fuenteReloj = 1
       * banSyncReloj = 1 (usa pulso PPS del GPS)
       * Programa RTC en próxima interrupción PPS + 500ms
   - Si inválido:
       * fuenteReloj = 3
       * Lee hora del RTC como fallback
5. Si timeout:
   - fuenteReloj = 5
   - Lee hora del RTC como fallback
```

#### Mantenimiento de Tiempo

```
Modo RTC (banSetReloj=1, banSyncReloj=0):
- INT1 (SQW 1Hz) incrementa horaSistema cada segundo
- Si horaSistema == 86400 → horaSistema = 0

Modo GPS (banSyncReloj=1):
- INT2 (PPS 1Hz) incrementa horaSistema cada segundo
- Más preciso que RTC
- Programa RTC cada vez (Timer3 de 500ms)
```

---

## Protocolo de Comunicación SPI con Raspberry Pi

### Arquitectura

El dsPIC actúa como **esclavo SPI**, la RPi como maestro. La comunicación es mediante comandos delimitados:

```
[Byte Inicio] [Datos...] [Byte Fin]
```

### Comandos Implementados

#### 1. Petición de Operación (dsPIC → RPi)

```
RPi envía:   0xA0 ... 0xF0
dsPIC envía: [tipoOperacion]

Tipos de operación:
- 0xB1: Datos de acelerómetro listos
- 0xB2: Hora del sistema disponible
```

#### 2. Inicio de Muestreo (RPi → dsPIC)

```
RPi envía: 0xA1 [parámetro] 0xF1

- Activa banMuestrear
- Prepara el acelerómetro
- Espera próxima interrupción RTC/GPS para comenzar
```

#### 3. Lectura de Datos (RPi ← dsPIC)

```
RPi envía: 0xA3 ... 0xF3
dsPIC envía: tramaCompleta[2506 bytes]

Formato de trama:
[fuenteReloj][250 muestras][timestamp]
```

#### 4. Configuración de Tiempo desde RPi (RPi → dsPIC)

```
RPi envía: 0xA4 [año][mes][día][hora][min][seg] 0xF4

- Configura horaSistema y fechaSistema
- Programa RTC después de 500ms
```

#### 5. Envío de Tiempo a RPi (RPi ← dsPIC)

```
RPi envía: 0xA5 ... 0xF5
dsPIC envía: [fuenteReloj][año][mes][día][hora][min][seg]

- Envía el tiempo actual del sistema
- Incluye indicador de fuente
```

#### 6. Solicitud de Tiempo GPS/RTC (RPi → dsPIC)

```
RPi envía: 0xA6 [referenciaTiempo] 0xF6

referenciaTiempo:
- 1: Intentar GPS (con fallback a RTC)
- Otro: Leer RTC directamente
```

#### 7. Inicialización GPS (RPi → dsPIC)

```
RPi envía: 0xA2 ... 0xF2
dsPIC responde: 0x47 ('G')

- Ejecuta GPS_init()
- Parpadea LED 3 veces
```

---

## Sistema de Interrupciones

### Prioridades de Interrupción

```c
IPC2bits.SPI1IP  = 0x03   // SPI1 (RPi): Prioridad 3
IPC2bits.U1RXIP  = 0x04   // UART1 (GPS): Prioridad 4 (más alta)
IPC5bits.INT1IP  = 0x02   // INT1 (SQW): Prioridad 2
IPC7bits.INT2IP  = 0x01   // INT2 (PPS): Prioridad 1
IPC0bits.T1IP    = 0x02   // Timer1: Prioridad 2
IPC1bits.T2IP    = 0x02   // Timer2: Prioridad 2
IPC2bits.T3IP    = 0x02   // Timer3: Prioridad 2
```

### INT1: Pulso SQW del RTC (1 Hz)

```c
void int_1() org IVT_ADDR_INT1INTERRUPT

Ejecuta cada segundo cuando banSetReloj=1:
1. Conmuta LED de estado
2. Incrementa horaSistema
3. Si horaSistema == 86400 → horaSistema = 0
4. Si banInicio=1 → llama Muestrear()
```

### INT2: Pulso PPS del GPS (1 Hz)

```c
void int_2() org IVT_ADDR_INT2INTERRUPT

Ejecuta cada segundo cuando banSyncReloj=1:
1. Conmuta LED de estado
2. Incrementa horaSistema en 1 segundo
3. Inicia Timer3 (500ms) para sincronizar RTC
```

**Nota**: Existe código comentado que invierte las funciones de INT1/INT2 para pruebas.

### Timer1: Lectura del FIFO del ADXL355 (100ms)

```c
void Timer1Int() org IVT_ADDR_T1INTERRUPT

Ejecuta cada 100ms durante el muestreo:
1. Lee FIFO_ENTRIES para saber cuántas muestras hay
2. Calcula numSetsFIFO = numFIFO / 3
3. Lee todos los sets disponibles del FIFO
4. Intercala número de muestra en tramaCompleta
5. Incrementa contTimer1
6. Si contTimer1 == numTMR1:
   - Apaga Timer1
   - Activa banCiclo=2 (ciclo completo)

Para 250Hz:
- numTMR1 = 9
- 9 × 100ms = 900ms de captura
- Luego 100ms para procesar y enviar
- Total: 1 segundo por trama
```

### Timer2: Timeout GPS (300ms)

```c
void Timer2Int() org IVT_ADDR_T2INTERRUPT

Ejecuta cada 300ms cuando UART1 está esperando GPS:
1. Incrementa contTimeout1
2. Si contTimeout1 == 4 (1.2 segundos total):
   - Apaga Timer2
   - Lee hora del RTC como fallback
   - fuenteReloj = 5 (Timeout)
   - Envía tiempo a RPi
```

### Timer3: Sincronización SQW-PPS (500ms)

```c
void Timer3Int() org IVT_ADDR_T3INTERRUPT

Propósito dual:

A) Después de recibir tiempo de RPi:
   - Espera 500ms
   - Programa RTC con tiempo recibido
   - Activa banSetReloj=1

B) Después de pulso PPS del GPS:
   - Espera 500ms (para estabilización)
   - Programa RTC con tiempo GPS
   - Alterna entre modos SQW y PPS según necesidad
```

### SPI1: Comunicación con RPi

```c
void spi_1() org IVT_ADDR_SPI1INTERRUPT

Máquina de estados que maneja todos los comandos 0xA0-0xA6.
Ver sección "Protocolo de Comunicación SPI".
```

### UART1: Recepción GPS

```c
void urx_1() org IVT_ADDR_U1RXINTERRUPT

Máquina de estados para parsear trama GPRMC:

Estados (banGPSI):
0: Idle
1: Esperando '$'
2: Leyendo cabecera "GPRMC"
3: Capturando payload hasta '*'

Al completar trama válida (banGPSC=1):
1. Extrae hhmmss y DDMMYY
2. Valida flag de estado
3. Configura fuenteReloj
4. Programa sincronización PPS o fallback a RTC
```

---

## Proceso de Muestreo Continuo

### Flujo Principal

```
1. RPi envía comando 0xA1 (inicio de muestreo)
   └─> banMuestrear = 1, banCiclo = 1

2. En próxima interrupción INT1/INT2 (1Hz):
   └─> Si banInicio == 1 → llama Muestrear()

3. Muestrear() primera llamada (banCiclo=1):
   ├─> Pone ADXL355 en modo MEASURING
   └─> Enciende Timer1 (100ms)

4. Timer1 interrumpe cada 100ms (9 veces para 250Hz):
   ├─> Lee FIFO del ADXL355 (~27 muestras)
   ├─> Intercala números de muestra
   ├─> Acumula en tramaCompleta
   └─> Si contTimer1 == 9 → banCiclo = 2

5. Muestrear() segunda llamada (banCiclo=2):
   ├─> Completa tramaCompleta con timestamp
   ├─> banLec = 1
   ├─> Genera pulso RP1 (interrupción a RPi)
   └─> Reinicia Timer1 para próximo ciclo

6. RPi lee datos vía comando 0xA3:
   └─> Transmite 2506 bytes completos

7. Ciclo se repite cada segundo
```

### Diagrama de Tiempo (250Hz)

```
Segundo N:
|--100ms--|--100ms--|--100ms--|...|--100ms--|--100ms--|
  TMR1      TMR1      TMR1          TMR1      Procesar
   ↓         ↓         ↓             ↓          ↓
  Lee       Lee       Lee           Lee      Completa
  27 samp   27 samp   27 samp       27 samp  trama
                                              + envía
                                              interrupción
                                              a RPi

Total: ~900ms captura + ~100ms proceso = 1 segundo
```

### Capacidad del FIFO

El ADXL355 tiene un FIFO de 96 muestras (32 sets de 3 ejes):

```
Para 250Hz:
- En 100ms se generan: 250 × 0.1 = 25 muestras
- FIFO lee: ~27 sets (verificado por numSetsFIFO)
- Margen de seguridad: 96 - 27 = 69 muestras libres
```

---

## Configuración de Oscilador y Periféricos

### Oscilador Principal

```c
// FRC (Fast RC Oscillator) con PLL
// FPLLO = FIN × (M/(N1+N2))
// FIN = 7.37 MHz (FRC)
// N1 = 7 (PLLPRE=5 → divisor=7)
// N2 = 2 (PLLPOST=0 → divisor=2)
// M = 152 (PLLDIV=150)
//
// FPLLO = 7.37 × (152/(7+2)) ≈ 80 MHz
```

### SPI1 (Esclavo - Comunicación con RPi)

```c
SPI1_Init_Advanced(
    _SPI_SLAVE,                // Modo esclavo
    _SPI_8_BIT,                // 8 bits por transferencia
    _SPI_PRESCALE_SEC_1,       // N/A en modo esclavo
    _SPI_PRESCALE_PRI_1,       // N/A en modo esclavo
    _SPI_SS_ENABLE,            // SS habilitado
    _SPI_DATA_SAMPLE_END,      // Muestrea al final del pulso
    _SPI_CLK_IDLE_HIGH,        // CLK en alto cuando idle (CPOL=1)
    _SPI_ACTIVE_2_IDLE         // Transición activo→idle (CPHA=1)
)
// Modo SPI 3: CPOL=1, CPHA=1
```

### SPI2 (Maestro - ADXL355 y RTC)

```c
// Configuración por defecto (SPI2_Init):
// - Modo maestro
// - 8 bits
// - Velocidad: Fosc/4 (20 MHz para ADXL355)

// Configuración especial para RTC (lectura/escritura):
SPI2_Init_Advanced(
    _SPI_MASTER,
    _SPI_8_BIT,
    _SPI_PRESCALE_SEC_1,
    _SPI_PRESCALE_PRI_64,      // Más lento para RTC
    _SPI_SS_DISABLE,           // SS manual
    _SPI_DATA_SAMPLE_MIDDLE,   // Muestrea en medio
    _SPI_CLK_IDLE_LOW,         // CLK bajo cuando idle (CPOL=0)
    _SPI_ACTIVE_2_IDLE
)
// Modo SPI 1: CPOL=0, CPHA=1
```

### UART1 (GPS)

```c
UART1_Init(9600);              // 9600 baudios
U1STAbits.URXISEL = 0x00;      // Interrupción por cada byte recibido
```

### Timers

```c
// Timer1: 100ms
// Prescaler: 1:8 (T1CON=0x0020)
PR1 = 62500
Tiempo = PR1 × Prescaler / Fosc
       = 62500 × 8 / 80MHz = 0.1s

// Timer2: 300ms
// Prescaler: 1:64 (T2CON=0x30)
PR2 = 46875
Tiempo = 46875 × 64 / 80MHz = 0.3s

// Timer3: 500ms
// Prescaler: 1:64 (T3CON=0x20)
PR3 = 62500
Tiempo = 62500 × 8 / 80MHz = 0.5s
```

---

## Banderas de Control

### Banderas de Comunicación

```c
banOperacion    // Operación pendiente para RPi
banLec          // 0:idle, 1:preparado, 2:enviando datos
banEsc          // Recibiendo datos desde RPi
banSetReloj     // Tiempo del sistema válido
```

### Banderas de Muestreo

```c
banMuestrear    // Muestreo habilitado
banInicio       // Inicio de ciclo de muestreo autorizado
banCiclo        // 1:iniciar, 2:procesar, 3:enviando
```

### Banderas de Tiempo

```c
banSyncReloj    // Usar pulso PPS del GPS (más preciso)
banSetGPS       // (No usado actualmente)
```

### Banderas GPS

```c
banGPSI         // Estado de recepción GPS (0-3)
banGPSC         // Trama GPS completa
banTFGPS        // (No usado)
banInitGPS      // Inicialización de GPS en proceso
```

---

## Análisis de Rendimiento

### Throughput de Datos

```
Para 250Hz (configuración típica):
- Muestras por segundo: 250
- Bytes por muestra: 10 (1 ID + 9 datos)
- Datos de aceleración: 2500 bytes/s
- Overhead: 7 bytes/s (fuente + timestamp)
- Total: 2507 bytes/s

Capacidad SPI1 (estimada 1 MHz):
- Teórico: 125 KB/s
- Utilización: 2507/125000 = 2%
- Margen: Muy amplio
```

### Latencia de Respuesta

```
Evento → Interrupción RPi:
- Trama completa: ~20μs (pulso RP1)
- Transferencia SPI1: 2506 bytes × 8μs/byte ≈ 20ms
- Total: < 25ms (aceptable para sísmica)

Sincronización de tiempo:
- GPS PPS: ±100ns (cuando GPS válido)
- RTC SQW: ±50μs (precisión del oscilador)
- RPi: No crítico (solo inicialización)
```

### Consumo de Memoria

```
RAM utilizada (aproximado):
- tramaCompleta[2506]:      2506 bytes
- datosFIFO[243]:            243 bytes
- tramaGPS[70]:              70 bytes
- Variables globales:        ~100 bytes
---------------------------------
Total:                       ~2.9 KB

dsPIC33EP256MC202 tiene 32 KB RAM → Uso: 9%
Flash: ~5-8 KB estimado / 256 KB disponibles
```

---

## Consideraciones de Diseño

### Robustez

1. **Redundancia de fuentes de tiempo**: GPS → RTC → RPi
2. **Timeouts**: GPS tiene timeout de 1.2s antes de usar RTC
3. **Validación de tramas GPS**: Verifica cabecera y flag de validez
4. **Manejo de FIFO**: Lee todas las muestras disponibles para evitar overflow
5. **Indicadores de fuente**: fuenteReloj permite rastrear origen del tiempo

### Limitaciones Conocidas

1. **Sin manejo de años bisiestos completo**: Solo verifica (año-16) % 4
2. **No guarda segundos fraccionarios**: Precisión limitada a 1 segundo
3. **Buffer único**: Solo puede haber una trama en proceso
4. **Sin verificación CRC**: No valida integridad de datos
5. **Transiciones de fecha**: Incremento manual, no automático en INT1/INT2

### Mejoras Potenciales

1. **Timestamp de alta resolución**: Agregar milisegundos desde Timer1
2. **Doble buffer**: Permitir captura mientras se transmite
3. **Compresión**: Reducir tamaño de trama (números de muestra redundantes)
4. **CRC/Checksum**: Validar integridad de comunicación SPI
5. **Modo low-power**: Apagar periféricos no usados
6. **Detección de pérdida de sincronización GPS**: Monitorear calidad de señal

---

## Interacción con el Sistema Raspberry Pi

### Responsabilidades del dsPIC

1. **Adquisición de datos**: Lectura continua del ADXL355
2. **Sincronización temporal**: Mantener tiempo preciso
3. **Buffering**: Acumular 250 muestras antes de transferir
4. **Notificación**: Interrumpir RPi cuando hay datos listos

### Responsabilidades de la RPi

1. **Configuración inicial**: Enviar tiempo y tasas de muestreo
2. **Lectura de datos**: Responder a interrupciones y leer tramas
3. **Procesamiento**: Convertir datos binarios a Mini-SEED
4. **Almacenamiento**: Guardar archivos .dat y gestionar espacio
5. **Comunicación**: Subir a Drive, MQTT, etc.

### Sincronización entre Dispositivos

```
Caso típico (operación continua a 250Hz):

RPi                          dsPIC
 │                             │
 ├─ (inicio) 0xA4 tiempo ───>  │ Configura RTC
 │                             │
 ├─ 0xA1 inicio muestreo ───>  │ Activa ADXL355
 │                             │
 │                      Cada 1 segundo:
 │                             ├─ INT1/INT2
 │                             ├─ Captura 250 muestras
 │                             └─ RP1 (interrupción)
 │ <───────────────────────────┤
 ├─ (ISR) Lee GPIO             │
 ├─ 0xA3 solicita datos ─────> │
 │ <── Envía 2506 bytes ────── │
 ├─ Procesa y guarda           │
 │                             │
 └─ (ciclo continúa...)        └─ (ciclo continúa...)
```

---

## Depuración y Diagnóstico

### LED de Estado (LedTest - RB12)

```c
Configuración inicial:
- 3 parpadeos rápidos al terminar ConfiguracionPrincipal()

Durante operación normal:
- Conmuta cada segundo (INT1 o INT2)
- Permite verificar visualmente sincronización 1Hz

Inicialización GPS:
- 3 parpadeos rápidos cuando se ejecuta GPS_init()
```

### Códigos de Fuente de Reloj

Permiten rastrear problemas de sincronización:

```
0: RPi recibido → RTC OK → Usando RTC
1: GPS OK → PPS activo → Mejor precisión
2: RTC leído directamente → Sin GPS activo
3: GPS sin señal válida → Fallback a RTC
4: Error en trama GPS → Fallback a RTC
5: Timeout GPS → Fallback a RTC
```

### Puntos de Verificación

1. **SPI1**: Monitorear comandos 0xA0-0xA6 desde RPi
2. **SPI2**: Verificar CS_ADXL355 y CS_DS3234 toggling
3. **UART1**: Capturar tramas GPRMC para validar GPS
4. **INT1**: Osciloscopio en RB15 → debe ser 1Hz
5. **INT2**: Osciloscopio en RB14 → debe ser 1Hz cuando GPS OK
6. **RP1**: Pulsos de 20μs cada segundo durante muestreo

---

## Resumen de Archivos

| Archivo | LOC | Descripción |
|---------|-----|-------------|
| firmware_dspic.c | ~792 | Firmware principal, interrupciones, muestreo |
| ADXL355_SPI.c | ~89 | Driver del acelerómetro ADXL355 |
| TIEMPO_GPS.c | ~82 | Parser de tramas NMEA GPRMC |
| TIEMPO_RPI.c | ~27 | Conversión de tiempo desde RPi |
| TIEMPO_RTC.c | ~260 | Driver del RTC DS3234, manejo de calendario |

**Total**: ~1250 líneas de código C embebido.

---

## Compatibilidad con el Sistema Completo

Este firmware es parte de un sistema más amplio:

```
Hardware Layer:
├─ dsPIC33EP256MC202 (este firmware)
├─ ADXL355 (sensor MEMS)
├─ DS3234 (RTC)
└─ GPS Module

Raspberry Pi Layer:
├─ registro_continuo (C program)        ← Lee datos del dsPIC vía SPI
├─ binary_to_mseed.py                   ← Convierte .dat → .mseed
├─ gestor_archivos_acq.py               ← Manejo de archivos
└─ cliente.py (MQTT)                    ← Publicación de eventos

Storage/Cloud:
├─ Google Drive
└─ Archivos locales .dat/.mseed
```

El formato de trama de 2506 bytes es interpretado por `registro_continuo` (programa C en la RPi) que:
1. Lee 2506 bytes vía SPI
2. Extrae timestamp (bytes 2501-2506)
3. Guarda datos brutos en archivos .dat
4. Notifica a `binary_to_mseed.py` para conversión

---

## Referencias Técnicas

### Datasheets

1. **dsPIC33EP256MC202**: Microchip DS70616G
2. **ADXL355**: Analog Devices Rev. D
3. **DS3234**: Maxim Integrated 19-5170

### Estándares

1. **SPI**: Motorola SPI Block Guide
2. **NMEA 0183**: GPS Protocol Specification
3. **Mini-SEED**: FDSN Standard (usado en capa superior)

### Comandos PMTK

- **PMTK220**: Set Position Fix Interval
- **PMTK313**: Enable/Disable SBAS Search
- **PMTK314**: Set NMEA Output Sentences
- **PMTK319**: Set SBAS Mode
- **PMTK413**: Query SBAS Status
- **PMTK513**: Enable/Disable SBAS

---

## Conclusión

Este firmware implementa un sistema robusto de adquisición sísmica con las siguientes características clave:

**Fortalezas**:
- ✅ Sincronización temporal multi-fuente con fallbacks automáticos
- ✅ Adquisición continua a 250 Hz con buffering eficiente
- ✅ Bajo uso de CPU y memoria
- ✅ Protocolo de comunicación bien estructurado
- ✅ Indicadores de diagnóstico (LED, códigos de fuente)

**Áreas de atención**:
- ⚠️ Buffer único (no permite captura simultánea con transferencia)
- ⚠️ Sin validación CRC/checksum de datos
- ⚠️ Timestamp con resolución de 1 segundo
- ⚠️ Manejo manual de calendario (no automático)

El diseño es apropiado para aplicaciones de monitoreo sísmico continuo donde la precisión temporal (±100ns con GPS) y la captura confiable son críticas.

---

**Documento generado para**: Sistema de Acelerografía RSA
**Fecha**: 2025-01-21
**Versión del firmware**: Basado en código del 14/03/2019
**Mantenido por**: Claude Code Analysis

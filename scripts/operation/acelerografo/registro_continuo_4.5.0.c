
// Para manejo del tiempo
#define _XOPEN_SOURCE // Debe ir en la primera linea
#include <time.h>
#include <sys/time.h>

#include <fcntl.h>
#include <sys/stat.h>
#include <signal.h>
#include <stdbool.h>

#include <stdio.h>
#include <stdlib.h>
#include <wiringPi.h>
#include <bcm2835.h>
#include <string.h>
#include <unistd.h>
#include <errno.h>

#define PIPE_NAME "/tmp/my_pipe"

// Incluye las librerias de deteccion de eventos y de lectura del archivo json
#include "lector_json.h"
#include "detector_eventos.h"

// Declaracion de constantes
#define P2 2
#define P1 0
#define MCLR 28    // Pin 38
#define LedTest 26 // Pin 32
#define NUM_MUESTRAS 199
#define NUM_ELEMENTOS 2506
#define TIEMPO_SPI 10
#define NUM_CICLOS 1
#define FreqSPI 2000000



// Declaracion de variables
unsigned short i;
unsigned int x;
unsigned short buffer;
unsigned short banFile;
unsigned short banNewFile;
unsigned short numBytes;
unsigned short contMuestras;
unsigned char tiempoPIC[8];
unsigned char tiempoLocal[8];
unsigned char tramaDatos[NUM_ELEMENTOS];

// Variables para crear los archivos de datos:
char filenameTemporalRegistroContinuo[100];

char comando[40];
char dateGPS[22];
unsigned int timeNewFile[2] = {0, 0}; // Variable para configurar la hora a la que se desea generar un archivo nuevo (hh, mm)
unsigned short confGPS[2] = {0, 1};   // Parametros que se pasan para configurar el GPS (conf, NMA) cuando conf=1 realiza la configuracion del GPS y se realiza una sola vez la primera vez que es utilizado
unsigned short banNewFile;

unsigned short contCiclos;
unsigned short contador;

// Variables para control de tiempo:
int fuenteTiempo;
unsigned short fuenteTiempoPic;
unsigned short banTiempoRed, banTiempoRTC;
char datePICStr[20];
char datePicUNIX[15];
char dateRedUNIX[15];
struct tm datePIC;
// struct tm dateRed;
long tiempoPicUNIX, tiempoRedUNIX, deltaUNIX;

// Variables para extraer los datos de configuracion:
char id[10];
char deteccion_eventos[10];
char publicacion_eventos[10];

// Variables para crear los archivos de datos:
char temporalRegistroContinuo[35];
char archivoEventoDetectado[35];
char archivoActualRegistroContinuo[35];

// Variavle para mensajes log 
char mensaje_log[256];

FILE *fp;
FILE *ftmp;
FILE *fTramaTmp;
FILE *ficheroDatosConfiguracion;
FILE *obj_fp;

const char *config_filename;

// Metodo para manejar el tiempo del sistema
int ComprobarNTP();

// Metodos para la comunicacion con el dsPIC
int ConfiguracionPrincipal();
void write_log(const char *type, const char *message);
void handle_sigpipe(int sig);
void LeerArchivoConfiguracion();
void CrearArchivos();
void GuardarVector(unsigned char *tramaD);
void ObtenerOperacion();                      // C:0xA0    F:0xF0
void IniciarMuestreo();                       // C:0xA1	F:0xF1
void DetenerMuestreo();                       // C:0xA2	F:0xF2
void NuevoCiclo();                            // C:0xA3	F:0xF3
void EnviarTiempoLocal();                     // C:0xA4	F:0xF4
void ObtenerTiempoPIC();                      // C:0xA5	F:0xF5
void ObtenerReferenciaTiempo(int referencia); // C:0xA6	F:0xF6
void SetRelojLocal(unsigned char *tramaTiempo);


// Declaración global
struct datos_config *datos_configuracion;

int main(void)
{

    printf("\n\nPROGRAMA INICIADO: registro_continuo\n");
    write_log("INFO", "PROGRAMA INICIADO: registro_continuo");

    // Inicializa las variables:
    i = 0;
    x = 0;
    contMuestras = 0;
    banFile = 0;
    banNewFile = 0;
    numBytes = 0;
    contCiclos = 0;
    contador = 0;

    banTiempoRed = 0;
    banTiempoRTC = 0;

    
    // Realiza la configuracion principal:
    ConfiguracionPrincipal();

    // Comprueba si el equipo esta sincronizado con el tiempo de red:
    banTiempoRed = ComprobarNTP();

    // Inicializa la variable config_filename considerando la variable de entorno de la raiz del proyecto
    const char *project_local_root = getenv("PROJECT_LOCAL_ROOT");
    if (project_local_root == NULL) {
        fprintf(stderr, "Error: La variable de entorno PROJECT_LOCAL_ROOT no está configurada.\n");
        write_log("ERROR", "La variable de entorno PROJECT_LOCAL_ROOT no está configurada");
        write_log("ERROR", "PROGRAMA FINALIZADO: registro_continuo");
        return 1;
    }
    static char config_path[256];
    snprintf(config_path, sizeof(config_path), "%s/configuracion/configuracion_dispositivo.json", project_local_root);
    config_filename = config_path;

    // Lee el archivo de configuracion en formato json
    printf("\nLeyendo archivo de configuracion...\n");
    struct datos_config *datos_configuracion = compilar_json(config_filename);
    if (datos_configuracion == NULL) {
        fprintf(stderr, "Error al leer el archivo de configuracion JSON.\n");
        write_log("ERROR", "Error al leer el archivo de configuracion JSON");
        write_log("ERROR", "PROGRAMA FINALIZADO: registro_continuo");
        return 1;
    }

    // Imprime el id del dispositivo
    printf("ID: %s\n", datos_configuracion->id);
        
    // Obtiene la referencia de tiempo | 0:RPi 1:GPS 2:RTC
    int fuente_reloj = atoi(datos_configuracion->fuente_reloj); 
    if (fuente_reloj == 0 || fuente_reloj == 1 || fuente_reloj == 2)
    {
        ObtenerReferenciaTiempo(fuente_reloj);
        printf("Fuente de reloj: %s\n", datos_configuracion->fuente_reloj);
        // Guarda en el archivo log la referencia de tiempo recuperada
        snprintf(mensaje_log, sizeof(mensaje_log), "Fuente de reloj: %s", datos_configuracion->fuente_reloj);
        write_log("INFO", mensaje_log);
    }
    else
    {
        fprintf(stderr, "Advertencia: No se pudo recuperar la fuente de reloj. Revise el archivo de configuracion.\n");
        write_log("WARNING", "No se pudo leer la configuracion de fuente de reloj");
        // Establece la hora de red como referencia de tiempo predeterminada
        ObtenerReferenciaTiempo(0);
    }

    // Comprueba la configuracion de deteccion de eventos 
    strncpy(deteccion_eventos, datos_configuracion->deteccion_eventos, sizeof(deteccion_eventos) - 1);
    deteccion_eventos[sizeof(deteccion_eventos) - 1] = '\0'; // Asegurar la terminación nula
    if ((strcmp(deteccion_eventos, "si") == 0) || (strcmp(deteccion_eventos, "no") == 0))
    {
        printf("Deteccion de eventos: %s\n", datos_configuracion->deteccion_eventos);
        // Guarda en el archivo log los datos de configuracion recuperados del archivo JSON
        snprintf(mensaje_log, sizeof(mensaje_log), "Deteccion de eventos: %s", datos_configuracion->deteccion_eventos);
        write_log("INFO", mensaje_log);
        // Si la deteccion de eventos esta activa inicializa el filtro FIR
        if (strcmp(deteccion_eventos, "si") == 0)
        {
            firFloatInit();
        } 
    } 
    else
    {
        fprintf(stderr, "Advertencia: No se pudo leer la configuracion de deteccion de eventos. Revise el archivo de configuracion.\n");
        write_log("WARNING", "No se pudo leer la configuracion de deteccion de eventos");
    }
        
    // Liberar la memoria del struct datos_config
    free(datos_configuracion);

    // Configurar el manejador de SIGPIPE
    signal(SIGPIPE, handle_sigpipe);

    // Crear el named pipe
    if (mkfifo(PIPE_NAME, 0666) == -1) {
        if (errno != EEXIST) {
            perror("Error al crear el PIPE");
            write_log("ERROR", "Error al crear el pipe");
            write_log("ERROR", "PROGRAMA FINALIZADO: registro_continuo");
            exit(1);
        } 
        else 
        {
        // El pipe ya existe, no es un error crítico
        write_log("INFO", "Estado del pipe: Existente");
        } 
    }
    else
    {
        write_log("INFO", "Estado del pipe: Creado con exito");
    } 

    // Bucle infinito
    while (1)
    {
        //delay(10);
        __asm__("nop");  // Instrucción "no operation" para evitar optimización excesiva
    }

    bcm2835_spi_end();
    bcm2835_close();

    return 0;
}

int ConfiguracionPrincipal()
{

    // Reinicia el modulo SPI
    system("sudo rmmod  spi_bcm2835");
    // bcm2835_delayMicroseconds(500);
    system("sudo modprobe spi_bcm2835");

    // Configuracion libreria bcm2835:
    if (!bcm2835_init())
    {
        printf("bcm2835_init fallo. Ejecuto el programa como root?\n");
        return 1;
    }
    if (!bcm2835_spi_begin())
    {
        printf("bcm2835_spi_begin fallo. Ejecuto el programa como root?\n");
        return 1;
    }

    bcm2835_spi_setBitOrder(BCM2835_SPI_BIT_ORDER_MSBFIRST);
    bcm2835_spi_setDataMode(BCM2835_SPI_MODE3);
    // bcm2835_spi_setClockDivider(BCM2835_SPI_CLOCK_DIVIDER_32);					//Clock divider RPi 2
    bcm2835_spi_setClockDivider(BCM2835_SPI_CLOCK_DIVIDER_64); // Clock divider RPi 3
    bcm2835_spi_set_speed_hz(FreqSPI);
    bcm2835_spi_chipSelect(BCM2835_SPI_CS0);
    bcm2835_spi_setChipSelectPolarity(BCM2835_SPI_CS0, LOW);

    // Configuracion libreria WiringPi:
    wiringPiSetup();
    pinMode(P1, INPUT);
    pinMode(MCLR, OUTPUT);
    pinMode(LedTest, OUTPUT);
    wiringPiISR(P1, INT_EDGE_RISING, ObtenerOperacion);

    // Enciende el pin LedTest
    digitalWrite(LedTest, HIGH);

    printf("\n****************************************\n");
    printf("Configuracion completa\n");
    printf("****************************************\n");
}

void write_log(const char *type, const char *message) 
{
    // Define el archivo de log
    const char *log_file = "/home/rsa/projects/acelerografo/log-files/registro_continuo.log";

    // Abre el archivo en modo append
    FILE *fp_log = fopen(log_file, "a");
    if (fp_log == NULL) {
        fprintf(stderr, "Error: No se pudo abrir el archivo de log: %s\n", log_file);
        return;
    }

    // Obtiene la fecha y hora actual
    time_t t = time(NULL);
    struct tm *tm = localtime(&t);

    // Formatea la fecha y hora
    char timestamp[30];
    strftime(timestamp, sizeof(timestamp), "%Y-%m-%d %H:%M:%S", tm);

    // Escribe el mensaje en el archivo de log
    fprintf(fp_log, "%s - %s - %s\n", timestamp, type, message);

    // Cierra el archivo
    fclose(fp_log);
}

void handle_sigpipe(int sig) {
    printf("SIGPIPE caught. Reader probably disconnected.\n");
}

int ComprobarNTP()
{
    char str1[5];
    const char *str2 = "yes";
    int v;

    printf("****************************************\n");
    printf("Comprobando conexion con servidor NTP...\n");
    // system("timedatectl | grep System | tail -c4");
    FILE *ftimedate = popen("timedatectl | grep System | tail -c4", "r");
    fscanf(ftimedate, "%s", str1);
    printf("System clock synchronized: %s\n", str1);
    pclose(ftimedate);

    // Comprueba si System clock synchronized == yes
    v = strcmp(str1, str2);
    if (v == 0)
    {
        system("date");
        time_t now;
        struct tm *lt;
        now = time(NULL);
        lt = localtime(&now);
        lt->tm_year;
        lt->tm_mon;
        lt->tm_mday;
        lt->tm_hour;
        lt->tm_min;
        lt->tm_sec;
        time_t midnight = mktime(lt);
        tiempoRedUNIX = (long)midnight;
        printf("Tiempo UNIX red: %d\n", tiempoRedUNIX);
        printf("****************************************\n");
        return 1;
    }
    else
    {
        return 2;
        printf("****************************************\n");
    }
}


void CrearArchivos()
{
    
    char dir_registro_continuo[100];
    char dir_eventos_detectados[100];
    char dir_archivos_temporales[100];

    char extBin[5];
    char extTxt[5];
    char extTmp[5];
    char nombreActualARC[25];
    char nombreAnteriorARC[26];
    char timestamp[35];

    char filenameArchivoRegistroContinuo[100];
    char filenameEventosDetectados[100];
    char filenameActualRegistroContinuo[100];
    
    
    printf("\nLeyendo archivo de configuracion...\n");

    // Abre y lee el archivo de configuración JSON
    struct datos_config *config = compilar_json(config_filename);
    if (config == NULL) {
        fprintf(stderr, "Error al leer el archivo de configuracion JSON.\n");
        return;
    }

    // Asignar los valores leídos del archivo JSON a las variables correspondientes
    strncpy(id, config->id, sizeof(id) - 1);
    strncpy(dir_archivos_temporales, config->archivos_temporales, sizeof(dir_archivos_temporales) - 1);
    strncpy(dir_registro_continuo, config->registro_continuo, sizeof(dir_registro_continuo) - 1);
    strncpy(dir_eventos_detectados, config->eventos_detectados, sizeof(dir_eventos_detectados) - 1);
    id[sizeof(id) - 1] = '\0';  // Asegurar la terminación nula
    dir_archivos_temporales[sizeof(dir_archivos_temporales) - 1] = '\0';
    dir_registro_continuo[sizeof(dir_registro_continuo) - 1] = '\0';
    dir_eventos_detectados[sizeof(dir_eventos_detectados) - 1] = '\0';

    // Asigna el texto correspondiente a los array de caracteres
    strcpy(extBin, ".dat");
    strcpy(extTxt, ".txt");
    strcpy(extTmp, ".tmp");

    // Se crean los archivos necesarios para almacenar los datos:
    printf("\nSe crearon los archivos:\n");

    // Obtiene la hora y la fecha del sistema:
    time_t t;
    struct tm *tm;
    t = time(NULL);
    tm = localtime(&t);

    // Crea el archivo binario para los datos de registro continuo:
    strftime(timestamp, sizeof(timestamp), "%y%m%d-%H%M%S", tm);
    snprintf(filenameArchivoRegistroContinuo, sizeof(filenameArchivoRegistroContinuo), "%s%s_%s%s", dir_registro_continuo, id, timestamp, extBin);
    printf("   %s\n", filenameArchivoRegistroContinuo);
    fp = fopen(filenameArchivoRegistroContinuo, "ab+");
    if (fp == NULL) {
        fprintf(stderr, "Error al crear el archivo de registro continuo.\n");
        free(config); // Liberar memoria en caso de error
        return;
    }

    // Crea el archivo temporal para los datos de registro continuo:
    snprintf(filenameTemporalRegistroContinuo, sizeof(filenameTemporalRegistroContinuo), "%sTramaTemporal%s", dir_archivos_temporales, extTmp);

    // Crea el archivo de texto para guardar los eventos detectados:
    snprintf(filenameEventosDetectados, sizeof(filenameEventosDetectados), "%s%s_EventosDetectados%s",dir_eventos_detectados, id, extTxt);
    printf("   %s\n", filenameEventosDetectados);
    obj_fp = fopen(filenameEventosDetectados, "a");
    if (obj_fp == NULL) {
        fprintf(stderr, "Error al crear el archivo de eventos detectados.\n");
        fclose(fp); // Cerrar archivo abierto
        free(config); // Liberar memoria en caso de error
        return;
    }
    printf("   %s\n", filenameEventosDetectados);

    // Crea el archivo temporal para guardar los nombres actual y anterior de los archivos RC:
    snprintf(filenameActualRegistroContinuo, sizeof(filenameActualRegistroContinuo), "%sNombreArchivoRegistroContinuo%s", dir_archivos_temporales, extTmp);
    printf("   %s\n", filenameActualRegistroContinuo);
    ftmp = fopen(filenameActualRegistroContinuo, "rt");
    if (ftmp == NULL) {
        fprintf(stderr, "Error al abrir el archivo temporal para nombres de archivos RC.\n");
        fclose(fp); // Cerrar archivo abierto
        fclose(obj_fp); // Cerrar archivo abierto
        free(config); // Liberar memoria en caso de error
        return;
    }
    fgets(nombreAnteriorARC, sizeof(nombreAnteriorARC), ftmp);
    fclose(ftmp);

    ftmp = fopen(filenameActualRegistroContinuo, "w+");
    if (ftmp == NULL) {
        fprintf(stderr, "Error al abrir el archivo temporal para escritura de nombres de archivos RC.\n");
        fclose(fp); // Cerrar archivo abierto
        fclose(obj_fp); // Cerrar archivo abierto
        free(config); // Liberar memoria en caso de error
        return;
    }

    snprintf(nombreActualARC, sizeof(nombreActualARC), "%s_%s%s\n", id, timestamp, extBin);

    fwrite(nombreActualARC, sizeof(char), strlen(nombreActualARC), ftmp);
    fwrite(nombreAnteriorARC, sizeof(char), strlen(nombreAnteriorARC), ftmp);

    printf("\nArchivo RC Actual: %s", nombreActualARC);
    printf("Archivo RC Anterior: %s\n\n", nombreAnteriorARC);

    fclose(ftmp);

    // Liberar la memoria del struct datos_config
    free(config);
}



//**************************************************************************************************************************************
// Comunicacion RPi-dsPIC:

// C:0xA0	F:0xF0
void ObtenerOperacion()
{
    // bcm2835_delayMicroseconds(200);

    digitalWrite(LedTest, !digitalRead(LedTest));

    bcm2835_spi_transfer(0xA0);
    bcm2835_delayMicroseconds(TIEMPO_SPI);
    buffer = bcm2835_spi_transfer(0x00);
    bcm2835_delayMicroseconds(TIEMPO_SPI);
    bcm2835_spi_transfer(0xF0);
    // bcm2835_delayMicroseconds(TIEMPO_SPI);
    //   printf("%X \n", buffer);

    delay(1);

    // Aqui se selecciona el tipo de operacion que se va a ejecutar
    if (buffer == 0xB1)
    {
        // printf("Interrupcion P1: 0xB1\n");
        NuevoCiclo();
    }
    if (buffer == 0xB2)
    {
        printf("Interrupcion P1: 0xB2\n");
        printf("****************************************\n");
        ObtenerTiempoPIC();
    }
}

// C:0xA1	F:0xF1
void IniciarMuestreo()
{
    printf("\nIniciando el muestreo...\n");
    bcm2835_spi_transfer(0xA1);
    bcm2835_delayMicroseconds(TIEMPO_SPI);
    bcm2835_spi_transfer(0x01);
    bcm2835_delayMicroseconds(TIEMPO_SPI);
    bcm2835_spi_transfer(0xF1);
    bcm2835_delayMicroseconds(TIEMPO_SPI);
}

// C:0xA3	F:0xF3
void NuevoCiclo()
{
    // printf("Nuevo ciclo\n");
    bcm2835_spi_transfer(0xA3); // Envia el delimitador de inicio de trama
    bcm2835_delayMicroseconds(TIEMPO_SPI);

    for (i = 0; i < 2506; i++)
    {
        buffer = bcm2835_spi_transfer(0x00); // Envia 2506 dummy bytes para recuperar los datos de la trama enviada desde el dsPIC
        tramaDatos[i] = buffer;              // Guarda los datos en el vector tramaDatos
        bcm2835_delayMicroseconds(TIEMPO_SPI);
    }

    bcm2835_spi_transfer(0xF3); // Envia el delimitador de final de trama
    bcm2835_delayMicroseconds(TIEMPO_SPI);

    GuardarVector(tramaDatos); // Guarda la el vector tramaDatos en el archivo binario
    // CrearArchivos();           //Crea un archivo nuevo si se cumplen las condiciones

    // Llama al metodo para determinar si existe o no un evento sismico:
    if (strcmp(deteccion_eventos, "si") == 0){
        DetectarEvento(tramaDatos);
    }
    
}

// C:0xA4	F:0xF4
void EnviarTiempoLocal()
{
    time_t t;
    struct tm *tm;
    int ban_segundo_inicio = 0; // Bandera para controlar el bucle
    int segundo_anterior = -1;  // Inicializa para detectar el cambio de segundos

    printf("Esperando inicio de segundo...\n");

    // Espera en el bucle hasta que el segundo actual sea 0
    while (ban_segundo_inicio == 0)
    {

        // Obtiene la hora y la fecha del sistema:
        time(&t);
        tm = localtime(&t);
        int segundo_actual = tm->tm_sec;

        // Envía la trama de tiempo al detectarse un cambio de segundo
        if (segundo_actual == 0 || (segundo_actual % 2 == 0))
        {
            printf("Enviando tiempo local: ");
            tiempoLocal[0] = tm->tm_year - 100; // Anio (contado desde 1900)
            tiempoLocal[1] = tm->tm_mon + 1;    // Mes desde Enero (0-11)
            tiempoLocal[2] = tm->tm_mday;       // Dia del mes (0-31)
            tiempoLocal[3] = tm->tm_hour;       // Hora
            tiempoLocal[4] = tm->tm_min;        // Minuto
            tiempoLocal[5] = segundo_actual;    // Segundo
            printf("%0.2d:", tiempoLocal[3]);   // hh
            printf("%0.2d:", tiempoLocal[4]);   // mm
            printf("%0.2d ", tiempoLocal[5]);   // ss
            printf("%0.2d/", tiempoLocal[0]);   // AA
            printf("%0.2d/", tiempoLocal[1]);   // MM
            printf("%0.2d\n", tiempoLocal[2]);  // DD
            printf("****************************************\n");

            // Envia la trama de tiempo a través de SPI
            bcm2835_spi_transfer(0xA4); // Envia el delimitador de inicio de trama
            bcm2835_delayMicroseconds(TIEMPO_SPI);
            for (int i = 0; i < 6; i++)
            {
                bcm2835_spi_transfer(tiempoLocal[i]); // Envia los 6 datos de la trama tiempoLocal al dsPIC
                bcm2835_delayMicroseconds(TIEMPO_SPI);
            }
            bcm2835_spi_transfer(0xF4); // Envia el delimitador de final de trama
            bcm2835_delayMicroseconds(TIEMPO_SPI);

            ban_segundo_inicio = 1; // Actualiza la bandera para salir del bucle
        }

        // Espera 1000us (1ms) antes de verificar nuevamente
        bcm2835_delayMicroseconds(1000);
    }
}

// C:0xA5	F:0xF5
void ObtenerTiempoPIC()
{

    printf("Hora dsPIC: ");
    bcm2835_spi_transfer(0xA5); // Envia el delimitador de final de trama
    bcm2835_delayMicroseconds(TIEMPO_SPI);

    fuenteTiempoPic = bcm2835_spi_transfer(0x00); // Recibe el byte que indica la fuente de tiempo del PIC
    bcm2835_delayMicroseconds(TIEMPO_SPI);

    for (i = 0; i < 6; i++)
    {
        buffer = bcm2835_spi_transfer(0x00);
        tiempoPIC[i] = buffer; // Guarda la hora y fecha devuelta por el dsPIC
        bcm2835_delayMicroseconds(TIEMPO_SPI);
    }

    bcm2835_spi_transfer(0xF5); // Envia el delimitador de final de trama
    bcm2835_delayMicroseconds(TIEMPO_SPI);

    sprintf(datePICStr, "%0.2d:%0.2d:%0.2d %0.2d/%0.2d/%0.2d", tiempoPIC[3], tiempoPIC[4], tiempoPIC[5], tiempoPIC[0], tiempoPIC[1], tiempoPIC[2]);

    switch (fuenteTiempoPic)
    {
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
        printf("E%d ", fuenteTiempoPic);
        break;
    }

    // Imprime la trama de tiempo del dsPIC:
    printf("%s\n", datePICStr);

    // Imprime el tipo de error si es que existe:
    if (fuenteTiempoPic == 3 || fuenteTiempoPic == 4 || fuenteTiempoPic == 5)
    {
        switch (fuenteTiempoPic)
        {
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

    // Calcula el tiempo UNIX de la trama de tiempo recibida del dsPIC
    strptime(datePICStr, "%H:%M:%S %y/%m/%d", &datePIC);        // Convierte el tiempo en string a struct
    strftime(datePicUNIX, sizeof(datePicUNIX), "%s", &datePIC); //%s: The number of seconds since the Epoch, 1970-01-01 00:00:00
    tiempoPicUNIX = atoi(datePicUNIX);
    printf("Tiempo UNIX dsPIC: %d\n", tiempoPicUNIX);
    printf("****************************************\n");

    CrearArchivos();
    IniciarMuestreo();
}

// C:0xA6	F:0xF6
void ObtenerReferenciaTiempo(int referencia)
{
    // referencia = 0 -> RPi
    // referencia = 1 -> GPS
    // referencia = 2 -> RTC
    if (referencia == 0)
    {
        EnviarTiempoLocal();
    }
    else
    {
        if (referencia == 1)
        {
            printf("Obteniendo hora del GPS...\n");
        }
        else
        {
            printf("Obteniendo hora del RTC...\n");
        }
        printf("****************************************\n");
        bcm2835_spi_transfer(0xA6);
        bcm2835_delayMicroseconds(TIEMPO_SPI);
        bcm2835_spi_transfer(referencia);
        bcm2835_delayMicroseconds(TIEMPO_SPI);
        bcm2835_spi_transfer(0xF6);
        bcm2835_delayMicroseconds(TIEMPO_SPI);
    }
}
//**************************************************************************************************************************************



// Esta funcion sirve para guardar en el archivo binario las tramas de 1 segundo recibidas
void GuardarVector(unsigned char *tramaD) {
    
    // Guardar la trama en el archivo de registro continuo
    if (fp != NULL) {
        size_t outFwrite;
        do {
            outFwrite = fwrite(tramaD, sizeof(char), NUM_ELEMENTOS, fp);
        } while (outFwrite != NUM_ELEMENTOS);
        fflush(fp);
    }
    
    // Escribir en el pipe
    int fd;
    //printf("Abriendo pipe para escritura...\n");
    fd = open(PIPE_NAME, O_WRONLY | O_NONBLOCK);
    
    if (fd == -1) {
        if (errno == ENXIO) {
            //printf("No hay lector. No se puede escribir.\n");
            return;
        } else {
            //perror("Error al abrir el pipe");
            return;
        }
    }
    //printf("Escribiendo datos...\n");
    ssize_t bytes_written = write(fd, tramaD, NUM_ELEMENTOS);
    if (bytes_written == -1) {
        if (errno == EPIPE) {
            //printf("El lector se desconectó.\n");
        } else {
            //perror("Error al escribir en el pipe");
        }
    } else {
        //printf("Escritos %zd bytes\n", bytes_written);
    }
    close(fd);

}


void SetRelojLocal(unsigned char *tramaTiempo)
{
    printf("Configurando hora de Red con la hora RTC...\n");
    char datePIC[22];
    // Configura el reloj interno de la RPi con la hora recuperada del PIC:
    strcpy(comando, "sudo date --set "); // strcpy( <variable_destino>, <cadena_fuente> )
    // Ejemplo: '2019-09-13 17:45:00':
    datePIC[0] = 0x27; //'
    datePIC[1] = '2';
    datePIC[2] = '0';
    datePIC[3] = (tramaTiempo[0] / 10) + 48; // dd
    datePIC[4] = (tramaTiempo[0] % 10) + 48;
    datePIC[5] = '-';
    datePIC[6] = (tramaTiempo[1] / 10) + 48; // MM
    datePIC[7] = (tramaTiempo[1] % 10) + 48;
    datePIC[8] = '-';
    datePIC[9] = (tramaTiempo[2] / 10) + 48;  // aa: (19/10)+48 = 49 = '1'
    datePIC[10] = (tramaTiempo[2] % 10) + 48; //    (19%10)+48 = 57 = '9'
    datePIC[11] = ' ';
    datePIC[12] = (tramaTiempo[3] / 10) + 48; // hh
    datePIC[13] = (tramaTiempo[3] % 10) + 48;
    datePIC[14] = ':';
    datePIC[15] = (tramaTiempo[4] / 10) + 48; // mm
    datePIC[16] = (tramaTiempo[4] % 10) + 48;
    datePIC[17] = ':';
    datePIC[18] = (tramaTiempo[5] / 10) + 48; // ss
    datePIC[19] = (tramaTiempo[5] % 10) + 48;
    datePIC[20] = 0x27;
    datePIC[21] = '\0';

    strcat(comando, datePIC);

    system(comando);
    system("date");
}

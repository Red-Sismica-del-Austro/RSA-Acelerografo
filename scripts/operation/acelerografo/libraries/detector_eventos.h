// miArchivo.h
#ifndef MI_ARCHIVO_H
#define MI_ARCHIVO_H

#define NUM_ELEMENTOS 2506

// Define los parametros del metodo STA/LTA en segundos multiplicado por la frecuencia de muestreo
#define fSample 250
#define n_STA 125   // 0.5 segundos * fSample
#define n_LTA 12500 // 50 segundos *fSample
#define valTrigger 4
#define valDetrigger 2
// Tiempos en segundos para agregar antes y despues de la deteccion de un evento
#define timePreEvent 2
#define timePostEvent 2
#define ventanaEvento 30
// Se considera un tiempo extra entre eventos, de esta forma si ocurren dos eventos cercanos
// se envia uno solo
#define timeEntreEventos 60

// Define los parametros del filtro FIR
// Maximo numero de datos de entrada en una llamada a la funcion
// Permite filtrar al mismo tiempo hasta este numero de muestras
#define MAX_INPUT_LEN 80
// Maxima longitud del filtro, maximo numero de coeficientes que permite
#define MAX_FLT_LEN 64
// Dimension para almacenar las muestras de entrada
#define BUFFER_LEN (MAX_FLT_LEN - 1 + MAX_INPUT_LEN)
// Coeficientes para un filtro FIR pasa alto de frecuencia 1Hz con ventana Kaiser de orden 63 que da 64 coeficientes, beta = 5
// La frecuencia de muestreo es 250 Hz y se utilizo la herramienta fdatool Matlab (Se llama con filterDesigner)
#define FILTER_LEN 64

// DEFINICION DE VARIABLES GLOBALES
// Vector para almacenar las muestras de entrada
extern double vectorMuestras[BUFFER_LEN];
// Coeficientes para un filtro FIR pasa alto de frecuencia 1Hz con ventana Kaiser de orden 63 que da 64 coeficientes, beta = 5
// La frecuencia de muestreo es 250 Hz y se utilizo la herramienta fdatool Matlab (Se llama con filterDesigner)
extern double coeficientes[FILTER_LEN];
// Variable con la ruta y el nombre del archivo temporal para guardar la informacion de cada evento detectado
// Se guarda solo la fecha long, la hora en segundos del inicio del evento y su duracion
// Con cada evento nuevo se sobreescribe la informacion, antes se debe leer en el programa de Python
// static char *fileNameEventosDetectados = "/home/rsa/TMP/EventosDetectados.tmp";

extern FILE *obj_fp;

// DECLARACION DE FUNCIONES
// Metodos para detectar automaticamente los eventos sismicos:
void DetectarEvento(unsigned char *tramaD);
float ObtenerValorAceleracion(char byte1, char byte2, char byte3);
float calcular_STA_recursivo(float numRecibido);
float calcular_LTA_recursivo(float numRecibido);
float calcularRelacion_LTA_STA(float valSTA, float valLTA);
char calcularIsEvento(float resul_STA_LTA);
void firFloatInit(void);
float calcular_Salida_Filtro(double *coeficientes, double valEntrada, int filterLength);
void ExtraerEvento(char *nombreArchivoRegistro, unsigned int tiempoEvento, unsigned int duracionEvento);

#endif // MI_ARCHIVO_H
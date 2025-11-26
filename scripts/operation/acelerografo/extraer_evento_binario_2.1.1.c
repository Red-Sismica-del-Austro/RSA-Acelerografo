// Autor: Milton Muñoz
// Fecha: 24/03/2021

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <math.h>
#include "libraries/lector_json.h"

// Declaracion de constantes
#define P2 0
#define P1 2
#define NUM_MUESTRAS 249
#define TIEMPO_SPI 100

// Declaracion de variables
unsigned short i, k;
signed short j;
unsigned short contEje;
unsigned int x;
unsigned short banGuardar;
unsigned int contMuestras;
unsigned int numCiclos;
unsigned int tiempoInicial;
unsigned int factorDiezmado;
unsigned long periodoMuestreo;
unsigned char tramaInSPI[20];
unsigned char tramaDatos[16 + (NUM_MUESTRAS * 10)];
unsigned short axisData[3];
int axisValue;
double aceleracion, acelX, acelY, acelZ;
unsigned short tiempoSPI;
unsigned short tramaSize;
char rutaEntrada[35];
char rutaSalidaInfo[30];
char rutaSalidaX[30];
char rutaSalidaY[30];
char rutaSalidaZ[30];
char ext1[8];
char ext2[8];
char ext3[8];
char nombreArchivo[35];
char nombreArchivoEvento[35];
char nombreRed[8];
char nombreEstacion[8];
char ejeX[3];
char ejeY[3];
char ejeZ[3];
char filenameArchivoRegistroContinuo[100];

unsigned int outFwrite;

unsigned int duracionEvento;
unsigned int horaEvento;
unsigned int tiempoInicio;
unsigned int tiempoEvento;
unsigned int tiempoTranscurrido;
unsigned int fechaEventoTrama;
unsigned int horaEventoTrama;
unsigned int tiempoEventoTrama;
int tiempo;

unsigned short banExtraer;
unsigned char opcionExtraer;

double offLong, offTran, offVert;

FILE *lf;
FILE *ftmp;
FILE *fileInfo;
FILE *fileX;
FILE *fileY;
FILE *fileZ;

// Declaracion de funciones
void RecuperarVector(struct datos_config *config);
void CrearArchivo(unsigned int duracionEvento, unsigned char *tramaRegistro, struct datos_config *config);

int main(int argc, char *argv[])
{
	////////////////////////////////////////////////////////////////////////////////////////////////////////////////
	// Obtener PROJECT_LOCAL_ROOT y cargar configuración JSON
	////////////////////////////////////////////////////////////////////////////////////////////////////////////////
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
	////////////////////////////////////////////////////////////////////////////////////////////////////////////////

	////////////////////////////////////////////////////////////////////////////////////////////////////////////////
	// Ingreso de datos
	////////////////////////////////////////////////////////////////////////////////////////////////////////////////
	strcpy(nombreArchivo, argv[1]);
	strcpy(filenameArchivoRegistroContinuo, config->registro_continuo);
	strcat(filenameArchivoRegistroContinuo, nombreArchivo);

	horaEvento = atoi(argv[2]);
	duracionEvento = atoi(argv[3]);
	////////////////////////////////////////////////////////////////////////////////////////////////////////////////

	i = 0;
	x = 0;
	j = 0;
	k = 0;

	factorDiezmado = 1;
	banGuardar = 0;
	periodoMuestreo = 4;

	axisValue = 0;
	aceleracion = 0.0;
	acelX = 0.0;
	acelY = 0.0;
	acelZ = 0.0;
	contMuestras = 0;
	tramaSize = 16 + (NUM_MUESTRAS * 10); // 16+(249*10) = 2506

	// Constantes offset:
	offLong = 0;
	offTran = 0;
	offVert = 0;

	banExtraer = 0;

	RecuperarVector(config);

	// Liberar memoria de la configuración
	free(config);

	// Comando para ejecutar el script de Python
	//const char *comandoPython = "sudo python3 /home/rsa/programas/ConversorMseed.py 2";
	//system(comandoPython);

	return 0;
}

void RecuperarVector(struct datos_config *config)
{
	int ajusteTiempo = 0;

	////////////////////////////////////////////////////////////////////////////////////////////////////////////////
	// Abre el archivo binario en modo lectura:
	printf("Abriendo archivo registro continuo");
	lf = fopen(filenameArchivoRegistroContinuo, "rb");
	////////////////////////////////////////////////////////////////////////////////////////////////////////////////

	////////////////////////////////////////////////////////////////////////////////////////////////////////////////
	// Obtiene y calcula los tiempos de inicio del muestreo
	////////////////////////////////////////////////////////////////////////////////////////////////////////////////
	fread(tramaDatos, sizeof(char), tramaSize, lf);
	tiempoInicio = (tramaDatos[tramaSize - 3] * 3600) + (tramaDatos[tramaSize - 2] * 60) + (tramaDatos[tramaSize - 1]);
	// tiempoEvento = ((horaEvento/10000)*3600)+(((horaEvento%10000)/100)*60)+(horaEvento%100);
	tiempoEvento = horaEvento;
	tiempoTranscurrido = tiempoEvento - tiempoInicio;
	// printf("%d",tiempoEvento);
	////////////////////////////////////////////////////////////////////////////////////////////////////////////////

	////////////////////////////////////////////////////////////////////////////////////////////////////////////////
	// Comprueba el estado de la trama de datos para continuar con el proceso
	////////////////////////////////////////////////////////////////////////////////////////////////////////////////
	// Se salta el numero de segundos que indique la variable tiempoTranscurrido:
	for (x = 0; x < (tiempoTranscurrido); x++)
	{
		fread(tramaDatos, sizeof(char), tramaSize, lf);
	}
	// Calcula la fecha de la trama recuperada en formato aammdd:
	fechaEventoTrama = ((int)tramaDatos[tramaSize - 6] * 10000) + ((int)tramaDatos[tramaSize - 5] * 100) + ((int)tramaDatos[tramaSize - 4]);
	// Calcula la hora de la trama recuperada en formato hhmmss:
	horaEventoTrama = ((int)tramaDatos[tramaSize - 3] * 10000) + ((int)tramaDatos[tramaSize - 2] * 100) + ((int)tramaDatos[tramaSize - 1]);
	// Calcula el tiempo de la trama recuperada en formato segundos:
	tiempoEventoTrama = ((int)tramaDatos[tramaSize - 3] * 3600) + ((int)tramaDatos[tramaSize - 2] * 60) + ((int)tramaDatos[tramaSize - 1]);
	// Verifica si el minuto del tiempo local es diferente del minuto del tiempo de la trama recuperada:
	if ((tiempoEventoTrama) == (tiempoEvento))
	{
		printf("\nTrama OK\n");
		banExtraer = 1;
	}
	else
	{
		printf("\nError: El tiempo de la trama no concuerda\n");
		// Imprime la hora y fecha recuperada de la trama de datos
		printf("| ");
		printf("%0.2d/", tramaDatos[tramaSize - 6]); // aa
		printf("%0.2d/", tramaDatos[tramaSize - 5]); // mm
		printf("%0.2d ", tramaDatos[tramaSize - 4]); // dd
		printf("%0.2d:", tramaDatos[tramaSize - 3]); // hh
		printf("%0.2d:", tramaDatos[tramaSize - 2]); // mm
		printf("%0.2d ", tramaDatos[tramaSize - 1]); // ss
		printf("%d", tiempoEventoTrama);			 // tiempo en segundos
		printf("|\n");
		banExtraer = 1;
	}
	////////////////////////////////////////////////////////////////////////////////////////////////////////////////

	////////////////////////////////////////////////////////////////////////////////////////////////////////////////
	// Inicia el proceso de extraccion y almacenamieto del evento
	////////////////////////////////////////////////////////////////////////////////////////////////////////////////
	if (banExtraer == 1)
	{

		printf("\nExtrayendo...\n");

		// Crea un archivo binario para guardar el evento:
		CrearArchivo(duracionEvento, tramaDatos, config);

		// Escritura de datos en los archivo de aceleracion:
		while (contMuestras < duracionEvento)
		{													// Se almacena el numero de muestras que indique la variable duracionEvento
			fread(tramaDatos, sizeof(char), tramaSize, lf); // Leo la cantidad establecida en la variable tramaSize del contenido del archivo lf y lo guardo en el vector tramaDatos

			if (fileX != NULL)
			{
				do
				{
					// Guarda la trama en el archivo binario:
					outFwrite = fwrite(tramaDatos, sizeof(char), 2506, fileX);
				} while (outFwrite != 2506);
				fflush(fileX);
			}

			contMuestras++;
		}

		fclose(fileX);

		////////////////////////////////////////////////////////////////////////////////////////////////////////////////
	}
	////////////////////////////////////////////////////////////////////////////////////////////////////////////////

	////////////////////////////////////////////////////////////////////////////////////////////////////////////////
	// Final
	////////////////////////////////////////////////////////////////////////////////////////////////////////////////
	fclose(lf);
	printf("\nTerminado\n");
	////////////////////////////////////////////////////////////////////////////////////////////////////////////////
}

void CrearArchivo(unsigned int duracionEvento, unsigned char *tramaRegistro, struct datos_config *config)
{
	// Variables para crear el nombre del archivo:
	char tiempoNodoStr[30];
	char duracionEventoStr[4];
	char extBin[5];

	// Variables para crear los archivos de datos:
	char filenameEventoExtraido[150];

	// Asigna el texto correspondiente a los array de carateres:
	strcpy(extBin, ".dat");

	// Extrae el tiempo de la trama pyload:
	unsigned char dd = tramaRegistro[tramaSize - 6]; // día
	unsigned char mm = tramaRegistro[tramaSize - 5]; // mes
	unsigned char aa = tramaRegistro[tramaSize - 4]; // año (2 dígitos)
	unsigned char hh = tramaRegistro[tramaSize - 3]; // hora
	unsigned char min = tramaRegistro[tramaSize - 2]; // minuto
	unsigned char ss = tramaRegistro[tramaSize - 1]; // segundo

	// Calcula el año completo (asume 20xx para años < 70, 19xx para >= 70)
	unsigned int anio_completo = (aa < 70) ? (2000 + aa) : (1900 + aa);

	// Formato: ID_AAAAMMDD_hhmmss_duracion.dat
	sprintf(tiempoNodoStr, "%04d%02d%02d_%02d%02d%02d_", anio_completo, mm, dd, hh, min, ss);
	sprintf(duracionEventoStr, "%03d", duracionEvento);

	// Construye la ruta completa del archivo usando config->eventos_extraidos
	strcpy(filenameEventoExtraido, config->eventos_extraidos);
	strcat(filenameEventoExtraido, config->id);
	strcat(filenameEventoExtraido, "_");
	strcat(filenameEventoExtraido, tiempoNodoStr);
	strcat(filenameEventoExtraido, duracionEventoStr);
	strcat(filenameEventoExtraido, extBin);

	// Crea el archivo binario:
	printf("Se ha creado el archivo: %s\n", filenameEventoExtraido);
	fileX = fopen(filenameEventoExtraido, "ab+");

	// Construye la ruta del archivo temporal usando config->archivos_temporales
	char filenameArchivoTemporal[150];
	strcpy(filenameArchivoTemporal, config->archivos_temporales);
	strcat(filenameArchivoTemporal, "NombreArchivoEventoExtraido.tmp");

	// Abre el archivo temporal para escribir el nombre del archivo en modo escritura:
	ftmp = fopen(filenameArchivoTemporal, "w+");
	// Escribe el nombre del archivo:
	fwrite(filenameEventoExtraido, sizeof(char), strlen(filenameEventoExtraido), ftmp);
	// Cierra el archivo temporal:
	fclose(ftmp);
}

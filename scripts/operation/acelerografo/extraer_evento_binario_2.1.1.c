// Autor: Milton Muñoz
// Fecha: 24/03/2021

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <math.h>

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
FILE *ficheroDatosConfiguracion;

// Declaracion de funciones
void RecuperarVector();
void CrearArchivo(unsigned int duracionEvento, unsigned char *tramaRegistro);

int main(int argc, char *argv[])
{

	////////////////////////////////////////////////////////////////////////////////////////////////////////////////
	// Ingreso de datos
	////////////////////////////////////////////////////////////////////////////////////////////////////////////////
	// strcpy(filenameArchivoRegistroContinuo, argv[1]);
	strcpy(nombreArchivo, argv[1]);
	strcpy(filenameArchivoRegistroContinuo, "/home/rsa/resultados/registro-continuo/");
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

	RecuperarVector();

	// Comando para ejecutar el script de Python
	//const char *comandoPython = "sudo python3 /home/rsa/programas/ConversorMseed.py 2";
	//system(comandoPython);

	return 0;
}

void RecuperarVector()
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
		CrearArchivo(duracionEvento, tramaDatos);

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

void CrearArchivo(unsigned int duracionEvento, unsigned char *tramaRegistro)
{

	// Variables para extraer los datos de configuracion:
	char idEstacion[10];
	char pathEventosExtraidos[60];
	char extBin[5];

	// Variables para crear el nombre del archivo:
	char tiempoNodoStr[25];
	char duracionEventoStr[4];
	char tiempoNodo[6];

	// Variables para crear los archivos de datos:
	char filenameEventoExtraido[30];

	// Se leen los datos de configuracion:
	printf("Leyendo archivo de configuracion...\n");

	// Abre el fichero de datos de configuracion:
	ficheroDatosConfiguracion = fopen("/home/rsa/configuracion/DatosConfiguracion.txt", "rt");
	// Recupera el contenido del archivo en la variable arg1 hasta que encuentra el carácter de fin de línea (\n):
	fgets(idEstacion, 10, ficheroDatosConfiguracion);
	for (i = 0; i < 4; i++)
	{
		fgets(pathEventosExtraidos, 60, ficheroDatosConfiguracion); // Recupera la quinta fila del archivo de configuracion
	}
	// Cierra el fichero de informacion:
	fclose(ficheroDatosConfiguracion);

	// Elimina el caracter de fin de linea (\n):
	strtok(idEstacion, "\n");
	strtok(pathEventosExtraidos, "\n");
	// Elimina el caracter de retorno de carro (\r):
	strtok(idEstacion, "\r");
	strtok(pathEventosExtraidos, "\r");

	// Asigna el texto correspondiente a los array de carateres:
	strcpy(extBin, ".dat");

	// Extrae el tiempo de la trama pyload:
	tiempoNodo[0] = tramaRegistro[tramaSize - 6]; // dd
	tiempoNodo[1] = tramaRegistro[tramaSize - 5]; // mm
	tiempoNodo[2] = tramaRegistro[tramaSize - 4]; // aa
	tiempoNodo[3] = tramaRegistro[tramaSize - 3]; // hh
	tiempoNodo[4] = tramaRegistro[tramaSize - 2]; // mm
	tiempoNodo[5] = tramaRegistro[tramaSize - 1]; // ss

	// Realiza la concatenacion para obtener el nombre del archivo:
	sprintf(tiempoNodoStr, "%0.2d%0.2d%0.2d-%0.2d%0.2d%0.2d_", tiempoNodo[2], tiempoNodo[1], tiempoNodo[0], tiempoNodo[3], tiempoNodo[4], tiempoNodo[5]);
	sprintf(duracionEventoStr, "%0.3d", duracionEvento);

	// Crea el archivo temporal para guardar el nombre del archivo de registro continuo actual:
	//strcpy(filenameEventoExtraido, pathEventosExtraidos);
	strcpy(filenameEventoExtraido, idEstacion);
	strcat(filenameEventoExtraido, tiempoNodoStr);
	strcat(filenameEventoExtraido, duracionEventoStr);
	strcat(filenameEventoExtraido, extBin);

	// Crea el archivo binario:
	printf("Se ha creado el archivo: %s\n", filenameEventoExtraido);
	fileX = fopen(filenameEventoExtraido, "ab+");

	// Abre el archivo temporal para escribir el nnombre del archivo en modo escritura:
	ftmp = fopen("/home/rsa/tmp/NombreArchivoEventoExtraido.tmp", "w+");
	// Escribe el nombre del archivo:
	fwrite(filenameEventoExtraido, sizeof(char), 27, ftmp);
	// Cierra el archivo temporal:
	fclose(ftmp);
}


#include <stdio.h>
#include <stdlib.h>
#include <wiringPi.h>
#include <bcm2835.h>
#include <time.h>
#include <string.h>
#include <unistd.h>

// Declaracion de constantes
#define P1 0	// Pin 11 GPIO
#define MCLR 28 // Pin 38 GPIO
#define TEST 26 // Pin 32 GPIO
#define TIEMPO_SPI 10
#define FreqSPI 2000000

// Declaracion de funciones
int ConfiguracionPrincipal();

int main(int argc, char *argv[])
{

	// Configuracion principal:
	ConfiguracionPrincipal();

	return 0;
}

//**************************************************************************************************************************************
// Configuracion:

int ConfiguracionPrincipal()
{

	// Configuracion libreria WiringPi:
	wiringPiSetup();
	pinMode(MCLR, OUTPUT);
	pinMode(TEST, OUTPUT);

	// Genera un pulso para resetear el dsPIC:
	digitalWrite(MCLR, HIGH);
	delay(100);
	digitalWrite(MCLR, LOW);
	delay(100);
	digitalWrite(MCLR, HIGH);

	// Genera un pulso en el TEST:
	digitalWrite(TEST, LOW);
	delay(1000);
	digitalWrite(TEST, HIGH);
}
//**************************************************************************************************************************************

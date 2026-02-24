/*-------------------------------------------------------------------------------------------------------------------------
Autor: Milton Munoz, email: miltonrodrigomunoz@gmail.com
Fecha de creacion: 14/03/2019
Configuracion: dsPIC33EP256MC202, XT=80MHz
---------------------------------------------------------------------------------------------------------------------------*/

////////////////////////////////////////////////////         Librerias         /////////////////////////////////////////////////////////////

#include "ADXL355_SPI.h"
#include "TIEMPO_GPS.h"
#include "TIEMPO_RPI.h"
#include "TIEMPO_RTC.h"

///////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////

//////////////////////////////////////////////////// Declaracion de variables //////////////////////////////////////////////////////////////

// Variables y contantes para la peticion y respuesta de datos
sbit RP1 at LATA4_bit; // Definicion del pin P1
sbit RP1_Direction at TRISA4_bit;
sbit RP2 at LATB4_bit; // Definicion del pin P2
sbit RP2_Direction at TRISB4_bit;
sbit LedTest at LATB12_bit; // Definicion del pin P2
sbit TEST_Direction at TRISB12_bit;

unsigned char tramaGPS[70];
unsigned char datosGPS[13];
unsigned char tiempo[6];    // Vector de datos de tiempo del sistema
unsigned char tiempoRPI[6]; // Vector para recuperar el tiempo enviado desde la RPi
unsigned char datosLeidos[9] = {0, 0, 0, 0, 0, 0, 0, 0, 0};
unsigned char datosFIFO[243];      // Vector para almacenar 27 muestras de 3 ejes del vector FIFO
unsigned char tramaCompleta[2506] = {0}; // Vector para almacenar 10 vectores datosFIFO, 250 cabeceras de muestras y el vector tiempo
unsigned char numFIFO, numSetsFIFO; // Variablea para almacenar el numero de muestras y sets recuperados del buffer FIFO
unsigned char contTimer1;           // Variable para contar el numero de veces que entra a la interrupcion por Timer 1

unsigned int i, x, y, i_gps, j;
unsigned char buffer;
unsigned char contMuestras;
unsigned char contCiclos;
unsigned int contFIFO;
unsigned char tasaMuestreo;
unsigned char numTMR1;

unsigned char banTC, banTI, banTF; // Banderas de trama completa, inicio de trama y final de trama
unsigned char banLec, banEsc, banCiclo, banInicio, banSetReloj, banSetGPS, banSyncReloj;
unsigned char banMuestrear, banLeer, banConf;
unsigned char banOperacion, tipoOperacion;

unsigned char byteGPS, banGPSI, banTFGPS, banGPSC, stsGPS;
unsigned char fuenteReloj; // Indiaca la fuente de reloj 0:RTC 1:GPS
unsigned char confGPS[2];
unsigned long horaSistema, fechaSistema;
unsigned char referenciaTiempo;
unsigned char banInicializar;
unsigned char contTimeout1;
unsigned char banInitGPS;
unsigned char contTimer3;

// Variable de estado para rastrear la recepci�n de la trama SPI:
//int estadoTrama;
//enum EstadoRecepcion {EsperandoInicio, RecibiendoDatos, EsperandoFin};
//estadoTrama = EsperandoInicio;

//////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////

/////////////////////////////////////////////////////////  Declaracion de funciones  /////////////////////////////////////////////////////////
void ConfiguracionPrincipal();
void Muestrear();
void InterrupcionP1(unsigned char operacion);
//////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////

//////////////////////////////////////////////////////////////      Main      ////////////////////////////////////////////////////////////////
void main()
{

   tasaMuestreo = 1; // 1=250Hz, 2=125Hz, 4=62.5Hz, 8=31.25Hz
   numTMR1 = (tasaMuestreo * 10) - 1; // Calcula el numero de veces que tienen que desbordarse el TMR1 para cada tasa de muestreo

   banOperacion = 0;
   tipoOperacion = 0;

   banTI = 0;
   banLec = 0;
   banEsc = 0;
   banCiclo = 0;
   banSetReloj = 0;

   banSetGPS = 0;
   banGPSI = 0;
   banTFGPS = 0;
   banGPSC = 0;
   stsGPS = 0;
   fuenteReloj = 0;
   banSyncReloj = 0;

   banMuestrear = 0; // Inicia el programa con esta bandera en bajo para permitir que la RPi envie la peticion de inicio de muestreo
   banInicio = 0;    // Bandera de inicio de muestreo
   banLeer = 0;
   banConf = 0;

   i = 0;
   x = 0;
   y = 0;
   i_gps = 0;
   horaSistema = 0;
   referenciaTiempo = 0;
   contTimeout1 = 0;

   contMuestras = 0;
   contCiclos = 0;
   contFIFO = 0;
   numFIFO = 0;
   numSetsFIFO = 0;
   contTimer1 = 0;
   contTimer3 = 0;

   byteGPS = 0;
   banInitGPS = 0;

   // Inicio:
   banInicializar = 0;

   RP1 = 0;
   RP2 = 0;
   LedTest = 0;

   SPI1BUF = 0x00;

   ConfiguracionPrincipal();

   while (1)
   {
      Delay_ms(1);
   }
   
}
///////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////

//////////////////////////////////////////////////////////////// Funciones ////////////////////////////////////////////////////////////////

//****************************************************************************************************************************************
// Funcion para realizar la configuracion principal
void ConfiguracionPrincipal()
{

   // configuracion del oscilador                                              //FPLLO = FIN*(M/(N1+N2)) = 80.017MHz
   CLKDIVbits.FRCDIV = 0;   // FIN=FRC/1
   CLKDIVbits.PLLPOST = 0;  // N2=2
   CLKDIVbits.PLLPRE = 5;   // N1=7
   PLLFBDbits.PLLDIV = 150; // M=152

   // Configuracion de puertos
   ANSELA = 0;      // Configura PORTA como digital     *
   ANSELB = 0;      // Configura PORTB como digital     *
   TRISA2_bit = 0;  // Configura el pin A2 como salida  *
   TRISA3_bit = 0;  // Configura el pin A3 como salida  *
   TRISA4_bit = 0;  // Configura el pin A4 como salida  *
   TRISB4_bit = 0;  // Configura el pin B4 como salida  *
   TRISB12_bit = 0; // Configura el pin B12 como salida *

   TRISB10_bit = 1; // Configura el pin B10 como entrada *
   TRISB11_bit = 1; // Configura el pin B11 como entrada *
   TRISB13_bit = 1; // Configura el pin B13 como entrada *
   TRISB14_bit = 1;
   TRISB15_bit = 1; // Configura el pin B15 como entrada *

   INTCON2.GIE = 1; // Habilita las interrupciones globales *

   // Configuracion del puerto SPI1 en modo Esclavo
   SPI1STAT.SPIEN = 1;                                                                                                                                                 // Habilita el SPI1 *
   SPI1_Init_Advanced(_SPI_SLAVE, _SPI_8_BIT, _SPI_PRESCALE_SEC_1, _SPI_PRESCALE_PRI_1, _SPI_SS_ENABLE, _SPI_DATA_SAMPLE_END, _SPI_CLK_IDLE_HIGH, _SPI_ACTIVE_2_IDLE); //*
   SPI1IE_bit = 1;                                                                                                                                                     // Habilita la interrupcion por SPI1  *
   SPI1IF_bit = 0;                                                                                                                                                     // Limpia la bandera de interrupcion por SPI *
   IPC2bits.SPI1IP = 0x03;                                                                                                                                             // Prioridad de la interrupcion SPI1

   // Configuracion del puerto SPI2 en modo Master
   RPINR22bits.SDI2R = 0x21; // Configura el pin RB1/RPI33 como SDI2 *
   RPOR2bits.RP38R = 0x08;   // Configura el SDO2 en el pin RB6/RP38 *
   RPOR1bits.RP37R = 0x09;   // Configura el SCK2 en el pin RB5/RP37 *
   SPI2STATbits.SPIROV = 0;  // No Receive Overflow has occurred
   SPI2STAT.SPIEN = 1;       // Habilita el SPI2 *
   SPI2_Init();              // Inicializa el modulo SPI2
   CS_DS3234 = 1;            // Pone en alto el CS del RTC
   CS_ADXL355 = 1;           // Pone en alto el CS del acelerometro

   // Configuracion del puerto UART1
   RPINR18bits.U1RXR = 0x22; // Configura el pin RB2/RPI34 como Rx1 *
   RPOR0bits.RP35R = 0x01;   // Configura el Tx1 en el pin RB3/RP35 *
   U1RXIE_bit = 1;           // Habilita la interrupcion por UART1 RX *
   U1RXIF_bit = 0;           // Limpia la bandera de interrupcion por UART1 RX *
   IPC2bits.U1RXIP = 0x04;   // Prioridad de la interrupcion UART1 RX
   U1STAbits.URXISEL = 0x00;
   UART1_Init(9600); // Inicializa el UART1 con una velocidad de 9600 baudios

   // Configuracion de la interrupcion externa INT1
   RPINR0 = 0x2F00;        // Asigna INT1 al RB15/RPI47 (SQW)
   INT1IE_bit = 1;         // Habilita la interrupcion externa INT1
   INT1IF_bit = 0;         // Limpia la bandera de interrupcion externa INT1
   IPC5bits.INT1IP = 0x02; // Prioridad en la interrupocion externa INT1

   // Configuracion de la interrupcion externa INT2
   RPINR1 = 0x002E;        // Asigna INT2 al RB14/RPI46 (PPS)
   INT2IE_bit = 1;         // Habilita la interrupcion externa INT1
   INT2IF_bit = 0;         // Limpia la bandera de interrupcion externa INT1
   IPC7bits.INT2IP = 0x01; // Prioridad en la interrupocion externa INT2

   // Configuracion del TMR1 con un tiempo de 100ms
   T1CON = 0x0020;
   T1CON.TON = 0;        // Apaga el TMR1
   T1IE_bit = 1;         // Habilita la interrupcion de desbordamiento TMR1
   T1IF_bit = 0;         // Limpia la bandera de interrupcion del TMR1
   PR1 = 62500;          // Car ga el preload para un tiempo de 100ms
   IPC0bits.T1IP = 0x02; // Prioridad de la interrupcion por desbordamiento del TMR1

   // Configuracion del TMR2 con un tiempo de 300ms
   T2CON = 0x30;         // Prescalador
   T2CON.TON = 0;        // Apaga el TMR2
   T2IE_bit = 1;         // Habilita la interrupcion de desbordamiento TMR2
   T2IF_bit = 0;         // Limpia la bandera de interrupcion del TMR2
   PR2 = 46875;          // Carga el preload para un tiempo de 300ms
   IPC1bits.T2IP = 0x02; // Prioridad de la interrupcion por desbordamiento del TMR2

   // Configuracion del TMR3 con un tiempo de 500ms
   T3CON = 0x20;         // Prescalador
   T3CON.TON = 0;        // Apaga el TMR3
   T3IE_bit = 1;         // Habilita la interrupcion de desbordamiento TMR3
   T3IF_bit = 0;         // Limpia la bandera de interrupcion del TMR3
   PR3 = 62500;          // Carga el preload para un tiempo de 500ms
   IPC2bits.T3IP = 0x02; // Prioridad de la interrupcion por desbordamiento del TMR3

   Delay_ms(200); // Espera hasta que se estabilicen los cambios
   
   // Configuracion del RTC:
   DS3234_init();              // inicializa el RTC
   
   Delay_ms(500);              // Espera hasta que se estabilicen los cambios del RTC
   
   // Configuracion del acelerometro:
   ADXL355_init(tasaMuestreo); // Inicializa el modulo ADXL con la tasa de muestreo requerida
   
   //Configuracion del GPS:
   GPS_init();
   U1MODE.UARTEN = 0;
   
   // Conmuta el ledTest para indicar que se termino la configuracion:
   LedTest = ~LedTest;
   Delay_ms(300);
   LedTest = ~LedTest;
   Delay_ms(300);
   LedTest = ~LedTest;

}
//****************************************************************************************************************************************

//*****************************************************************************************************************************************
// Funcion para realizar la interrupcion en la RPi
void InterrupcionP1(unsigned char operacion)
{
   banOperacion = 0;          // Encera la bandera para permitir una nueva peticion de operacion
   tipoOperacion = operacion; // Carga en la variable el tipo de operacion requerido
   // Genera el pulso P1 para producir la interrupcion externa en la RPi
   RP1 = 1;
   Delay_us(20);
   RP1 = 0;
}
//*****************************************************************************************************************************************

//****************************************************************************************************************************************
// Funcion para relizar el muesteo
void Muestrear()
{

   if (banCiclo == 1)
   {
      ADXL355_write_byte(POWER_CTL, DRDY_OFF | MEASURING); // Coloca el ADXL en modo medicion
      T1CON.TON = 1;                                       // Enciende el Timer1
   }
   else if (banCiclo == 2)
   {

      banCiclo = 3; // Limpia la bandera de ciclo completo

      tramaCompleta[0] = fuenteReloj; // LLena el primer elemento de la tramaCompleta con el identificador de fuente de reloj
      numFIFO = ADXL355_read_byte(FIFO_ENTRIES);
      numSetsFIFO = (numFIFO) / 3; // Lee el numero de sets disponibles en el FIFO

      // Este bucle recupera tantos sets de mediciones del buffer FIFO como indique la variable anterior
      for (x = 0; x < numSetsFIFO; x++)
      {
         ADXL355_read_FIFO(datosLeidos); // Lee una sola posicion del FIFO
         for (y = 0; y < 9; y++)
         {
            datosFIFO[y + (x * 9)] = datosLeidos[y]; // LLena la trama datosFIFO
            //datosFIFO[y + (x * 9)] = numSetsFIFO;  // Prueba para comprobar el numero de sets leidos en la ultima muestra
         }
      }

      // Este bucle rellena la trama completa intercalando el numero de muestra correspondientes
      for (x = 0; x < (numSetsFIFO * 9); x++)
      {
         if ((x == 0) || (x % 9 == 0))
         {
            tramaCompleta[contFIFO + contMuestras + x] = contMuestras; // Funciona bien
            tramaCompleta[contFIFO + contMuestras + x + 1] = datosFIFO[x];
            contMuestras++;
         }
         else
         {
            tramaCompleta[contFIFO + contMuestras + x] = datosFIFO[x];
         }
      }

      // LLena la trama tiempo con el valor del tiempo actual del sistema y luega rellena la tramaCompleta con los valores de esta trama
      AjustarTiempoSistema(horaSistema, fechaSistema, tiempo);
      for (x = 0; x < 6; x++)
      {
         tramaCompleta[2500 + x] = tiempo[x];
      }

      contMuestras = 0; // Limpia el contador de muestras
      contFIFO = 0;     // Limpia el contador de FIFOs
      T1CON.TON = 1;    // Enciende el Timer1

      banLec = 1; // Activa la bandera de lectura para enviar la trama
      InterrupcionP1(0XB1);

      LedTest = 0;
   }

}
//****************************************************************************************************************************************

///////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////

////////////////////////////////////////////////////////////// Interrupciones /////////////////////////////////////////////////////////////

// Interrupcion SPI1: RPi
void spi_1() org IVT_ADDR_SPI1INTERRUPT
{

   SPI1IF_bit = 0;   // Limpia la bandera de interrupcion por SPI
   buffer = SPI1BUF; // Guarda el contenido del bufeer (lectura)

   //************************************************************************************************************************************
   // Rutina para enviar la peticion de operacion a la RPi  (C:0xA0   F:0xF0)
   if ((banOperacion == 0) && (buffer == 0xA0))
   {
      banOperacion = 1;        // Activa la bandera para enviar el tipo de operacion requerido a la RPi
      SPI1BUF = tipoOperacion; // Carga en el buffer el tipo de operacion requerido
   }
   if ((banOperacion == 1) && (buffer == 0xF0))
   {
      banOperacion = 0;  // Limpia la bandera
      tipoOperacion = 0; // Limpia la variable de tipo de operacion
   }
   //************************************************************************************************************************************

   //************************************************************************************************************************************
   // Rutina para inicio del muestreo (C:0xA1   F:0xF1):
   if ((banMuestrear == 0) && (buffer == 0xA1))
   {
      banMuestrear = 1;
      banCiclo = 1;
   }
   if ((banMuestrear == 1) && (buffer != 0xA1) && (buffer != 0xF1))
   {
      banInicio = 1;  // Bandera que permite el inicio del muestreo dentro de la interrupcion INT1
      /*
      banCiclo = 0;
      contMuestras = 0;
      contCiclos = 0;
      contFIFO = 0;
      numFIFO = 0;
      numSetsFIFO = 0;
      contTimer1 = 0;
      */
   }
   if ((banMuestrear == 1) && (buffer == 0xF1))
   {
      banMuestrear = 0;
   }

   // Rutina para inicializar el GPS:
   if ((banInitGPS == 0) && (buffer == 0xA2))
   {
      // Cambia el estado de la bandera:
      banInitGPS = 1;
      SPI1BUF = 0x47; // Ascii: G
   }
   if ((banInitGPS == 1) && (buffer == 0xF2))
   {
      //GPS_init();
      // Conmuta el LedTest para indicar que se inicializo el GPS:
      LedTest = 0;
      Delay_ms(150);
      LedTest = ~LedTest;
      Delay_ms(150);
      LedTest = ~LedTest;
      Delay_ms(150);
      LedTest = ~LedTest;
      Delay_ms(150);
      LedTest = ~LedTest;
      Delay_ms(150);
      LedTest = ~LedTest;
   }

   // Rutina de lectura de los datos del acelerometro (C:0xA3   F:0xF3):
   if ((banLec == 1) && (buffer == 0xA3))
   {              // Verifica si la bandera de inicio de trama esta activa
      banLec = 2; // Activa la bandera de lectura
      i = 0;
      SPI1BUF = tramaCompleta[i];
   }
   if ((banLec == 2) && (buffer != 0xF3))
   {
      SPI1BUF = tramaCompleta[i];
      i++;
   }
   if ((banLec == 2) && (buffer == 0xF3))
   {              // Si detecta el delimitador de final de trama:
      banLec = 0; // Limpia la bandera de lectura                        ****AQUI Me QUEDE
      SPI1BUF = 0xFF;
   }
   //************************************************************************************************************************************

   //************************************************************************************************************************************
   // Rutina para obtener la hora de la RPi (C:0xA4   F:0xF4):
   if ((banEsc == 0) && (buffer == 0xA4))
   {
      banEsc = 1;
      j = 0;
   } 
   if ((banEsc == 1) && (buffer != 0xA4) && (buffer != 0xF4))
   {
      tiempoRPI[j] = buffer;
      j++;
   }
   if ((banEsc == 1) && (buffer == 0xF4))
   {
      horaSistema = RecuperarHoraRPI(tiempoRPI);               // Recupera la hora de la RPi
      fechaSistema = RecuperarFechaRPI(tiempoRPI);             // Recupera la fecha de la RPi
      fuenteReloj = 0;                                         // Fuente de reloj = RPi
      
      //Configuracion del RTC aplicando un retardo de 500ms:
      T3CON.TON = 1;
      TMR3 = 0;

      banEsc = 0;

   }

   // Rutina para enviar la hora local a la RPi (C:0xA5   F:0xF5):
   if ((banSetReloj == 1) && (buffer == 0xA5))
   {
      banSetReloj = 2;
      j = 0;
      SPI1BUF = fuenteReloj; // Envia el indicador de fuente de reloj (0:RTC, 1:GPS)
   }
   if ((banSetReloj == 2) && (buffer != 0xA5) && (buffer != 0xF5))
   {
      SPI1BUF = tiempo[j];
      j++;
   }
   if ((banSetReloj == 2) && (buffer == 0xF5))
   {                   // Si detecta el delimitador de final de trama:
      banSetReloj = 1; // Reactiva la bandera de lectura
      SPI1BUF = 0xFF;
   }

   // Rutina para obtener la referencia de reloj del GPS o el RTC (C:0xA6   F:0xF6):
   if ((banEsc == 0) && (buffer == 0xA6))
   {
      banEsc = 1;
   }
   if ((banEsc == 1) && (buffer != 0xA6) && (buffer != 0xF6))
   {
      referenciaTiempo = buffer; // Recupera la opcion de referencia de tiempo solicitada
   }
   if ((banEsc == 1) && (buffer == 0xF6))
   {
      if (referenciaTiempo == 1)
      {
         // Recupera el tiempo del GPS:
         banGPSI = 1;       // Activa la bandera de inicio de trama  del GPS
         banGPSC = 0;       // Limpia la bandera de trama completa
         U1MODE.UARTEN = 1; // Inicializa el UART1
         //  Inicia el Timeout 1:
         T2CON.TON = 1;
         TMR2 = 0;
      }
      else
      {
         // Recupera el tiempo del RTC:
         horaSistema = RecuperarHoraRTC();                        // Recupera la hora del RTC
         fechaSistema = RecuperarFechaRTC();                      // Recupera la fecha del RTC
         AjustarTiempoSistema(horaSistema, fechaSistema, tiempo); // Actualiza los datos de la trama tiempo con la hora y fecha recuperadas
         fuenteReloj = 2;                                         // Fuente de reloj = RTC
         InterrupcionP1(0xB2);                                    // Envia la hora local a la RPi
      }
      banEsc = 0;
      banSetReloj = 1; // Activa esta bandera para usar la hora/fecha recuperada
   }
   //************************************************************************************************************************************
}
///////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////

///////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////
// Inicio fuente de reloj
///////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////
// Interrupcion INT1: RTC-SQW
void int_1() org IVT_ADDR_INT1INTERRUPT
{

   INT1IF_bit = 0; // Limpia la bandera de interrupcion externa INT1

   if (banSetReloj == 1)
   {
      LedTest = ~LedTest;
      horaSistema++; // Incrementa el reloj del sistema
      //  Reinicia el reloj al llegar a las 24:00:00 horas
      if (horaSistema == 86400)
      {
         horaSistema = 0; //(24*3600)+(0*60)+(0) = 86400
      }
      if (banInicio == 1)
      {
         Muestrear();
      }
   }
}
//*****************************************************************************************************************************************
// Interrupcion INT2: GPS-PPS
void int_2() org IVT_ADDR_INT2INTERRUPT
{

   INT2IF_bit = 0; // Limpia la bandera de interrupcion externa INT2

   if (banSyncReloj == 1)
   {
      // Cumple en este turno las tareas del pulso SQW:
      LedTest = ~LedTest;
      //horaSistema = horaSistema + 2; // Incrementa el reloj del sistema en 2 segundos
      horaSistema = horaSistema + 1; // Correccion 230901: Incrementa el reloj del sistema en 1 segundo
      // Inicia el Timer3 de 500ms:
      T3CON.TON = 1;
      TMR3 = 0;
   }
}
///////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////
// Fin fuente de reloj
///////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////

/*
///////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////
// Inicio modificacion fuente reloj: Utilizado para hacer pruebas de sincronizacion
///////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////
// Interrupcion INT1: RTC-SQW
void int_1() org IVT_ADDR_INT1INTERRUPT
{
   INT1IF_bit = 0; // Limpia la bandera de interrupcion externa INT1
}
// Interrupcion INT2: GPS-PPS
void int_2() org IVT_ADDR_INT2INTERRUPT
{
   INT2IF_bit = 0;
   if (banSetReloj == 1)
   {
      LedTest = ~LedTest;
      horaSistema++; // Incrementa el reloj del sistema
      if (horaSistema == 86400)
      {
         horaSistema = 0; //(24*3600)+(0*60)+(0) = 86400
      }
      if (banInicio == 1)
      {
         Muestrear();
      }
   }
}
///////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////
// Fin modificacion fuente reloj
///////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////
*/

///////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////
// Interrupcion Timer1: Lectura ADXL355
void Timer1Int() org IVT_ADDR_T1INTERRUPT
{

   T1IF_bit = 0; // Limpia la bandera de interrupcion por desbordamiento del Timer1

   numFIFO = ADXL355_read_byte(FIFO_ENTRIES); // 75                            //Lee el numero de muestras disponibles en el FIFO
   numSetsFIFO = (numFIFO) / 3;               // 25                            //Lee el numero de sets disponibles en el FIFO

   // Este bucle recupera tantos sets de mediciones del buffer FIFO como indique la variable anterior
   for (x = 0; x < numSetsFIFO; x++)
   {
      ADXL355_read_FIFO(datosLeidos); // Lee una sola posicion del FIFO
      for (y = 0; y < 9; y++)
      {
         datosFIFO[y + (x * 9)] = datosLeidos[y]; // LLena la trama datosFIFO
      }
   }

   // Este bucle rellena la trama completa intercalando el numero de muestra correspondientes
   for (x = 0; x < (numSetsFIFO * 9); x++)
   { // 0-224
      if ((x == 0) || (x % 9 == 0))
      {
         tramaCompleta[contFIFO + contMuestras + x] = contMuestras;
         tramaCompleta[contFIFO + contMuestras + x + 1] = datosFIFO[x];
         contMuestras++;
      }
      else
      {
         tramaCompleta[contFIFO + contMuestras + x] = datosFIFO[x];
      }
   }

   contFIFO = (contMuestras * 9); // Incrementa el contador de FIFOs

   contTimer1++; // Incrementa una unidad cada vez que entra a la interrupcion por Timer1

   if (contTimer1 == numTMR1)
   {                  // Verifica si se cumplio el numero de interrupciones por TMR1 para la tasa de muestreo seleccionada
      T1CON.TON = 0;  // Apaga el Timer1
      banCiclo = 2;   // Activa la bandera que indica que se completo un ciclo de medicion
      contTimer1 = 0; // Limpia el contador de interrupciones por Timer1
   }
}

///////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////
// Interrupcion Timer2: Timeout de 4*300ms para el UART1:
void Timer2Int() org IVT_ADDR_T2INTERRUPT
{

   T2IF_bit = 0;   // Limpia la bandera de interrupcion por desbordamiento del Timer2
   contTimeout1++; // Incrementa el contador de Timeout

   // Despues de 4 desbordamientos apaga el Timer2 y recupera la hora del RTC:
   if (contTimeout1 == 4)
   {
      T2CON.TON = 0;
      TMR2 = 0;
      contTimeout1 = 0;
      // Recupera la hora del RTC:
      horaSistema = RecuperarHoraRTC();                        // Recupera la hora del RTC
      fechaSistema = RecuperarFechaRTC();                      // Recupera la fecha del RTC
      AjustarTiempoSistema(horaSistema, fechaSistema, tiempo); // Actualiza los datos de la trama tiempo con la hora y fecha recuperadas del RTC
      fuenteReloj = 5;                                         //**Indica que se obtuvo la hora del RTC
      banSetReloj = 1;
      InterrupcionP1(0xB2); // Envia la hora local a la RPi
   }
}

///////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////
// Interrupcion Timer3: Sincronizacion SQW-PPS
void Timer3Int() org IVT_ADDR_T3INTERRUPT
{
   T3IF_bit = 0;

   contTimer3++; // Incrementa una unidad cada vez que entra a la interrupcion por Timer3

   // Revisa si el contador es igual a 5 (500ms)
   if (contTimer3 == 5)
   {
      DS3234_setDate(horaSistema, fechaSistema); // Configura la hora en el RTC con la hora recuperada de la RPi

      banSyncReloj = 0;
      banSetReloj = 1; // Activa esta bandera para continuar trabajando con el pulso SQW

      // Envia la hora local a la RPi:
      InterrupcionP1(0xB2);
      contTimer3 = 0; // Encera el contador
      T3CON.TON = 0;  // Apaga el Timer3
   }
}

///////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////
// Interrupcion UART1: Lectura GPS
void urx_1() org IVT_ADDR_U1RXINTERRUPT
{
   // Recupera el byte recibido en cada interrupcion:
   byteGPS = U1RXREG; // Lee el byte de la trama enviada por el GPS
   U1STA.OERR = 0;    // Limpia este bit para limpiar el FIFO UART1

   // Recupera el pyload de la trama GPS:                                      //Aqui deberia entrar despues de recuperar la cabecera de trama
   if (banGPSI == 3)
   {
      if (byteGPS != 0x2A)
      {
         tramaGPS[i_gps] = byteGPS; // LLena la tramaGPS hasta recibir el ultimo simbolo ("*") de la trama GPS
         i_gps++;
      }
      else
      {
         banGPSI = 0; // Limpia la bandera de inicio de trama
         banGPSC = 1; // Activa la bandera de trama completa
      }
   }

   // Recupera la cabecera de la trama GPS:                                    //Aqui deberia entrar primero cada vez que se recibe una trama nueva
   if ((banGPSI == 1))
   {
      if (byteGPS == 0x24)
      { // Verifica si el primer byte recibido sea la cabecera de trama "$"
         banGPSI = 2;
         i_gps = 0;
      }
   }
   if ((banGPSI == 2) && (i_gps < 6))
   {
      tramaGPS[i_gps] = byteGPS; // Recupera los datos de cabecera de la trama GPS: ["$", "G", "P", "R", "M", "C"]
      i_gps++;
   }
   if ((banGPSI == 2) && (i_gps == 6))
   {
      // Detiene el Timeout 1:
      T2CON.TON = 0;
      TMR2 = 0;
      // Comprueba la cabecera GPRMC:
      if (tramaGPS[1] == 'G' && tramaGPS[2] == 'P' && tramaGPS[3] == 'R' && tramaGPS[4] == 'M' && tramaGPS[5] == 'C')
      {
         banGPSI = 3;
         i_gps = 0;
      }
      else
      {
         banGPSI = 0;
         banGPSC = 0;
         i_gps = 0;
         // Recupera la hora del RTC:
         horaSistema = RecuperarHoraRTC();                        // Recupera la hora del RTC
         fechaSistema = RecuperarFechaRTC();                      // Recupera la fecha del RTC
         AjustarTiempoSistema(horaSistema, fechaSistema, tiempo); // Actualiza los datos de la trama tiempo con la hora y fecha recuperadas del RTC
         fuenteReloj = 4;                                         // Fuente reloj: RTC/E4
         banSetReloj = 1;
         InterrupcionP1(0xB2); // Envia la hora local a la RPi y a los nodos                                                   //Envia la hora local a la RPi
         banGPSI = 0;
         banGPSC = 0;
         i_gps = 0;
         U1MODE.UARTEN = 0; // Desactiva el UART1
      }
   }

   // Realiza el procesamiento de la informacion del  pyload:                  //Aqui se realiza cualquier accion con el pyload recuperado
   if (banGPSC == 1)
   {
      // Extrae los datos de la trama GPS:
      for (x = 0; x < 6; x++)
      {
         datosGPS[x] = tramaGPS[x + 1]; // Guarda los datos de hhmmss
      }
      // Busca el simbolo "," a partir de la posicion 44
      for (x = 44; x < 54; x++)
      {
         if (tramaGPS[x] == 0x2C)
         {
            for (y = 0; y < 6; y++)
            {
               datosGPS[6 + y] = tramaGPS[x + y + 1]; // Guarda los datos de DDMMAA en la trama datosGPS
            }
         }
      }
      horaSistema = RecuperarHoraGPS(datosGPS);                // Recupera la hora del GPS
      fechaSistema = RecuperarFechaGPS(datosGPS);              // Recupera la fecha del GPS
      AjustarTiempoSistema(horaSistema, fechaSistema, tiempo); // Actualiza los datos de la trama tiempo con la hora y fecha recuperadas del gps

      // Verifica que el caracter 12 sea igual a "A" lo cual comprueba que los datos son validos:
      if (tramaGPS[12] == 0x41)
      {
         fuenteReloj = 1; // Fuente reloj: GPS
         banSyncReloj = 1;
         banSetReloj = 0;
      }
      else
      {
         fuenteReloj = 3; // Fuente reloj: GPS/E3
         banSyncReloj = 0;
         banSetReloj = 1;
         InterrupcionP1(0xB2); // Envia la hora local a la RPi
      }
      banGPSI = 0;
      banGPSC = 0;
      i_gps = 0;
      U1MODE.UARTEN = 0; // Desactiva el UART1
   }

   // Limpia la bandera de interrupcion por UART
   U1RXIF_bit = 0;
}
///////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////
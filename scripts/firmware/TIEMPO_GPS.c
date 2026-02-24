// Libreria para el manejo del tiempo del GPS

#include "TIEMPO_GPS.h"

///////////////////////////////////////////        Funciones        ///////////////////////////////////////////


// Funcion para configurar el GPS
void GPS_init()
{
     UART1_Write_Text("$PMTK220,1000*1F\r\n");
     UART1_Write_Text("$PMTK313,1*2E\r\n");
     UART1_Write_Text("$PMTK314,0,1,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0*29\r\n");
     UART1_Write_Text("$PMTK319,1*24\r\n");
     UART1_Write_Text("$PMTK413*34\r\n");
     UART1_Write_Text("$PMTK513,1*28\r\n");
     Delay_ms(1000);

}


// Funcion para tomar la fecha del GPS
unsigned long RecuperarFechaGPS(unsigned char *tramaDatosGPS)
{

     unsigned long tramaFecha[4];
     unsigned long fechaGPS;
     char datoStringF[3];
     char *ptrDatoStringF = &datoStringF;
     datoStringF[2] = '\0';
     tramaFecha[3] = '\0';

     // Anio
     datoStringF[0] = tramaDatosGPS[10];
     datoStringF[1] = tramaDatosGPS[11];
     tramaFecha[0] = atoi(ptrDatoStringF);
     
     // Mes
     datoStringF[0] = tramaDatosGPS[8];
     datoStringF[1] = tramaDatosGPS[9];
     tramaFecha[1] = atoi(ptrDatoStringF);
     
     // Dia
     datoStringF[0] = tramaDatosGPS[6];
     datoStringF[1] = tramaDatosGPS[7];
     tramaFecha[2] = atoi(ptrDatoStringF);


     fechaGPS = (tramaFecha[0] * 10000) + (tramaFecha[1] * 100) + (tramaFecha[2]); // 10000*aa + 100*mm + dd

     return fechaGPS;
}

// Funcion para tomar la hora del GPS
unsigned long RecuperarHoraGPS(unsigned char *tramaDatosGPS)
{

     unsigned long tramaTiempo[4];
     unsigned long horaGPS;
     char datoString[3];
     char *ptrDatoString = &datoString;
     datoString[2] = '\0';
     tramaTiempo[3] = '\0';

     // Horas
     datoString[0] = tramaDatosGPS[0];
     datoString[1] = tramaDatosGPS[1];
     tramaTiempo[0] = atoi(ptrDatoString);

     // Minutos
     datoString[0] = tramaDatosGPS[2];
     datoString[1] = tramaDatosGPS[3];
     tramaTiempo[1] = atoi(ptrDatoString);

     // Segundos
     datoString[0] = tramaDatosGPS[4];
     datoString[1] = tramaDatosGPS[5];
     tramaTiempo[2] = atoi(ptrDatoString);

     horaGPS = (tramaTiempo[0] * 3600) + (tramaTiempo[1] * 60) + (tramaTiempo[2]); // Calcula el segundo actual = hh*3600 + mm*60 + ss
     return horaGPS;
}
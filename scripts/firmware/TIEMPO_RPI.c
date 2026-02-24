//Libreria para el manejo del tiempo del RPI

#include "TIEMPO_RPI.h"

///////////////////////////////////////////        Funciones        ///////////////////////////////////////////

//Funcion para transformar la fecha de la trama de tiempo de la Rpi
unsigned long RecuperarFechaRPI(unsigned char *tramaTiempoRpi){

     unsigned long fechaRPi;

     fechaRPi = ((unsigned long)tramaTiempoRpi[0]*10000)+((unsigned long)tramaTiempoRpi[1]*100)+((unsigned long)tramaTiempoRpi[2]);      //10000*aa + 100*mm + dd

     return fechaRPi;

}

//Funcion para transformar la fecha de la trama de tiempo de la Rpi
unsigned long RecuperarHoraRPI(unsigned char *tramaTiempoRpi){

     unsigned long horaRPi;

     horaRPi = ((unsigned long)tramaTiempoRpi[3]*3600)+((unsigned long)tramaTiempoRpi[4]*60)+((unsigned long)tramaTiempoRpi[5]);      //Calcula el segundo actual = hh*3600 + mm*60 + ss
   
     return horaRPi;

}
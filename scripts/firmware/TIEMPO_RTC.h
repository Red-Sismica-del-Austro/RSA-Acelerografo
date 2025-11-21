#ifndef TIEMPO_RTC_H
#define TIEMPO_RTC_H

///////////////////////////////////////////   Definicion de pines   ///////////////////////////////////////////
sbit CS_DS3234 at LATA2_bit;                                                    //Define el pin CS

/////////////////////////////////////////// Definicion de funciones ///////////////////////////////////////////
void DS3234_init();
void DS3234_write_byte(unsigned char address, unsigned char value);
void DS3234_read_byte(unsigned char address, unsigned char value);
void DS3234_setDate(unsigned long longHora, unsigned long longFecha);
unsigned long RecuperarFechaRTC();
unsigned long RecuperarHoraRTC();
unsigned long IncrementarFecha(unsigned long longFecha);
void AjustarTiempoSistema(unsigned long longHora, unsigned long longFecha, unsigned char *tramaTiempoSistema);

#endif
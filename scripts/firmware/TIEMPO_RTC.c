//Libreria para el manejo del tiempo del RTC DS3234
#include "TIEMPO_RTC.h"

/////////////////////////////////////////// Definicion de registros ///////////////////////////////////////////

// Registros de lectura //
#define Segundos_Lec      0x00                                                  //00-59 BCD
#define Minutos_Lec       0x01                                                  //00-59 BCD
#define Horas_Lec         0x02                                                  //1-12+AM/PM  00-23 BCD
#define DiaSemana_Lec     0x03                                                  //1-7
#define DiaMes_Lec        0x04                                                  //01-31 BCD
#define Mes_Lec           0x05                                                  //01-12 BCD + siglo?
#define Anio_Lec          0x06                                                  //01-99 BCD
#define Control_Lec       0x0E                                                  //Ver Datasheet
#define TempMSB           0x11                                                  //Solo escritura
#define TempLSB           0x12                                                  //Ejm: 00011001 01b = +25.25C (Ver Datasheet)

// Registros de escritura //
#define Segundos_Esc      0x80                                                  //0-59 BCD
#define Minutos_Esc       0x81                                                  //0-59 BCD
#define Horas_Esc         0x82                                                  //1-12+AM/PM  0-23 BCD
#define DiaSemana_Esc     0x83                                                  //1-7
#define DiaMes_Esc        0x84                                                  //01-31 BCD
#define Mes_Esc           0x85                                                  //01-12 BCD + siglo?
#define Anio_Esc          0x86                                                  //01-99 BCD
#define Control           0x8E
#define ControlStatus     0x8F

// Settings Control //
#define Ctrl_Default      0x00
#define Osc_On            0x00
#define OSc_Off           0x80


///////////////////////////////////////////        Funciones        ///////////////////////////////////////////

//Funcion para configurar el DS3234
void DS3234_init(){
        
     SPI2_Init_Advanced(_SPI_MASTER, _SPI_8_BIT, _SPI_PRESCALE_SEC_1, _SPI_PRESCALE_PRI_64, _SPI_SS_DISABLE, _SPI_DATA_SAMPLE_MIDDLE, _SPI_CLK_IDLE_LOW, _SPI_ACTIVE_2_IDLE);
     DS3234_write_byte(Control,0x20);
     DS3234_write_byte(ControlStatus,0x08);
     SPI2_Init();
         
}

//Funcion para escirbir un solo byte en el DS3234
void DS3234_write_byte(unsigned char address, unsigned char value){
        
     CS_DS3234 = 0;
     SPI2_Write(address);
     SPI2_Write(value);
     CS_DS3234 = 1;
         
}

//Funcion para leer un solo byte del DS3234
unsigned char DS3234_read_byte(unsigned char address){
        
     unsigned char value = 0x00;
     CS_DS3234 = 0;
     SPI2_Write(address);
     value = SPI2_Read(0);
     CS_DS3234 = 1;
     return value;
         
}

//Funcion para establecer la hora y fecha en el DS3234 con la hora y fecha recuperada del GPS
void DS3234_setDate(unsigned long longHora, unsigned long longFecha){
        
     unsigned char valueSet;
     unsigned char hora;
     unsigned char minuto;
     unsigned char segundo;
     unsigned char dia;
     unsigned char mes;
     unsigned char anio;
     
     SPI2_Init_Advanced(_SPI_MASTER, _SPI_8_BIT, _SPI_PRESCALE_SEC_1, _SPI_PRESCALE_PRI_64, _SPI_SS_DISABLE, _SPI_DATA_SAMPLE_MIDDLE, _SPI_CLK_IDLE_LOW, _SPI_ACTIVE_2_IDLE);

     hora = (char)(longHora / 3600);
     minuto = (char)((longHora%3600) / 60);
     segundo = (char)((longHora%3600) % 60);

     anio = (char)(longFecha / 10000);
     mes = (char)((longFecha%10000) / 100);
     dia = (char)((longFecha%10000) % 100);

     segundo = Dec2Bcd(segundo);
     minuto = Dec2Bcd(minuto);
     hora = Dec2Bcd(hora);
     dia = Dec2Bcd(dia);
     mes = Dec2Bcd(mes);
     anio = Dec2Bcd(anio);

     DS3234_write_byte(Segundos_Esc, segundo);
     DS3234_write_byte(Minutos_Esc, minuto);
     DS3234_write_byte(Horas_Esc, hora);
     DS3234_write_byte(DiaMes_Esc, dia);
     DS3234_write_byte(Mes_Esc, mes);
     DS3234_write_byte(Anio_Esc, anio);
     
     SPI2_Init();
     
     return;
         
}

//Funcion para recuperar la hora del DS3234
unsigned long RecuperarHoraRTC(){
        
     unsigned char valueRead;
     unsigned long hora;
     unsigned long minuto;
     unsigned long segundo;
     unsigned long horaRTC;
     
     SPI2_Init_Advanced(_SPI_MASTER, _SPI_8_BIT, _SPI_PRESCALE_SEC_1, _SPI_PRESCALE_PRI_64, _SPI_SS_DISABLE, _SPI_DATA_SAMPLE_MIDDLE, _SPI_CLK_IDLE_LOW, _SPI_ACTIVE_2_IDLE);

     valueRead = DS3234_read_byte(Segundos_Lec);
     valueRead = Bcd2Dec(valueRead);
     segundo = (long)valueRead;
     valueRead = DS3234_read_byte(Minutos_Lec);
     valueRead = Bcd2Dec(valueRead);
     minuto = (long)valueRead;
     valueRead = DS3234_read_byte(Horas_Lec);
     valueRead = Bcd2Dec(valueRead);
     hora = (long)valueRead;

     horaRTC = (hora*3600)+(minuto*60)+(segundo);                               //Calcula el segundo actual = hh*3600 + mm*60 + ss
             
     SPI2_Init();
     
     return horaRTC;
         
}

//Funcion para recuperar la fecha del DS3234
unsigned long RecuperarFechaRTC(){
        
     unsigned char valueRead;
     unsigned long dia;
     unsigned long mes;
     unsigned long anio;
     unsigned long fechaRTC;
     
     SPI2_Init_Advanced(_SPI_MASTER, _SPI_8_BIT, _SPI_PRESCALE_SEC_1, _SPI_PRESCALE_PRI_64, _SPI_SS_DISABLE, _SPI_DATA_SAMPLE_MIDDLE, _SPI_CLK_IDLE_LOW, _SPI_ACTIVE_2_IDLE);

     valueRead = DS3234_read_byte(DiaMes_Lec);
     valueRead = Bcd2Dec(valueRead);
     dia = (long)valueRead;
     valueRead = 0x1F & DS3234_read_byte(Mes_Lec);
     valueRead = Bcd2Dec(valueRead);
     mes = (long)valueRead;
     valueRead = DS3234_read_byte(Anio_Lec);
     valueRead = Bcd2Dec(valueRead);
     anio = (long)valueRead;

     fechaRTC = (anio*10000)+(mes*100)+(dia);                                   //10000*aa + 100*mm + dd
          
     SPI2_Init();
     
     return fechaRTC;
         
}

//Funcion para incrementar la fecha
unsigned long IncrementarFecha(unsigned long longFecha){
         
         unsigned long dia;
     unsigned long mes;
     unsigned long anio; 
         unsigned long fechaInc;
         
         anio = longFecha / 10000;
     mes = (longFecha%10000) / 100;
     dia = (longFecha%10000) % 100;
         
         if (dia<28){
                dia++;                 
         } else {
                if (mes==2){
                        //Comprueba si es año biciesto:
                        if (((anio-16)%4)==0){
                                if (dia==29){
                                        dia = 1;
                                        mes++;        
                                } else {
                                        dia++;
                                }
                        } else {
                                dia = 1;
                                mes++;
                        }
                } else {
                        if (dia<30){
                                dia++;
                        } else {
                                if (mes==4||mes==6||mes==9||mes==11){
                                        if (dia==30){
                                                dia = 1;
                                                mes++;
                                        } else {
                                                dia++;
                                        }
                                }
                                if ((dia!=1)&&(mes==1||mes==3||mes==5||mes==7||mes==8||mes==10)){
                                        if (dia==31){
                                                dia = 1;
                                                mes++;
                                        } else {
                                                dia++;
                                        }
                                }
                                if ((dia!=1)&&(mes==12)){
                                        if (dia==31){
                                                dia = 1;
                                                mes = 1;
                                                anio++;
                                        } else {
                                                dia++;
                                        }
                                }
                        }
        }
                
         }
         
         fechaInc = (anio*10000)+(mes*100)+(dia);                                   //10000*aa + 100*mm + dd
         return fechaInc;         
        
}

//Funcion para ajustar la hora y la fecha del sistema
void AjustarTiempoSistema(unsigned long longHora, unsigned long longFecha, unsigned char *tramaTiempoSistema){

     unsigned char hora;
     unsigned char minuto;
     unsigned char segundo;
     unsigned char dia;
     unsigned char mes;
     unsigned char anio;

     hora = (char)(longHora / 3600);
     minuto = (char)((longHora%3600) / 60);
     segundo = (char)((longHora%3600) % 60);

     anio = (char)(longFecha / 10000);
     mes = (char)((longFecha%10000) / 100);
     dia = (char)((longFecha%10000) % 100);
     
     tramaTiempoSistema[0] = anio;
     tramaTiempoSistema[1] = mes;
     tramaTiempoSistema[2] = dia;
     tramaTiempoSistema[3] = hora;
     tramaTiempoSistema[4] = minuto;
     tramaTiempoSistema[5] = segundo;
         
}
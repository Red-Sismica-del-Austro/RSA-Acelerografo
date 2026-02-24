// Libreria para controlar el ADXL355

#include "ADXL355_SPI.h"

unsigned short axisAddresses[] = {XDATA3, XDATA2, XDATA1, YDATA3, YDATA2, YDATA1, ZDATA3, ZDATA2, ZDATA1};


void ADXL355_init(short tMuestreo){
    ADXL355_write_byte(Reset,0x52);                                             //Resetea el dispositivo
    Delay_ms(10);
    ADXL355_write_byte(POWER_CTL, DRDY_OFF|STANDBY);
    ADXL355_write_byte(Range, _2G);
    switch (tMuestreo){
           case 1:
                ADXL355_write_byte(Filter, NO_HIGH_PASS_FILTER|_62_5_Hz);       //ODR=250Hz 1
                break;
           case 2:
                ADXL355_write_byte(Filter, NO_HIGH_PASS_FILTER|_31_25_Hz);      //ODR=125Hz 2
                break;
           case 4:
                ADXL355_write_byte(Filter, NO_HIGH_PASS_FILTER|_15_625_Hz);     //ODR=62.5Hz 4
                break;
           case 8:
                ADXL355_write_byte(Filter, NO_HIGH_PASS_FILTER|_7_813_Hz );     //ODR=31.25Hz 8
                break;
    }
}


void ADXL355_write_byte(unsigned char address, unsigned char value){
     address = (address<<1)&0xFE;
     CS_ADXL355=0;
     SPI2_Write(address);
     SPI2_Write(value);
     CS_ADXL355=1;
}


unsigned char ADXL355_read_byte(unsigned char address){
     unsigned char value = 0x00;
     address=(address<<1)|0x01;
     CS_ADXL355=0;
     SPI2_Write(address);
     value=SPI2_Read(0);
     CS_ADXL355=1;
     return value;
}


unsigned int ADXL355_read_data(unsigned char *vectorMuestra){
     unsigned short j;
     unsigned short muestra;
     if((ADXL355_read_byte(Status)&0x01)==1){                                 //Verifica que el bit DATA_RDY del registro Status este en alto
          CS_ADXL355=0;
          for (j=0;j<9;j++){
              muestra = ADXL355_read_byte(axisAddresses[j]);
              vectorMuestra[j] = muestra;
          }
          CS_ADXL355=1;
     } else {
         for (j=0;j<9;j++){
             vectorMuestra[j] = 0;
         }
     }
     return;
}


unsigned int ADXL355_read_FIFO(unsigned char *vectorFIFO){
     unsigned char add;
     add = (FIFO_DATA<<1)|0x01;
     CS_ADXL355 = 0;
     SPI2_Write(add);
     //DATA X
     vectorFIFO[0] = SPI2_Read(0);
     vectorFIFO[1] = SPI2_Read(1);
     vectorFIFO[2] = SPI2_Read(2);
     //DATA Y
     vectorFIFO[3] = SPI2_Read(0);
     vectorFIFO[4] = SPI2_Read(1);
     vectorFIFO[5] = SPI2_Read(2);
     //DATA Z
     vectorFIFO[6] = SPI2_Read(0);
     vectorFIFO[7] = SPI2_Read(1);
     vectorFIFO[8] = SPI2_Read(2);
     CS_ADXL355 = 1;
     Delay_us(5);
     return;
}
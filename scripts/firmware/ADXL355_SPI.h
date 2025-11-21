#ifndef ADXL355_SPI_H
#define ADXL355_SPI_H

/*       Device Addressing      */

#define ADXL355_Write                                                                    0x3A  //La direccci�n del i2c es 0x1D, pues asel est a en 0.
#define ADXL355_Read                                                                     0x3B


/*      Register names      */

#define DEVID_AD                                                                         0x00
#define DEVID_MST                                                                        0x01
#define PARTID                                                                           0x02
#define REVID                                                                            0x03
#define Status                                                                           0x04
#define FIFO_ENTRIES                                                                     0x05
#define TEMP2                                                                            0x06
#define TEMP1                                                                            0x07
#define XDATA3                                                                           0x08
#define XDATA2                                                                           0x09
#define XDATA1                                                                           0x0A
#define YDATA3                                                                           0x0B
#define YDATA2                                                                           0x0C
#define YDATA1                                                                           0x0D
#define ZDATA3                                                                           0x0E
#define ZDATA2                                                                           0x0F
#define ZDATA1                                                                           0x10
#define FIFO_DATA                                                                        0x11
#define OFFSET_X_H                                                                       0x1E
#define OFFSET_X_L                                                                       0x1F
#define OFFSET_Y_H                                                                       0x20
#define OFFSET_Y_L                                                                       0x21
#define OFFSET_Z_H                                                                       0x22
#define OFFSET_Z_L                                                                       0x23
#define ACT_EN                                                                           0x24
#define ACT_THRESH_H                                                                     0x25
#define ACT_THRESH_L                                                                     0x26
#define ACT_COUNT                                                                        0x27
#define Filter                                                                           0x28
#define FIFO_SAMPLES                                                                     0x29
#define INT_MAP                                                                          0x2A
#define Sync                                                                             0x2B
#define Range                                                                            0x2C
#define POWER_CTL                                                                        0x2D
#define SELF_TEST                                                                        0x2E
#define Reset                                                                            0x2F


/*FILTER SETTINGS REGISTER  Filter*/
//HPF:
#define NO_HIGH_PASS_FILTER 0x00
#define _247ODR             0x10
#define _62_084ODR          0x20
#define _15_545ODR          0x30
#define _3_862ODR           0x40
#define _0_954ODR           0x50
#define _0_238ODR           0x60
//LPF:
#define _1000_Hz            0x00
#define _500_Hz             0x01
#define _250_Hz             0x02
#define _125_Hz             0x03
#define _62_5_Hz            0x04    //250Hz        //1
#define _31_25_Hz           0x05    //125Hz        //2
#define _15_625_Hz          0x06    //62.5Hz       //4
#define _7_813_Hz           0x07    //31.25Hz      //8
#define _3_906_Hz           0x08
#define _1_953_Hz           0x09
#define _0_977_Hz           0x0A


/*DATA SYNCHRONIZATION REGISTER  Sync */
#define EXT_CLK_ON          0x04
#define EXT_CLK_OFF         0x00
#define INT_SYNC            0x00
#define EXT_SYNC_NO_INT_FILT  0x01
#define EXT_SYNC_INT_FILT   0x02

/*I2C SPEED, INTERRUPT POLARITY, AND RANGE REGISTER  Range */
#define I2C_HS              0x80
#define I2C_FAST            0x00
#define INT_ACTIVE_LOW      0x40
#define INT_ACTIVE_HIGH     0x00
#define _2G                 0x01
#define _4G                 0x02
#define _8G                 0x03


/*       POWER CONTROL REGISTER    POWER_CTL   */
#define DRDY_OFF            0x04
#define DRDY_ON             0x00
#define TEMP_OFF            0x02
#define TEMP_ON             0x00
#define STANDBY             0x01
#define MEASURING           0x00


///////////////////////////////////////////   Definicion de pines   ///////////////////////////////////////////
sbit CS_ADXL355 at LATA3_bit;

/////////////////////////////////////////// Definicion de funciones ///////////////////////////////////////////
void ADXL355_init(short tMuestreo);
void ADXL355_write_byte(unsigned char address, unsigned char value);
unsigned char ADXL355_read_byte(unsigned char address);
unsigned int ADXL355_read_data(unsigned char *vectorMuestra);
unsigned int ADXL355_read_FIFO(unsigned char *vectorFIFO);

#endif
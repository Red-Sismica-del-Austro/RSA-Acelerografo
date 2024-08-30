//***********************************************************************************************************
// Compilar libreria:
// 1. Compila el código fuente en un archivo objeto:
//    gcc -c -o /home/rsa/librerias/detector-eventos/detector_eventos.o /home/rsa/librerias/detector-eventos/detector_eventos.c
// 2. Crea una biblioteca compartida:
//    gcc -shared -o /home/rsa/librerias/detector-eventos/libdetector_eventos.so /home/rsa/librerias/detector-eventos/detector_eventos.o
//***********************************************************************************************************

#include <time.h>
#include <sys/time.h>

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <errno.h>
// Para operaciones en la deteccion de eventos
#include <math.h>
#include <stdbool.h>

// Libreria Colocada
#include "detector_eventos.h"

// Define los parametros del metodo STA/LTA en segundos multiplicado por la frecuencia de muestreo
#define fSample 250
#define n_STA 125   // 0.5 segundos * fSample
#define n_LTA 12500 // 50 segundos *fSample
#define valTrigger 4
#define valDetrigger 2
// Tiempos en segundos para agregar antes y despues de la deteccion de un evento
#define timePreEvent 2
#define timePostEvent 2
#define ventanaEvento 30
// Se considera un tiempo extra entre eventos, de esta forma si ocurren dos eventos cercanos
// se envia uno solo
#define timeEntreEventos 60

// Define los parametros del filtro FIR
// Maximo numero de datos de entrada en una llamada a la funcion
// Permite filtrar al mismo tiempo hasta este numero de muestras
#define MAX_INPUT_LEN 80
// Maxima longitud del filtro, maximo numero de coeficientes que permite
#define MAX_FLT_LEN 64
// Dimension para almacenar las muestras de entrada
#define BUFFER_LEN (MAX_FLT_LEN - 1 + MAX_INPUT_LEN)
// Vector para almacenar las muestras de entrada
double vectorMuestras[BUFFER_LEN];
// Coeficientes para un filtro FIR pasa alto de frecuencia 1Hz con ventana Kaiser de orden 63 que da 64 coeficientes, beta = 5
// La frecuencia de muestreo es 250 Hz y se utilizo la herramienta fdatool Matlab (Se llama con filterDesigner)
#define FILTER_LEN 64
double coeficientes[FILTER_LEN] = {
    -0.0002607120740672, -0.0003948152676513, -0.0005637464517517, -0.0007728729580176,
    -0.001028015561932, -0.001335475734722, -0.00170207452642, -0.00213520803273,
    -0.002642925970776, -0.003234042043891, -0.003918287787646, -0.004706525881195,
    -0.005611045142428, -0.006645968660266, -0.007827820476902, -0.00917631779097,
    -0.01071548972453, -0.01247527892566, -0.01449387435105, -0.01682118197898,
    -0.01952412263954, -0.02269497075544, -0.02646496949405, -0.03102756147795,
    -0.03668020238467, -0.0439047613983, -0.05353560928689, -0.06715178559783,
    -0.08814138938659, -0.1253204018087, -0.2110265970226, -0.6363397139696,
    0.6363397139696, 0.2110265970226, 0.1253204018087, 0.08814138938659,
    0.06715178559783, 0.05353560928689, 0.0439047613983, 0.03668020238467,
    0.03102756147795, 0.02646496949405, 0.02269497075544, 0.01952412263954,
    0.01682118197898, 0.01449387435105, 0.01247527892566, 0.01071548972453,
    0.00917631779097, 0.007827820476902, 0.006645968660266, 0.005611045142428,
    0.004706525881195, 0.003918287787646, 0.003234042043891, 0.002642925970776,
    0.00213520803273, 0.00170207452642, 0.001335475734722, 0.001028015561932,
    0.0007728729580176, 0.0005637464517517, 0.0003948152676513, 0.0002607120740672};
// Variable con la ruta y el nombre del archivo temporal para guardar la informacion de cada evento detectado
// Se guarda solo la fecha long, la hora en segundos del inicio del evento y su duracion
// Con cada evento nuevo se sobreescribe la informacion, antes se debe leer en el programa de Python
// static char *fileNameEventosDetectados = "/home/rsa/TMP/EventosDetectados.tmp";

// variable para almacenar el comando externo a ejecutar:
char command[100];

// *********************************************************************************************
// Metodo para determinar si existe o no un evento sismico
// Utiliza el algoritmo STA/LTA recursivo
// *********************************************************************************************
void DetectarEvento(unsigned char *tramaD)
{
    // Variables para guardar los datos de evento detectado en el archivo temporal
    static FILE *obj_fp;
    //    static char* fileNameEventosDetectados = "EventoDetectado.tmp";
    // Variable para bucle
    unsigned int indiceVector;
    // Variables para obtener el tiempo en funcion de los datos recibidos
    char anio, mes, dia, horas, minutos, segundos;
    unsigned long horaLong, fechaLong;
    static unsigned long fechaLongAnt = 0, fechaActual = 0;
    static bool isPrimeraFecha = true;
    // Variables para obtener la aceleracion de los tres canales
    // aunque actualmente se esta usando solo uno para la deteccion
    double valAceleracionX, valAceleracionY, valAceleracionZ;
    // Variables para almacenar los resultados del metodo de deteccion STA/LTA
    double resul_STA, resul_LTA, resul_STA_LTA;
    // Variables para determinar el inicio y fin de un evento detectado
    // Tambien se almacena el ultimo evento y su duracion, porque en el caso de que
    // se detecte dos eventos cercanos, la idea es hacerlo uno solo, en funcion del
    // tiempo entre eventos definido al inicio del programa
    char valEvento;
    static bool isEvento = false, enviarEvt = false;
    static unsigned long tiempoInitEvtAct, tiempoInitEvtAnt, tiempoFinEvtAct, tiempoFinEvtAnt;
    static unsigned long fechaInitEvtAct, fechaInitEvtAnt;
    static unsigned int duracionEvtAct, duracionEvtAnt, tiempoPreEvento;
    // Variable para almacenar el dato filtrado
    double resul_filtro;

    // Para obtener el tiempo de inicio y fin
    //    struct timespec now;
    //    unsigned long msecInicial, msecFinal, diff;

    // Primero obtiene el tiempo actual que esta en los ultimos 6 bytes del vector
    anio = tramaD[NUM_ELEMENTOS - 6];
    mes = tramaD[NUM_ELEMENTOS - 5];
    dia = tramaD[NUM_ELEMENTOS - 4];
    fechaLong = 10000 * anio + 100 * mes + dia;
    // Si es la primera vez, actualiza todas las fechas
    if (isPrimeraFecha == true)
    {
        isPrimeraFecha = false;
        fechaActual = fechaLong;
        fechaLongAnt = fechaLong;
        // Desde la segunda entrada solo analiza si hay cambio de fecha
        // Es necesario tener almacenada la fecha de un dia anterior, por
        // si acaso un evento con el tiempo de pre event comience en el dia
        // anterior
    }
    else
    {
        // Si hubo cambio de fecha, actualiza primero la fecha anterior
        // y luego la fecha actual
        if (fechaActual != fechaLong)
        {
            fechaLongAnt = fechaActual;
            fechaActual = fechaLong;
        }
    }

    //    printf ("Anio %d Mes %d Dia %d \n", anio, mes, dia);
    horas = tramaD[NUM_ELEMENTOS - 3];
    minutos = tramaD[NUM_ELEMENTOS - 2];
    segundos = tramaD[NUM_ELEMENTOS - 1];
    horaLong = 3600 * horas + 60 * minutos + segundos;
    //    printf ("Horas %d Minutos %d Segundos %d \n", horas, minutos, segundos);

    // Obtiene el tiempo de inicio en ms
    //    clock_gettime( CLOCK_REALTIME, &now );
    // Si se quisiera los segundos sec = (int)now.tv_sec;
    //    msecInicial = (int)now.tv_nsec / 1000000;
    //    printf ("Tiempo Inicio %lu \n", msecInicial);

    // Recorre todo el vector, quitando los 6 bytes del tiempo
    indiceVector = 0;
    while (indiceVector < (NUM_ELEMENTOS - 6))
    {
        // Cada 10 bytes se tiene el inicio de un muestreo
        // Por lo tanto, el primer byte es un indicador de nuevo muestreo
        if (indiceVector % 10 == 0)
        {
            // Llama al metodo para obtener la aceleracion con los valores del eje X
            //            printf ("Indice %lu Trama %d Byte1 %d Byte2 %d Byte3 %d \n", indiceVector, tramaD[indiceVector], tramaD[indiceVector + 1], tramaD[indiceVector + 2], tramaD[indiceVector + 3]);
            valAceleracionX = ObtenerValorAceleracion(tramaD[indiceVector + 1], tramaD[indiceVector + 2], tramaD[indiceVector + 3]);
            //            printf ("Aceleracion X %0.8f \n", valAceleracionX);

            //            printf ("Indice %lu Trama %d Byte1 %d Byte2 %d Byte3 %d \n", indiceVector, tramaD[indiceVector], tramaD[indiceVector + 4], tramaD[indiceVector + 5], tramaD[indiceVector + 6]);
            valAceleracionY = ObtenerValorAceleracion(tramaD[indiceVector + 4], tramaD[indiceVector + 5], tramaD[indiceVector + 6]);
            //            printf ("Aceleracion Y %0.8f \n", valAceleracionY);

            //            printf ("Indice %lu Trama %d Byte1 %d Byte2 %d Byte3 %d \n", indiceVector, tramaD[indiceVector], tramaD[indiceVector + 7], tramaD[indiceVector + 8], tramaD[indiceVector + 9]);
            valAceleracionZ = ObtenerValorAceleracion(tramaD[indiceVector + 7], tramaD[indiceVector + 8], tramaD[indiceVector + 9]);
            //            printf ("Aceleracion Z %0.8f \n", valAceleracionZ);

            // Llama al metodo para realizar el filtrado
            // El valor filtrado se almacena en el vector resul_filtro
            resul_filtro = calcular_Salida_Filtro(coeficientes, valAceleracionY, FILTER_LEN);
            //            resul_filtro = valAceleracionY;

            // Envia el numero actual para el calculo del valor STA
            resul_STA = calcular_STA_recursivo(resul_filtro);
            // Envia el numero actual para el calculo del valor LTA
            resul_LTA = calcular_LTA_recursivo(resul_filtro);
            // Calcula la relacion entre los dos valores y si es o no evento
            resul_STA_LTA = calcularRelacion_LTA_STA(resul_STA, resul_LTA);
            valEvento = calcularIsEvento(resul_STA_LTA);

            // Si esta activa la bandera de enviar evento, analiza si ya se cumplio el tiempo extra
            // y que no hayan nuevos eventos y guarda la informacion en el archivo temporal
            if (enviarEvt == true && horaLong >= (tiempoFinEvtAnt + timeEntreEventos) && valEvento == 0)
            {
                enviarEvt = false;
                printf("Evento detectado: Fecha %lu | Hora inicio %lu | Duracion %lu | HoraActual %lu \n", fechaInitEvtAnt, tiempoInitEvtAnt, duracionEvtAnt, horaLong);
            }

            // Si aun no se han detectado eventos y el dato es 1, significa el comienzo de un evento
            if (isEvento == false && valEvento == 1)
            {
                // Coloca la bandera de evento en True, de aqui se desactiva cuando valEvento es 0
                isEvento = true;
                // Actualiza el tiempo inicial del evento, si no hay eventos pendientes por enviar
                // es directamente el tiempo actual
                if (enviarEvt == false)
                {
                    tiempoInitEvtAct = horaLong;
                    fechaInitEvtAct = fechaLong;
                    // Caso contrario es el tiempo de inicio del ultimo evento
                }
                else
                {
                    tiempoInitEvtAct = tiempoInitEvtAnt;
                    fechaInitEvtAct = fechaInitEvtAnt;
                }

                // printf("Hora actual %lu Fecha actual %lu Inicio evento detectado %lu %lu \n", horaLong, fechaLong, fechaInitEvtAct, tiempoInitEvtAct);
                printf("Inicio deteccion: Hora inicio: %lu | Hora actual: %lu \n", tiempoInitEvtAct, horaLong);

                //************************************************************************
                // Aqui puede ir el metodo para publicar el evento con parametro horaLong
                //************************************************************************
                sprintf(command, "python3 /home/rsa/ejecutables/publicar_evento_mqtt.py %lu %lu %lu", fechaLong, horaLong, 1);
                system(command);
            }
            // Si hay un evento actualmente y valEvento es 0, significa fin del evento
            if (isEvento == true && valEvento == 0)
            {
                isEvento = false;
                // Actualiza el tiempo final del evento
                // printf("Fin deteccion de evento %lu \n", horaLong);
                // printf("Final deteccion: Hora fin: %lu \n", horaLong);
                tiempoFinEvtAct = horaLong;

                // Ademas se analiza la ventana de tiempo de eventos (aproximadamente 20 segundos)
                // Esto es para agregar un tiempo antes y despues de la deteccion automatica y asi
                // asegurar toda la infomacion
                // Primero calcula la duracion del evento, lo logico es que el tiempo final sea mayor
                // que el tiempo inicial, pero si es lo contrario significa que hubo un evento justo en
                // el cambio de dia
                if (tiempoFinEvtAct >= tiempoInitEvtAct)
                {
                    duracionEvtAct = tiempoFinEvtAct - tiempoInitEvtAct;
                    // Si el tiempo inicial es mayor que el final, significa que comenzo en el dia anterior
                    // por lo que se suma los 86400 (24*3600) al tiempo final
                }
                else
                {
                    duracionEvtAct = 86400 + tiempoFinEvtAct - tiempoInitEvtAct;
                }
                // Con la duracion del evento, se obtiene cuantos segundos hay que restar al tiempo de
                // inicio, esto es para agregar un tiempo de pre evento
                // Si la ventana de 20 segundos es mayor que el evento (que es lo mas logico), resta y divide
                // para dos para sacar el tiempo de pre evento
                if (ventanaEvento >= duracionEvtAct)
                {
                    tiempoPreEvento = (unsigned long)((ventanaEvento - duracionEvtAct) / 2);
                    // Caso contrario, agrega el tiempo por defecto de pre evento
                }
                else
                {
                    tiempoPreEvento = timePreEvent;
                }
                // Finalmente resta al tiempo de inicio
                // Si el tiempo de inicio es mayor que el de pre evento solo realiza la resta
                if (tiempoInitEvtAct >= tiempoPreEvento)
                {
                    tiempoInitEvtAct = tiempoInitEvtAct - tiempoPreEvento;
                    // Caso contrario significa que con la resta se tiene el tiempo del dia anterior
                    // Entonces antes se suma los 86400 (3600*24)
                }
                else
                {
                    tiempoInitEvtAct = 86400 + tiempoInitEvtAct - tiempoPreEvento;
                    // En este caso tambien hay que actualizar la fecha long a la anterior
                    fechaInitEvtAct = fechaLongAnt;
                }
                // Algo similar para el tiempo fin de evento
                if ((tiempoFinEvtAct + tiempoPreEvento) >= 86400)
                {
                    tiempoFinEvtAct = tiempoFinEvtAct + tiempoPreEvento - 86400;
                }
                else
                {
                    tiempoFinEvtAct = tiempoFinEvtAct + tiempoPreEvento;
                }

                printf("Evento procesado: Fecha %lu | Hora inicio %lu | Hora fin %lu \n", fechaInitEvtAct, tiempoInitEvtAct, tiempoFinEvtAct);

                // Activa la bandera para enviar el evento
                enviarEvt = true;
                // Ademas actualiza los tiempos al evento anterior
                tiempoInitEvtAnt = tiempoInitEvtAct;
                tiempoFinEvtAnt = tiempoFinEvtAct;
                fechaInitEvtAnt = fechaInitEvtAct;
                // Tambien la duracion del evento
                if (tiempoFinEvtAnt >= tiempoInitEvtAnt)
                {
                    duracionEvtAnt = tiempoFinEvtAnt - tiempoInitEvtAnt;
                }
                else
                {
                    duracionEvtAnt = 86400 + tiempoFinEvtAnt - tiempoInitEvtAnt;
                }
            }

            //            printf ("Valor STA %f LTA %f STA/LTA %f \n", resul_STA, resul_LTA, resul_STA_LTA);
            // Aumenta en 10 el indiceVector dado que se utilizaron los 9 bytes de los datos y 1 del indicador
            indiceVector += 10;
        }
        //        printf("%d \n", tramaD[indiceVector]);
    }

    // Obtiene el tiempo final, luego de realizar todas las operaciones
    //    clock_gettime( CLOCK_REALTIME, &now );
    // Si se quisiera los segundos sec = (int)now.tv_sec;
    //    msecFinal = (int)now.tv_nsec / 1000000;
    //    printf ("Tiempo Final (ms) %lu \n", msecFinal);
    //    diff = msecFinal - msecInicial;
    //    printf("Tiempo Total Operaciones (ms) %lu \n", diff);
}
// *********************************************************************************************
// ************************** Fin Metodo DetectarEvento ****************************************
// *********************************************************************************************

// *********************************************************************************************
// Metodo para obtener el valor de la aceleracion para los 3 ejes a partir de sus 3 bytes
// *********************************************************************************************
float ObtenerValorAceleracion(char byte1, char byte2, char byte3)
{
    signed long axisValue;
    //    signed long valNegado;
    float aceleracion;

    //    printf ("Byte 1 %d Byte 2 %d Byte 3 %d \n", byte1, byte2, byte3);

    // Obtiene el valor de aceleraciion del eje correspondiente
    axisValue = ((byte1 << 12) & 0xFF000) + ((byte2 << 4) & 0xFF0) + ((byte3 >> 4) & 0xF);
    //    printf ("ValAxes %lu \n", axisValue);
    // Aplica el complemento a 2
    if (axisValue >= 0x80000)
    {
        // Se descarta el bit 20 que indica el signo (1 = negativo)
        //        printf ("Signo negativo %lu ", axisValue);
        axisValue = axisValue & 0x7FFFF;
        //        printf ("paso1 %li ", axisValue);
        //        valNegado = (~axisValue) + 1;
        //        printf ("negado %li ", valNegado);
        axisValue = (signed long)(-1 * (((~axisValue) + 1) & 0x7FFFF));
        //        printf ("nuevo %li \n", axisValue);

        //        aceleracion = (double) ((signed long) (axisValue) * (980/pow(2,18)));
        //        printf ("Aceleracion X %0.8f \n", aceleracion);

        //        aceleracion = axisValue * (980/pow(2,18));
        //        printf ("Aceleracion X %0.8f \n", aceleracion);
    }
    //    printf ("ValAxes %lu \n", axisValue);

    // Calcula la aceleracion en gales (float)
    aceleracion = (double)(axisValue * (980 / pow(2, 18)));
    //    printf ("Aceleracion X %0.8f \n", aceleracion);

    // Devuelve el valor calculado
    return aceleracion;
}
// *********************************************************************************************
// ********************** Fin Metodo ObtenerValorAceleracion ***********************************
// *********************************************************************************************

// *********************************************************************************************
// Metodo para iniciar el filtro FIR
// Consiste en iniciar en 0 el vectorMuestras
// *********************************************************************************************
void firFloatInit(void)
{
    memset(vectorMuestras, 0, sizeof(vectorMuestras));
}
// *********************************************************************************************
// *************************** Fin Metodo firFloatInit *****************************************
// *********************************************************************************************

// *********************************************************************************************
// Metodo que permite aplicar un filtro FIR para un solo dato de entrada, devuelve el valor filtrado
// *********************************************************************************************
float calcular_Salida_Filtro(double *coeficientes, double valEntrada, int filterLength)
{
    // Variable para acumular la suma de las multiplicaciones de las entradas por los coeficientes (convolucion)
    double valFiltrado;
    // Puntero para los coeficientes
    double *ptrCoeficientes;
    // Puntero para los datos de entrada
    double *ptrInput;
    int indiceFor;

    // Copia las muestras de entrada en el vector de datos, en la posicion final en funcion del # de coeficientes
    // memcpy(&vectorMuestras[filterLength - 1], dataInput, longitudInput*sizeof(double));
    vectorMuestras[filterLength - 1] = valEntrada;
    //    printf ("Muestra 63 %f \n", vectorMuestras[filterLength - 1]);

    // Aplica el filtro al dato de entrada
    ptrCoeficientes = coeficientes;
    ptrInput = &vectorMuestras[filterLength - 1];
    valFiltrado = 0;
    for (indiceFor = 0; indiceFor < filterLength; indiceFor++)
    {
        valFiltrado += (*ptrCoeficientes++) * (*ptrInput--);
        //        printf ("Filtro %f Muestra %f Multi %f Res %f ", datoFiltro, datoMuestra, multiplicacion, valFiltrado);
    }

    // Desplaza las muestras de entrada al inicio para utilizarlas en el siguiente calculo
    memmove(&vectorMuestras[0], &vectorMuestras[1], (filterLength - 1) * sizeof(double));

    return valFiltrado;
}
// *********************************************************************************************
// *********************** Fin Metodo calcular_Salida_Filtro ***********************************
// *********************************************************************************************

// *********************************************************************************************
// Metodo que permite calcular el valor de STA recursivo, depende del valor calculado en la iteracion
// anterior y una constante que depende del numero de muestras del STA (n_STA)
// Solo necesita como parametro la nueva muestra en tipo float y declarar al inicio el numero
// de muestras sobre las que se desea hacer el calculo. Ejemplo: #define n_STA = 5
// *********************************************************************************************
float calcular_STA_recursivo(float numRecibido)
{
    // Se almacena el valor anterior de STA porque se requiere en la siguiente iteracion
    static float valSTA_ant = 0;
    // Variable que cuenta las muestras computadas, esto es porque mientras no se llegue a n_LTA muestras
    // Se debe retornar el valor de 0. Aun no se pueden considerar validos los datos
    static unsigned long contadorMuestras = 0;
    // Variable para elevar al cuadrado el numero recibido
    float numCuad_STA;
    // Variable que devuelve el valor calculado de STA
    float valSTA;

    // Primero eleva al cuadrado el numero
    numCuad_STA = pow(numRecibido, 2);

    // Aplica la fórmula del cálculo STA recursivo
    valSTA = valSTA_ant + (double)((numCuad_STA - valSTA_ant) / n_STA);
    // Guarda este valor calculado para la proxima iteracion
    valSTA_ant = valSTA;

    //    printf ("Val STA %f \n", valSTA);

    // Solo si ya se llego al numero n_LTA (OJO LTA) devuelve el valor
    // EL aumento del contador se hace solo hasta llegar al numero n_LTA
    // Porque de no seguiria aumentando el contador de forma indeterminada
    if ((contadorMuestras + 1) >= n_LTA)
    {
        return valSTA;
        // Caso contrario aumenta en 1 el contador y devuelve 0
    }
    else
    {
        contadorMuestras++;
        return 0;
    }
}
// *********************************************************************************************
// ********************** Fin Metodo calcular_STA_recursivo ************************************
// *********************************************************************************************

// *********************************************************************************************
// Metodo que permite calcular el valor de LTA recursivo, depende del valor calculado en la iteracion
// anterior y una constante que depende del numero de muestras del LTA (n_LTA)
// Solo necesita como parametro la nueva muestra en tipo float y declarar al inicio el numero
// de muestras sobre las que se desea hacer el calculo. Ejemplo: #define n_LTA = 5
// *********************************************************************************************
float calcular_LTA_recursivo(float numRecibido)
{
    // Se almacena el valor anterior de STA porque se requiere en la siguiente iteracion
    static float valLTA_ant = 0;
    // Variable que cuenta las muestras computadas, esto es porque mientras no se llegue a n_LTA muestras
    // Se debe retornar el valor de 0. Aun no se pueden considerar validos los datos
    static unsigned long contadorMuestras = 0;
    // Variable para elevar al cuadrado el numero recibido
    float numCuad_LTA;
    // Variable que devuelve el valor calculado de STA
    float valLTA;

    // Primero eleva al cuadrado el numero
    numCuad_LTA = pow(numRecibido, 2);

    // Aplica la fórmula del cálculo STA recursivo
    valLTA = valLTA_ant + (double)((numCuad_LTA - valLTA_ant) / n_LTA);
    // Guarda este valor calculado para la proxima iteracion
    valLTA_ant = valLTA;

    //    printf ("Val LTA %f \n", valLTA);

    // Solo si ya se llego al numero n_LTA (OJO LTA) devuelve el valor
    // EL aumento del contador se hace solo hasta llegar al numero n_LTA
    // Porque de no seguiria aumentando el contador de forma indeterminada
    if ((contadorMuestras + 1) >= n_LTA)
    {
        return valLTA;
        // Caso contrario aumenta en 1 el contador y devuelve 0
    }
    else
    {
        contadorMuestras++;
        return 0;
    }
}
// *********************************************************************************************
// ********************** Fin Metodo calcular_STA_recursivo ************************************
// *********************************************************************************************

// *********************************************************************************************
// Metodo que permite calcular la relacion entre los dos valores STA y LTA, en caso de que alguno
// de ellos sea 0, devuelve 0
// *********************************************************************************************
float calcularRelacion_LTA_STA(float valSTA, float valLTA)
{
    float sta_lta = 0;

    // Solo si ambos valores son distinto de 0, calcula la relacion
    // Si alguno es 0 significa que aun no se ha completado el numero de datos para el calculo
    if (valSTA != 0 && valLTA != 0)
    {
        sta_lta = valSTA / valLTA;
    }

    return sta_lta;
}
// *********************************************************************************************
// *************************** Fin Metodo calcularRelacion_LTA_STA *****************************
// *********************************************************************************************

// *********************************************************************************************
// Metodo que determina si hay o no evento en funcion del resultado de la relacion STA/LTA y los
// valores de trigger y detrigger. Cuando STA/LTA es >= trigger comienza el evento y termina
// cuando STA/LTA es menor que detrigger
// *********************************************************************************************
char calcularIsEvento(float resul_STA_LTA)
{
    // Al inicio del programa no hay evento
    static char isEvento = 0;

    // Si no hay evento, analiza cuando supera el trigger al valor STA/LTA
    if (isEvento == 0)
    {
        // Si supera significa comienzo del evento
        if (resul_STA_LTA >= valTrigger)
        {
            isEvento = 1;
        }
        // Caso contrario, si hay evento, solo termina cuando STA/LTA es menor que detrigger
    }
    else
    {
        if (resul_STA_LTA < valDetrigger)
        {
            isEvento = 0;
        }
    }

    return isEvento;
}
// *********************************************************************************************
// ******************************** Fin Metodo calcularIsEvento **********************************
// *********************************************************************************************



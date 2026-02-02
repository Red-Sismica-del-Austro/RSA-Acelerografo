/*
gcc -Wall -o c_writer c_writer.c -lwiringPi
*/

#define _POSIX_C_SOURCE 200809L
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <fcntl.h>
#include <signal.h>
#include <errno.h>
#include <sys/stat.h>
#include <wiringPi.h>

#define PIPE_NAME "/tmp/my_pipe"
#define BUFFER_SIZE 2506
#define P1 0  // Esto corresponde al GPIO 17 en la Raspberry Pi
#define LedTest 26 

char buffer[BUFFER_SIZE];

void handle_sigpipe(int sig) {
    printf("SIGPIPE caught. Reader probably disconnected.\n");
}

void EscribirPipe(void) {
    int fd;

    digitalWrite(LedTest, !digitalRead(LedTest));
    printf("Interrupción detectada. Escribiendo en el pipe...\n");

    printf("Abriendo pipe para escritura...\n");
    fd = open(PIPE_NAME, O_WRONLY | O_NONBLOCK);
    
    if (fd == -1) {
        if (errno == ENXIO) {
            printf("No hay lector. No se puede escribir.\n");
            return;
        } else {
            perror("Error al abrir el pipe");
            return;
        }
    }

    printf("Escribiendo datos...\n");
    ssize_t bytes_written = write(fd, buffer, BUFFER_SIZE);
    
    if (bytes_written == -1) {
        if (errno == EPIPE) {
            printf("El lector se desconectó.\n");
        } else {
            perror("Error al escribir en el pipe");
        }
    } else {
        printf("Escritos %zd bytes\n", bytes_written);
    }

    close(fd);
}

int main() {
    // Llenar el buffer con datos de ejemplo
    memset(buffer, 'A', BUFFER_SIZE);

    // Configurar el manejador de SIGPIPE
    signal(SIGPIPE, handle_sigpipe);

    // Crear el named pipe
    if (mkfifo(PIPE_NAME, 0666) == -1) {
        if (errno != EEXIST) {
            perror("Error al crear el pipe");
            exit(1);
        }
    }

    // Configurar wiringPi
    if (wiringPiSetup() == -1) {
        printf("Error al inicializar wiringPi\n");
        return 1;
    }

    pinMode(P1, INPUT);
    pinMode(LedTest, OUTPUT);

    if (wiringPiISR(P1, INT_EDGE_RISING, &EscribirPipe) < 0) {
        printf("Error al configurar la interrupción\n");
        return 1;
    }

    printf("Esperando interrupciones. Presiona Ctrl+C para salir.\n");

    // Mantener el programa en ejecución
    while(1) {
        sleep(1);
    }

    return 0;
}

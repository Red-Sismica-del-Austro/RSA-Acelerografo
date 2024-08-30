#include <stdio.h>
#include <stdlib.h>
#include <string.h>

int main() {
    // Acceder a las variables de entorno
    char* project_git_root = getenv("PROJECT_GIT_ROOT");
    char* project_local_root = getenv("PROJECT_LOCAL_ROOT");

    if (project_git_root != NULL && project_local_root != NULL) {
        printf("PROJECT_GIT_ROOT: %s\n", project_git_root);
        printf("PROJECT_LOCAL_ROOT: %s\n", project_local_root);

        // Concatenar PROJECT_LOCAL_CONFIG con "/configuracion_dispositivo.json"
        const char* file_suffix = "/configuracion/configuracion_dispositivo.json";

        // Declarar un buffer suficientemente grande para almacenar la cadena concatenada
        char configuracion_dispositivo_filename[100];

        // Inicializar la cadena
        strcpy(configuracion_dispositivo_filename, project_local_root);
        strcat(configuracion_dispositivo_filename, file_suffix);

        // Imprimir el resultado
        printf("configuracion_dispositivo_file: %s\n", configuracion_dispositivo_filename);
    } else {
        printf("Una o más variables de entorno no están definidas.\n");
    }

    return 0;
}

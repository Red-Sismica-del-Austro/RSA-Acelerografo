//***********************************************************************************************************
// Compilar libreria:
// 1. Compila el código fuente en un archivo objeto:
//    gcc -c -o /home/rsa/librerias/lector-json/lector_json.o /home/rsa/librerias/lector-json/lector_json.c
// 2. Crea una biblioteca compartida:
//    gcc -shared -o /home/rsa/librerias/lector-json/liblector_json.so /home/rsa/librerias/lector-json/lector_json.o
//***********************************************************************************************************

#include <stdio.h>
#include <stdlib.h>
#include <jansson.h>
#include "lector_json.h"

struct datos_config *compilar_json(const char *filename)
{
    FILE *file;
    struct datos_config *datos = (struct datos_config *)malloc(sizeof(struct datos_config));
    if (datos == NULL)
    {
        fprintf(stderr, "No se pudo asignar memoria para datos_config\n");
        return NULL;
    }

    json_t *root;
    json_error_t error;

    // Abrir el archivo JSON
    file = fopen(filename, "r");
    if (!file)
    {
        fprintf(stderr, "No se puede abrir el archivo %s\n", filename);
        free(datos);
        return NULL;
    }

    // Cargar el contenido del JSON en una estructura de datos
    root = json_loadf(file, 0, &error);
    fclose(file);

    if (!root)
    {
        fprintf(stderr, "Error al leer el archivo JSON: %s\n", error.text);
        free(datos);
        return NULL;
    }

    // Verifica que el contenido es un objeto
    if (!json_is_object(root))
    {
        fprintf(stderr, "El JSON no es un objeto\n");
        json_decref(root);
        free(datos);
        return NULL;
    }

    // Acceder a los datos
    json_t *dispositivo = json_object_get(root, "dispositivo");
    json_t *directorios = json_object_get(root, "directorios");

    if (json_is_object(dispositivo))
    {
        const char *id1 = json_string_value(json_object_get(dispositivo, "id"));
        if (id1)
        {
            snprintf(datos->id, sizeof(datos->id), "%s", id1);
        }
        const char *fuente_reloj1 = json_string_value(json_object_get(dispositivo, "fuente_reloj"));
        if (fuente_reloj1)
        {
            snprintf(datos->fuente_reloj, sizeof(datos->fuente_reloj), "%s", fuente_reloj1);
        }
        const char *deteccion_eventos1 = json_string_value(json_object_get(dispositivo, "deteccion_eventos"));
        if (deteccion_eventos1)
        {
            snprintf(datos->deteccion_eventos, sizeof(datos->deteccion_eventos), "%s", deteccion_eventos1);
        }
    }

    if (json_is_object(directorios))
    {
        const char *archivos_temporales1 = json_string_value(json_object_get(directorios, "archivos_temporales"));
        if (archivos_temporales1)
        {
            snprintf(datos->archivos_temporales, sizeof(datos->archivos_temporales), "%s", archivos_temporales1);
        }

        const char *registro_continuo1 = json_string_value(json_object_get(directorios, "registro_continuo"));
        if (registro_continuo1)
        {
            snprintf(datos->registro_continuo, sizeof(datos->registro_continuo), "%s", registro_continuo1);
        }

        const char *eventos_detectados1 = json_string_value(json_object_get(directorios, "eventos_detectados"));
        if (eventos_detectados1)
        {
            snprintf(datos->eventos_detectados, sizeof(datos->eventos_detectados), "%s", eventos_detectados1);
        }
    }

    // No olvides liberar la memoria
    json_decref(root);

    return datos;
}

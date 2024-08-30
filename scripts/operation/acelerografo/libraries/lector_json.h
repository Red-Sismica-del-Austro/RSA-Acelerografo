#ifndef LECTOR_JSON_H
#define LECTOR_JSON_H

struct datos_config
{
    char id[10];
    char fuente_reloj[10];
    char deteccion_eventos[10];
    char archivos_temporales[100];
    char registro_continuo[100];
    char eventos_detectados[100];
};

struct datos_config *compilar_json(const char *filename);

#endif
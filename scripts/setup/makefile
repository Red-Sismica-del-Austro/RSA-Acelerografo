# Definir directorios
#PROJECT_GIT_ROOT = /home/rsa/git/Acelerografo-RSA
#PROJECT_LOCAL_ROOT = /home/rsa/projects/acelerografo-rsa
LIB_DIR_SRC = $(PROJECT_GIT_ROOT)/scripts/operation/acelerografo/libraries
LIB_DIR_DST = $(PROJECT_LOCAL_ROOT)/scripts/acelerografo/libraries
EXE_DIR = $(PROJECT_LOCAL_ROOT)/scripts/acelerografo/ejecutables
PROG_DIR = $(PROJECT_GIT_ROOT)/scripts/operation/acelerografo

# Definir compiladores y opciones
CC = gcc
CFLAGS = -g -I$(LIB_DIR_DST) -L$(LIB_DIR_DST) -Wl,-rpath,$(LIB_DIR_DST) -lbcm2835 -lwiringPi -lm -ljansson

all: registro_continuo comprobar_registro extraer_evento reset_master 

# Compilar librerías
$(LIB_DIR_DST)/detector_eventos.o: $(LIB_DIR_SRC)/detector_eventos.c $(LIB_DIR_SRC)/detector_eventos.h
	$(CC) -c -o $(LIB_DIR_DST)/detector_eventos.o $(LIB_DIR_SRC)/detector_eventos.c
	cp $(LIB_DIR_SRC)/detector_eventos.h $(LIB_DIR_DST)/

$(LIB_DIR_DST)/libdetector_eventos.so: $(LIB_DIR_DST)/detector_eventos.o
	$(CC) -shared -o $(LIB_DIR_DST)/libdetector_eventos.so $(LIB_DIR_DST)/detector_eventos.o

$(LIB_DIR_DST)/lector_json.o: $(LIB_DIR_SRC)/lector_json.c $(LIB_DIR_SRC)/lector_json.h
	$(CC) -c -o $(LIB_DIR_DST)/lector_json.o $(LIB_DIR_SRC)/lector_json.c
	cp $(LIB_DIR_SRC)/lector_json.h $(LIB_DIR_DST)/

$(LIB_DIR_DST)/liblector_json.so: $(LIB_DIR_DST)/lector_json.o
	$(CC) -shared -o $(LIB_DIR_DST)/liblector_json.so $(LIB_DIR_DST)/lector_json.o

# Añadir reglas similares para otras librerías, si las hubiera
# Ejemplo:
# $(LIB_DIR_DST)/otra_libreria.o: $(LIB_DIR_SRC)/otra_libreria.c $(LIB_DIR_SRC)/otra_libreria.h
#     $(CC) -c -o $(LIB_DIR_DST)/otra_libreria.o $(LIB_DIR_SRC)/otra_libreria.c
#     cp $(LIB_DIR_SRC)/otra_libreria.h $(LIB_DIR_DST)/

# Compilar programas
registro_continuo: $(PROG_DIR)/registro_continuo*.c $(LIB_DIR_DST)/libdetector_eventos.so $(LIB_DIR_DST)/liblector_json.so
	$(CC) $(CFLAGS) -I$(LIB_DIR_DST) -o $(EXE_DIR)/registro_continuo $(PROG_DIR)/registro_continuo*.c -ldetector_eventos -llector_json -lbcm2835 -lwiringPi -lm

comprobar_registro: $(PROG_DIR)/comprobar_registro*.c $(LIB_DIR_DST)/liblector_json.so
	$(CC) $(CFLAGS) -I$(LIB_DIR_DST) -o $(EXE_DIR)/comprobar_registro $(PROG_DIR)/comprobar_registro*.c -llector_json

extraer_evento: $(PROG_DIR)/extraer_evento*.c
	$(CC) -o $(EXE_DIR)/extraer_evento $(PROG_DIR)/extraer_evento*.c

reset_master: $(PROG_DIR)/reset_master.c
	$(CC) -o $(EXE_DIR)/reset_master $(PROG_DIR)/reset_master.c -lbcm2835 -lwiringPi


clean:
	rm -f $(LIB_DIR_DST)/*.o $(LIB_DIR_DST)/*.so $(EXE_DIR)/*

import os
import time
import struct

PIPE_NAME = "/tmp/my_pipe"
BUFFER_SIZE = 2506

def main():
    if not os.path.exists(PIPE_NAME):
        os.mkfifo(PIPE_NAME)

    print("Esperando datos...")
    
    while True:
        try:
            with open(PIPE_NAME, "rb") as pipe:
                data = pipe.read(BUFFER_SIZE)
                if data:
                    print(f"Leídos {len(data)} bytes")
                    if len(data) >= 6:
                        # Extraer los últimos 6 bytes
                        timestamp = data[-6:]
                        # Convertir los bytes a valores numéricos
                        year, month, day, hour, minute, second = struct.unpack('6B', timestamp)
                        # Imprimir en el formato deseado
                        print(f"Fecha y hora leída del pipe: {year:02d}/{month:02d}/{day:02d} {hour:02d}:{minute:02d}:{second:02d}")
                else:
                    print("No hay datos disponibles. Esperando...")
                    time.sleep(1)
        except KeyboardInterrupt:
            print("Lectura interrumpida. Saliendo.")
            break
        except Exception as e:
            print(f"Error: {e}")
            time.sleep(1)

    print("Programa finalizado.")

if __name__ == "__main__":
    main()

import sys
import os
import struct
import time
import numpy as np
from datetime import datetime, timezone

# Añadir directorio base al path para importar
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_OPERATION_DIR = os.path.dirname(_SCRIPT_DIR)
if _OPERATION_DIR not in sys.path:
    sys.path.insert(0, _OPERATION_DIR)

from streaming.shared_memory_publisher import SharedMemoryReader, SHM_PATH

def main():
    print(f"=== Diagnóstico de Memoria Compartida ===")
    print(f"Ruta SHM: {SHM_PATH}")
    
    if not os.path.exists(SHM_PATH):
        print(f"ERROR: El archivo de memoria compartida {SHM_PATH} no existe.")
        sys.exit(1)
        
    try:
        reader = SharedMemoryReader(shm_path=SHM_PATH)
        print("Lector de memoria compartida inicializado correctamente.")
        
        # Leer 5 tramas consecutivas con 1 segundo de separación
        for i in range(5):
            seq, ts, samples, clock = reader.read()
            dt = datetime.fromtimestamp(ts, tz=timezone.utc)
            
            print(f"\n--- Lectura {i+1} ---")
            print(f"Secuencia: {seq}")
            print(f"Timestamp: {ts} ({dt.strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]} UTC)")
            print(f"Fuente de Reloj: {clock}")
            print(f"Forma de muestras: {samples.shape} (esperado: (250, 3))")
            
            # Calcular estadísticas
            min_val = np.min(samples, axis=0)
            max_val = np.max(samples, axis=0)
            mean_val = np.mean(samples, axis=0)
            std_val = np.std(samples, axis=0)
            
            print(f"Estadísticas por eje (X, Y, Z):")
            print(f"  Mínimos:  {min_val}")
            print(f"  Máximos:  {max_val}")
            print(f"  Medias:   {mean_val}")
            print(f"  Desv.Est: {std_val}")
            
            # Mostrar las primeras 5 muestras
            print(f"  Primeras 5 muestras:")
            for j in range(min(5, len(samples))):
                print(f"    Muestra {j}: {samples[j]}")
                
            time.sleep(1.0)
            
        reader.close()
        
    except Exception as e:
        print(f"ERROR durando el diagnóstico: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()

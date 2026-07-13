import sys
import os
import time
import numpy as np

# Añadir directorio base al path para importar
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_OPERATION_DIR = os.path.dirname(_SCRIPT_DIR)
if _OPERATION_DIR not in sys.path:
    sys.path.insert(0, _OPERATION_DIR)

from streaming.shared_memory_publisher import SharedMemoryReader, SHM_PATH
from core.signal_preprocessor import SignalPreprocessor
from scipy.signal import resample_poly

def print_stats(name, data):
    min_val = np.min(data, axis=0)
    max_val = np.max(data, axis=0)
    mean_val = np.mean(data, axis=0)
    std_val = np.std(data, axis=0)
    print(f"\n--- {name} (shape: {data.shape}, dtype: {data.dtype}) ---")
    print(f"  Mínimos:  {min_val}")
    print(f"  Máximos:  {max_val}")
    print(f"  Medias:   {mean_val}")
    print(f"  Desv.Est: {std_val}")

def main():
    print("=== Diagnóstico de Compatibilidad de Resampling ===")
    if not os.path.exists(SHM_PATH):
        print(f"ERROR: {SHM_PATH} no existe.")
        sys.exit(1)
        
    reader = SharedMemoryReader(shm_path=SHM_PATH)
    seq, ts, samples, clock = reader.read()
    reader.close()
    
    print_stats("Muestras Crudas (int32)", samples)
    
    # 1. Resampling con int32 (original)
    try:
        res_int32 = resample_poly(samples, 2, 5, axis=0)
        print_stats("Resampling usando int32", res_int32)
    except Exception as e:
        print(f"Error en resampling int32: {e}")
        
    # 2. Resampling con float64 (conversión explícita)
    try:
        samples_float64 = samples.astype(np.float64)
        res_float64 = resample_poly(samples_float64, 2, 5, axis=0)
        print_stats("Resampling usando float64", res_float64)
    except Exception as e:
        print(f"Error en resampling float64: {e}")
        
    # 3. Resampling con float32 (conversión explícita)
    try:
        samples_float32 = samples.astype(np.float32)
        res_float32 = resample_poly(samples_float32, 2, 5, axis=0)
        print_stats("Resampling usando float32", res_float32)
    except Exception as e:
        print(f"Error en resampling float32: {e}")

if __name__ == "__main__":
    main()

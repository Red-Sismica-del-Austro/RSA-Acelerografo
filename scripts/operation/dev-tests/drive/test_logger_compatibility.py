
import sys
import os

# Añadir el path para importar StructuredLogger
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from structured_logger import StructuredLogger

def test_logger_compatibility():
    log_directory = os.path.abspath(os.path.join(os.path.dirname(__file__), 'logs'))
    log_filename = "test_compatibility.log"
    id_estacion = "TEST_STATION"
    
    print(f"--- Iniciando prueba de compatibilidad de logger ---")
    print(f"Directorio de logs: {log_directory}")
    
    # Instanciar logger
    logger = StructuredLogger(
        id_estacion=id_estacion,
        log_directory=log_directory,
        log_filename=log_filename,
        verbosity="DEBUG"
    )
    
    # 1. Probar llamada con 2 argumentos (Estilo estructurado actual)
    print("\n1. Probando llamada con 2 argumentos (Estilo estructurado)...")
    try:
        logger.error("SYSTEM_CHECK", "Critical error detected")
        print("   OK: Llamada con 2 argumentos exitosa.")
    except TypeError as e:
        print(f"   FALLO: Error de tipo con 2 argumentos: {e}")
    except Exception as e:
        print(f"   FALLO: Error inesperado con 2 argumentos: {e}")

    # 2. Probar llamada con 1 argumento (Estilo logging estándar)
    print("\n2. Probando llamada con 1 argumento (Estilo logging estándar)...")
    try:
        logger.error("Error simple sin operacion especificada")
        print("   OK: Llamada con 1 argumento exitosa.")
    except TypeError as e:
        print(f"   FALLO: Error de tipo con 1 argumento (el error reportado en producción): {e}")
    except Exception as e:
        print(f"   FALLO: Error inesperado con 1 argumento: {e}")

    print("\n--- Fin de la prueba ---")
    print(f"Puedes revisar el contenido del log en: {os.path.join(log_directory, log_filename)}")

if __name__ == "__main__":
    test_logger_compatibility()

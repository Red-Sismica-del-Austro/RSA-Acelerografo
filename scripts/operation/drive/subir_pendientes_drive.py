import os
import subprocess
import shutil
import socket
import json

######################################### ~Funciones~ #################################################

# Lee un archivo de configuración en formato JSON y devuelve su contenido como un diccionario.
def read_fileJSON(nameFile):
    try:
        with open(nameFile, 'r') as f:
            data = json.load(f)
        return data
    except FileNotFoundError:
        print(f"Archivo {nameFile} no encontrado.")
        return None
    except json.JSONDecodeError:
        print(f"Error al decodificar el archivo {nameFile}.")
        return None

# Retorna el porcentaje de espacio libre en la partición donde se encuentra 'path'
def get_free_space_percentage(path):
    total, used, free = shutil.disk_usage(path)
    return (free / total) * 100

# Verifica la conexión a internet intentando conectar al servidor DNS de Google
def check_internet_connection(host="8.8.8.8", port=53, timeout=3):
    try:
        socket.setdefaulttimeout(timeout)
        socket.socket(socket.AF_INET, socket.SOCK_STREAM).connect((host, port))
        return True
    except Exception:
        return False

# Borra el archivo más antiguo con la extensión indicada en el directorio especificado
def delete_oldest_file(directory, extension):
    files = [os.path.join(directory, f) for f in os.listdir(directory) if f.endswith(extension)]
    if not files:
        print(f"No se encontraron archivos con extensión {extension} en {directory}.")
        return
    oldest_file = min(files, key=os.path.getmtime)
    try:
        os.remove(oldest_file)
        print(f"Se borró el archivo más antiguo: {oldest_file}")
    except Exception as e:
        print(f"Error al borrar el archivo {oldest_file}: {e}")


#######################################################################################################

def main():
    # Obtiene la variable de entorno para definir la ruta del archivo de configuracion:
    project_local_root = os.getenv("PROJECT_LOCAL_ROOT")
    if not project_local_root:
        print("La variable de entorno PROJECT_LOCAL_ROOT no está definida.")
        return
    
    # Definir rutas de archivos y directorios
    script_subir_archivo_drive = os.path.join(project_local_root, "scripts", "drive", "subir_archivo.py")
    mseed_directory = os.path.join(project_local_root, "resultados", "mseed")
    binary_directory = os.path.join(project_local_root, "resultados", "registro-continuo")
    config_dispositivo_path = os.path.join(project_local_root, "configuracion", "configuracion_dispositivo.json")

    
    # Lee el archivo de configuración del dispositivo
    config_dispositivo = read_fileJSON(config_dispositivo_path)
    if config_dispositivo is None:
        print("No se pudo leer el archivo de configuración del dispositivo. Terminando el programa.")
        return
    
    mode_acq = config_dispositivo.get("dispositivo", {}).get("modo_adquisicion", "Unknown")

    # Escanear el contenido de los directorios
    archivos_mseed = [f for f in os.listdir(mseed_directory) if f.endswith(".mseed")]
    archivos_binarios = [f for f in os.listdir(binary_directory) if f.endswith(".dat")]
    
    if mode_acq == "offline":
        print("Modo offline activado.")
        # Borrar todos los archivos binarios
        for archivo in archivos_binarios:
            path_archivo = os.path.join(binary_directory, archivo)
            try:
                os.remove(path_archivo)
                print(f"Archivo binario borrado: {path_archivo}")
            except Exception as e:
                print(f"Error al borrar {path_archivo}: {e}")

        # Verificar espacio disponible en la partición donde se encuentra el directorio mseed
        free_space = get_free_space_percentage(mseed_directory)
        print(f"Espacio libre: {free_space:.2f}%")
        if free_space < 10:
            print("El espacio disponible es menor al 10%. Se procederá a borrar el archivo mseed más antiguo.")
            delete_oldest_file(mseed_directory, ".mseed")
    
    elif mode_acq == "online":
        print("Modo online activado.")
        if check_internet_connection():
            print("Conexión a internet establecida. Se procederá a subir los archivos mseed a Google Drive.")
            if archivos_mseed:
                for archivo in archivos_mseed:
                    print(f"Subiendo el archivo: {archivo}")
                    subprocess.run(["python3", script_subir_archivo_drive, archivo, "3", "1"])
            else:
                print("No se encontraron archivos .mseed en el directorio especificado.")
        else:
            print("Sin conexión a internet.")
            # Verificar espacio disponible en el directorio de archivos binarios
            free_space = get_free_space_percentage(binary_directory)
            print(f"Espacio libre en el directorio de binarios: {free_space:.2f}%")
            if free_space < 10:
                print("El espacio disponible es menor al 10%. Se procederá a borrar el archivo binario más antiguo.")
                delete_oldest_file(binary_directory, ".dat")
            else:
                print("Espacio disponible suficiente en la partición.")
    else:
        print(f"Modo de adquisición desconocido: {mode_acq}")
 

if __name__ == "__main__":
    main()

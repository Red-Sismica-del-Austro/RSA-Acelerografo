import os
import subprocess

def main():
    # Obtiene la variable de entorno para definir la ruta del archivo de configuracion:
    project_local_root = os.getenv("PROJECT_LOCAL_ROOT")
    if project_local_root:
        # Concatenar PROJECT_LOCAL_ROOT con las diferentes rutas de los archivos y scripts:
        script_subir_archivo_drive = os.path.join(project_local_root, "scripts", "drive", "subir_archivo.py")
    else:
        print("La variable de entorno no está definida.")
        return

    # Definir el directorio de archivos .mseed a subir
    mseed_directory = "/home/rsa/projects/acelerografo/resultados/mseed"

    # Verificar si el directorio existe
    if not os.path.exists(mseed_directory):
        print(f"El directorio {mseed_directory} no existe.")
        return

    # Escanear el contenido del directorio
    archivos_mseed = [f for f in os.listdir(mseed_directory) if f.endswith(".mseed")]

    # Subir cada archivo a Google Drive
    if archivos_mseed:
        for nombre_archivo_mseed in archivos_mseed:
            #ruta_archivo_mseed = os.path.join(mseed_directory, nombre_archivo_mseed)
            print(f"Subiendo el archivo: {nombre_archivo_mseed}")
            subprocess.run(["python3", script_subir_archivo_drive, nombre_archivo_mseed, "3", "1"])
    else:
        print("No se encontraron archivos .mseed en el directorio especificado.")

if __name__ == "__main__":
    main()

import os

def main():
    # Acceder a las variables de entorno
    project_git_root = os.getenv("PROJECT_GIT_ROOT")
    project_local_root = os.getenv("PROJECT_LOCAL_ROOT")

    if project_git_root and project_local_root:
        print(f"PROJECT_GIT_ROOT: {project_git_root}")
        print(f"PROJECT_LOCAL_ROOT: {project_local_root}")

        # Concatenar PROJECT_LOCAL_CONFIG con "/configuracion_dispositivo.json"
        configuracion_dispositivo_file = os.path.join(project_local_root, "configuracion", "configuracion_dispositivo.json")

        # Imprimir el resultado
        print(f"configuracion_dispositivo_file: {configuracion_dispositivo_file}")
    else:
        print("Una o más variables de entorno no están definidas.")

if __name__ == "__main__":
    main()

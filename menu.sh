#!/bin/bash

# Función para mostrar el menú y leer la opción seleccionada
show_menu() {
  echo " "
  echo "*****************************************************************"
  echo "Bienvenido al menú de configuración"
  echo "*****************************************************************"
  echo "0. Establecer variables de entorno"
  echo "1. Instalar librerías"
  echo "2. Desplegar el proyecto"
  echo "3. Actualizar el proyecto"
  echo "4. Salir"
  read -p "Ingrese el número de opción que desea ejecutar: " option
}

# Ciclo principal del programa
while true; do
  # Mostrar el menú y leer la opción seleccionada
  show_menu

  # Ejecutar el script correspondiente según la opción seleccionada
  case $option in
    0)
      echo "Preparando las variables de entorno..."
      sudo cp scripts/env/project_paths.sh /etc/profile.d/project_paths.sh
      sudo cp scripts/env/project_paths.sh /usr/local/bin/project_paths
      sudo chmod +x /etc/profile.d/project_paths.sh
      sudo chmod +x /usr/local/bin/project_paths
      source /etc/profile.d/project_paths.sh
      echo "Raiz del repositorio Git: $PROJECT_GIT_ROOT"
      echo "Raiz del proyecto local: $PROJECT_LOCAL_ROOT"
      ;;
    1)
      echo "Instalado librerias necesarias..."
      bash scripts/setup/instalar-librerias.sh
      ;;
    2)
      echo "Advertencia: Esta opción debe ejecutarse únicamente durante la configuración inicial de una nueva estación."
      echo "Si se ejecuta más de una vez puede borrar los archivos de configuracion."
      read -p "Desea continuar? (s/n) " response
      case "$response" in
        s|S)
            echo "Desplegando un proyecto nuevo..."
            bash scripts/setup/deploy.sh
            break
            ;;
        n|N)
            ;;
        *)
            echo "Opción no válida, por favor ingrese s para sí o n para no."
            ;;
      esac
      ;;
    3)
      echo "Actualizando el proyecto.."
      bash scripts/setup/update.sh
      ;;
    4)
      echo "Saliendo del programa..."
      echo "*****************************************************************"
      echo " "
      exit 0
      ;;
    *)
      echo "Opción no válida, por favor ingrese un número del 0 al 4."
      ;;
  esac
  echo "*****************************************************************"
done

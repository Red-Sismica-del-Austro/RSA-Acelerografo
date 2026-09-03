---
id: ADR-002
titulo: panel_web_configuracion_flask
estado: Aceptado
fecha: 2026-06-04
temas: [web, configuracion, seguridad]
entorno: [acelerografo]
---

# ADR-002: Panel Web de Configuración usando Flask

## Estado

**Aceptado** | Fecha: 2026-06-04

## Contexto

Para la Fase 4 de la unificación de configuraciones del acelerógrafo, se requiere una interfaz web interactiva que permita al personal en campo realizar cambios de configuración en caliente (lo que a su vez regenera los parámetros del runtime del acelerógrafo e inicia/reinicia los daemons). 

El hardware objetivo es una Raspberry Pi 3B+ que opera en estaciones remotas bajo recursos de memoria RAM y CPU sumamente limitados. Los scripts de adquisición y procesamiento de datos ya consumen una porción de recursos, por lo que la pila del servidor web de administración debe ser lo más liviana posible, requiriendo una huella mínima de memoria en modo pasivo y limitando el número de dependencias de terceros para facilitar el despliegue.

## Opciones Evaluadas

### Opción A: FastAPI con Uvicorn
FastAPI es una pila asíncrona moderna construida sobre ASGI y Pydantic para la validación automática de datos.
- **Ventajas:**
  - Validación de esquemas y sanitización de datos automática mediante modelos Pydantic.
  - Generación de documentación de endpoints interactiva de forma nativa.
  - Excelente rendimiento y soporte asíncrono para concurrencia.
- **Desventajas:**
  - Huella de memoria RAM inactiva más alta (~45MB - 50MB en la Raspberry Pi 3B+).
  - Instalación de múltiples paquetes y librerías externas dependientes de compilaciones específicas de Python.

### Opción B: Flask
Flask es una micro-biblioteca clásica de Python de carácter síncrono (WSGI).
- **Ventajas:**
  - Extremadamente liviana, requiriendo una huella de memoria RAM mínima (~15MB activos).
  - Mínimas dependencias externas, simplificando la instalación mediante el entorno virtual `.venv`.
  - Excelente soporte nativo para servir HTML, archivos estáticos y APIs sencillas de manera estructurada.
  - Patrón maduro y ampliamente comprendido por el equipo técnico.
- **Desventajas:**
  - No cuenta con validación automática de tipos y datos nativa, requiriendo lógica de validación manual.
  - Carece de soporte asíncrono de alto rendimiento (no requerido para este caso de uso transaccional de un solo usuario a la vez).

## Decisión

Se eligió la **Opción B (Flask)**. 

La restricción más crítica para la Raspberry Pi 3B+ es la economía de memoria RAM. Dado que el panel de administración web se utiliza de manera esporádica (únicamente en tareas de instalación y mantenimiento de campo) y solo atiende a un cliente concurrente (el móvil del operador), la sobrecarga de memoria de FastAPI no se justifica frente a los ~15MB de Flask. 

Las debilidades de validación de Flask se solventan programando una función de validación estructurada y estricta en `config_server.py` que comprueba cada campo del JSON contra un *allow-list* de tipos y valores permitidos usando expresiones regulares.

## Consecuencias

- **Huella del Servicio:** Consumo pasivo de RAM en el daemon `config_server` minimizado a ~15MB.
- **Simplicidad de Despliegue:** Integración fluida en el script `deploy.sh` y `update.sh` agregando la dependencia única `flask` al entorno virtual.
- **Esfuerzo de Desarrollo:** Es necesario codificar manualmente funciones de validación estrictas para todos los endpoints POST para mitigar riesgos de seguridad de inyección y escalada de privilegios.

## Referencias

- Sesión de origen: [2026-06-04_panel_web_config_fase4.md](file:///home/rsa/git/institucional/RSA-Bitacora-LLM-Milton/sesiones/2026/06/2026-06-04_panel_web_config_fase4.md)
- Contexto técnico relacionado: [config_server.py](file:///home/rsa/git/montajes/acelerografo-DEV00/scripts/operation/web/config_server.py)

---
id: ADR-001
titulo: Unificación de la Configuración del Acelerógrafo
estado: Aceptado
fecha: 2026-06-03
temas: [configuracion, unificacion, plantillas, automatizacion]
entorno: [acelerografo]
---

# ADR-001: Unificación de la Configuración del Acelerógrafo

## Estado

**Aceptado** | Fecha: 2026-06-03

## Contexto

Actualmente, el sistema acelerográfico almacena configuraciones redundantes en tres archivos JSON diferentes (`configuracion_dispositivo.json`, `configuracion_mqtt.json` y `configuracion_mseed.json`). El identificador de la estación (ej. `NOM00`) está duplicado en los tres archivos, y las coordenadas geográficas de la estación también se duplican. 

Esto genera dos problemas principales:
1. **Dificultad de Despliegue**: Para configurar una estación nueva, el administrador debe modificar manualmente el código de estación en múltiples archivos de configuración de forma redundante, un proceso propenso a errores humanos.
2. **Preparación para Interfaz Web**: A futuro se busca implementar un panel de control web local en la estación que edite la configuración. Tener múltiples archivos desestructurados y con redundancia dificulta el diseño de una interfaz limpia y robusta que actúe sobre una única fuente de verdad (SSOT).

Además, existe la restricción de que los cambios de configuración específicos de cada estación en producción no deben contaminar o modificar el directorio del repositorio Git original (`project_git_root`) para evitar conflictos operacionales al realizar actualizaciones con `git pull`.

## Opciones Evaluadas

### Opción A: Archivo de Configuración Único Integrado (`configuracion_estacion.json`)
Consiste en fusionar todos los JSONs en uno solo, unificando todos los parámetros de la estación en una sola estructura lógica JSON.
- **Ventajas:**
  - Estructura limpia y elegante sin duplicados en tiempo de ejecución.
  - Una sola ruta de lectura para todos los scripts y binarios.
- **Desventajas:**
  - Requiere reescribir y adaptar el cargador JSON en C (`lector_json.c`) y en los múltiples scripts en Python (`binary_to_mseed.py`, `gestor_archivos_acq.py`, `mqtt_coordinator.py`).
  - Alto riesgo operativo al requerir recompilar y reinstalar binarios críticos en producción que interactúan con el hardware (`registro_continuo`).

### Opción B: Generador Dinámico de Configuración basado en Plantillas (Maestro + Hidratación)
Mantener los tres archivos JSON tradicionales que el sistema lee en tiempo de ejecución, pero introduciendo un archivo maestro `configuracion_maestra.json` que actúa como única fuente de verdad y plantillas `.template` con marcadores. Un script auxiliar de hidratación genera los JSONs de runtime.
- **Ventajas:**
  - Cero modificaciones a los binarios compilados de adquisición en C y al código de producción existente.
  - El archivo maestro local de la estación reside fuera del repositorio de control de versiones Git, permitiendo cambios de configuración locales en producción sin generar conflictos al realizar actualizaciones con `git pull`.
  - Preparado para el panel web, el cual solo deberá editar `configuracion_maestra.json` y relanzar el hidratador.
- **Desventajas:**
  - Se añade un paso intermedio de generación (hidratación) durante el despliegue o la actualización del sistema.

## Decisión

Se eligió la **Opción B (Generación por Plantillas / Maestro + Hidratación)** porque minimiza drásticamente el riesgo operativo en el hardware de producción al no requerir la recompilación del software de adquisición en C (`registro_continuo`), al mismo tiempo que logra desacoplar de forma limpia la configuración de la estación del repositorio Git y provee una fuente única de verdad para el futuro panel web.

## Consecuencias

- **Aislamiento de Entorno**: El repositorio Git montado (`project_git_root`) permanece limpio y no contiene modificaciones operacionales locales, facilitando actualizaciones con `git pull`.
- **Automatización**: Se integró el hidratador en `deploy.sh` y `update.sh` para que se ejecute transparentemente al instalar o actualizar el sistema acelerográfico.
- **Robustez**: Si la hidratación fallase al guardar cambios locales, los últimos JSON de runtime válidos persisten en el sistema local, asegurando la continuidad del servicio.

## Referencias

- Sesión de origen: [2026-06-03_unificacion_configuracion.md](file:///home/rsa/git/institucional/RSA-Bitacora-LLM-Milton/sesiones/2026/06/2026-06-03_unificacion_configuracion.md)
- Contexto técnico relacionado: [registro_continuo_context.md](file:///home/rsa/git/montajes/acelerografo-DEV00/docs/context/registro_continuo_context.md), [binary_to_mseed_context.md](file:///home/rsa/git/montajes/acelerografo-DEV00/docs/context/binary_to_mseed_context.md), [mqtt_coordinator_context.md](file:///home/rsa/git/montajes/acelerografo-DEV00/docs/context/mqtt_coordinator_context.md)

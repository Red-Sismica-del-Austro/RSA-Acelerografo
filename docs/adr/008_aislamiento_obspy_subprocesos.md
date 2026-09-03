---
id: ADR-008
titulo: Aislamiento de Dependencias de ObsPy mediante Ejecución por Subprocesos
estado: Aceptado
fecha: 2026-06-24
temas: [acelerografo, event-extractor, obspy, venv, subprocesos]
entorno: [acelerografo]
---

# ADR-008: Aislamiento de Dependencias de ObsPy mediante Ejecución por Subprocesos

## Estado

**Aceptado** | Fecha: 2026-06-24

## Contexto

El daemon coordinador de telemetría MQTT (`mqtt_coordinator.py`) corre en la Raspberry Pi como un servicio en segundo plano gestionado por Supervisor. Este daemon interactúa con la infraestructura de red del sistema y despacha comandos remotos, por lo que a menudo se ejecuta bajo el entorno de Python del sistema o requiere de un entorno liviano con pocas dependencias de terceros.

Por otro lado, el módulo de extracción y empaquetamiento de eventos (`event_extractor.py`) requiere procesar datos sísmicos en formato MiniSEED, lo cual depende de la biblioteca científica `ObsPy` (y a su vez de `NumPy` y `SciPy`). `ObsPy` es una dependencia sumamente pesada, compleja de compilar en arquitecturas ARM y con dependencias binarias estrictas. 

De acuerdo con los estándares de codificación del proyecto, las librerías de Python complejas deben estar completamente aisladas dentro del entorno virtual del proyecto (`.venv`) y nunca ser instaladas de forma global con `sudo pip3`. Si `event_extractor.py` importase directamente a `ObsPy` dentro del mismo proceso del coordinador MQTT:
1.  Obligaría a que el servicio principal MQTT corra dentro del entorno virtual `.venv`, complicando el acceso a módulos globales y el script de arranque.
2.  Incrementaría la huella de memoria RAM pasiva de todo el daemon MQTT de forma innecesaria.
3.  Vulneraría el aislamiento de dependencias entre la lógica de comunicación y la lógica de análisis científico.

## Opciones Evaluadas

### Opción A: Ejecutar todo el Coordinador MQTT dentro del Entorno Virtual (.venv)
Migrar el inicio del servicio coordinador MQTT a través de Supervisor para que use el intérprete `$PROJECT_LOCAL_ROOT/.venv/bin/python3`, permitiendo que `event_extractor.py` importe directamente `obspy` e invoque sus funciones en el mismo proceso.
*   **Ventajas:** Permite llamadas directas en Python, manejo de excepciones en memoria y evita el overhead de crear subprocesos del sistema operativo.
*   **Desventajas:**
    *   Aumenta significativamente el consumo pasivo de memoria RAM del servicio de telemetría (el cual debe ser sumamente liviano).
    *   Acopla fuertemente el daemon de red a las versiones específicas de las librerías del `.venv`.
    *   Dificulta la depuración de caídas en el procesador de señales, ya que un fallo en la manipulación del miniSEED puede tumbar todo el daemon de comunicación MQTT.

### Opción B: Desacoplamiento por Subprocesos (`subprocess`)
Mantener el coordinador MQTT y `event_extractor.py` ejecutándose en el intérprete del host (del sistema), pero delegar las tareas pesadas de manipulación de archivos y formatos invocando a los scripts especializados (`binary_to_mseed.py` o `extract_segment.py`) mediante subprocesos usando la orden `subprocess.run()`. El subproceso apunta explícitamente al ejecutable del entorno virtual: `$PROJECT_LOCAL_ROOT/.venv/bin/python3`.
*   **Ventajas:**
    *   **Aislamiento Total:** El daemon principal de red MQTT no requiere importar ni saber nada de `ObsPy`.
    *   **Seguridad:** Si un archivo miniSEED corrupto produce un fallo catastrófico (ej. segmentation fault de ObsPy por librerías C subyacentes), solo se cae el subproceso transitorio de extracción, pero el daemon MQTT permanece en línea y reportando telemetría.
    *   **Preservación de RAM:** La huella de memoria en reposo se mantiene al mínimo, instanciando ObsPy únicamente durante los segundos que dure la extracción.
*   **Desventajas:** Añade un leve overhead de tiempo de CPU y memoria en el kernel de Linux para crear el proceso y parsear su salida estándar.

## Decisión

Se seleccionó la **Opción B: Desacoplamiento por Subprocesos (`subprocess`)**.

El aislamiento de dependencias y la tolerancia a fallos en el sistema embebido son prioritarios frente a la mínima latencia que evitaría crear un subproceso. La Raspberry Pi 3B+ maneja de forma eficiente el ciclo de vida de los subprocesos de corta duración, y la robustez resultante en el servicio MQTT de producción compensa el overhead de la llamada a sistema.

## Consecuencias

*   **Lógica de Invocación:** El orquestador `event_extractor.py` expone `_resolver_rutas()` y utiliza `subprocess.run` para ejecutar los scripts auxiliares dentro de la ruta del `.venv`.
*   **Comunicación Inter-Procesos:** Para capturar el nombre del archivo miniSEED auto-generado por los subprocesos, `event_extractor.py` implementa `_parsear_archivo_generado()` que lee la salida estándar (`stdout`) mediante expresiones regulares.
*   **Estabilidad:** Se garantiza que el entorno global de Python de la estación acelerográfica no contiene residuos ni dependencias del framework científico ObsPy.

## Referencias

*   Contexto técnico relacionado: [event_extractor_context.md](file:///c:/Users/miltonrsa/Documents/git/rsa/RSA-Acelerografo/docs/context/event_extractor_context.md)

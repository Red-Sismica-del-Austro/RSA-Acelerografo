---
id: ADR-005
titulo: Eliminación de la Detección Automática de Eventos STA/LTA Local
estado: Aceptado
fecha: 2026-06-24
temas: [acelerografo, adquisicion, sta-lta, optimizacion]
entorno: [acelerografo]
---

# ADR-005: Eliminación de la Detección Automática de Eventos STA/LTA Local

## Estado

**Aceptado** | Fecha: 2026-06-24

## Contexto

En las versiones iniciales del software de adquisición sísmica continua que se ejecuta en la Raspberry Pi (`registro_continuo`), se incluía un módulo embebido en C para la detección en tiempo real de eventos sísmicos mediante el algoritmo STA/LTA (Short-Term Average / Long-Term Average), un filtro de paso alto digital FIR y la publicación automática de eventos por MQTT local.

Sin embargo, correr este procesamiento pesado en caliente dentro del mismo daemon responsable de interaccionar con el microcontrolador dsPIC33EP a través de SPI a 250 Hz generaba los siguientes problemas:
1.  **Riesgo Operativo:** El daemon C debe ser de tiempo real blando y no perder ninguna trama SPI de 1 segundo (250 muestras). El overhead de CPU introducido por el filtro digital FIR y el cómputo continuo del STA/LTA aumentaba la probabilidad de retrasos en las lecturas de SPI y pérdida de consistencia.
2.  **Complejidad del Código:** El código en C acumulaba más de 1500 líneas (LOC), dificultando su mantenimiento y depuración en sistemas embebidos de producción.
3.  **Redundancia de Procesamiento:** Los análisis e identificaciones de eventos complejos se realizan con mayor precisión de forma centralizada en los servidores institucionales (usando ObsPy, SeisComP u otros motores de inferencia offline).

## Opciones Evaluadas

### Opción A: Mantener y Optimizar el STA/LTA en C
Continuar con el cálculo en caliente dentro del daemon de adquisición, optimizando el filtro FIR (ej. usando operaciones SIMD o enteros de punto fijo) para reducir la carga de CPU.
*   **Ventajas:** Detección y triggers instantáneos a nivel físico de la estación sin dependencias secundarias.
*   **Desventajas:** El código en C se vuelve aún más complejo y difícil de mantener. Persiste el riesgo operacional de caídas o desfases en la adquisición.

### Opción B: Eliminar el Módulo en C y Delegar el STA/LTA
Remover por completo la detección automática de eventos STA/LTA, el filtro FIR y los drivers asociados (`detector_eventos.c`, `detector_eventos.h`) del binario principal de adquisición, delegando la extracción de eventos a peticiones bajo demanda (mediante MQTT) o procesos de análisis históricos offline en el servidor central.
*   **Ventajas:**
    *   Simplifica drásticamente el daemon en C (`registro_continuo_4.5.0.c`), reduciendo su tamaño de ~1518 a ~758 LOC.
    *   Optimiza la estabilidad de la adquisición continua, logrando que el hilo principal tenga un consumo de CPU mínimo (~8-12% en una Raspberry Pi 3B+) y eliminando cuellos de botella críticos.
    *   Facilita la evolución y actualización de algoritmos de detección al desacoplarlos del binario embebido en C.
*   **Desventajas:** La estación deja de generar de forma autónoma triggers de eventos a nivel de adquisición local.

## Decisión

Se eligió la **Opción B (Eliminar el Módulo en C y Delegar)**.

La prioridad número uno del sistema acelerográfico en producción es la fiabilidad de la adquisición continua y que no se pierdan datos. La eliminación del STA/LTA del daemon en C remueve un overhead innecesario y estabiliza la tasa de muestreo de 250 Hz. Los triggers de eventos y la extracción de ventanas sísmicas ahora se realizan mediante el orquestador Python (`event_extractor.py`) bajo demanda, o de forma centralizada en los sistemas de procesamiento offline.

## Consecuencias

*   **Simplificación Estructural:** Se eliminaron del repositorio los archivos `detector_eventos.c` y `detector_eventos.h`.
*   **Estabilidad de Adquisición:** El daemon `registro_continuo` corre con un margen de inactividad por ciclo del ~96.9%, lo que reduce drásticamente el riesgo de retrasos de I/O en el bus SPI.
*   **Acoplamiento Débil:** El pipeline de eventos se independiza del binario en C, permitiendo modificar políticas de extracción y análisis sin alterar el ciclo de adquisición continuo en caliente.

## Referencias

*   Contexto técnico relacionado: [registro_continuo_context.md](file:///c:/Users/miltonrsa/Documents/git/rsa/RSA-Acelerografo/docs/context/registro_continuo_context.md)

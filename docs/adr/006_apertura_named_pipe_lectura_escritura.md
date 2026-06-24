---
id: ADR-006
titulo: Apertura del Named Pipe en Modo Lectura-Escritura (O_RDWR) para Evitar EOF
estado: Aceptado
fecha: 2026-06-24
temas: [acelerografo, streaming, pipe, named-pipe, optimizacion]
entorno: [acelerografo]
---

# ADR-006: Apertura del Named Pipe en Modo Lectura-Escritura (O_RDWR) para Evitar EOF

## Estado

**Aceptado** | Fecha: 2026-06-24

## Contexto

El daemon de adquisición en C (`registro_continuo`) escribe tramas binarias de 2506 bytes de manera continua cada 1 segundo en el named pipe `/tmp/my_pipe`. Para evitar bloqueos operacionales en caso de que no haya un lector activo, el programa C abre el named pipe utilizando los flags `O_WRONLY | O_NONBLOCK` (solo escritura, no bloqueante) y cierra el descriptor de archivo (`fd`) inmediatamente después de escribir cada trama.

En la capa lectora en Python (`stream_processor.py`), si se abre el pipe en modo de solo lectura tradicional (como `r` o `os.O_RDONLY`):
1.  Cada vez que el proceso en C cierra el descriptor del pipe, el sistema operativo le reporta un EOF (End of File) al lector Python.
2.  Para seguir escuchando, el daemon de Python se ve obligado a cerrar y reabrir el descriptor del pipe en un bucle continuo.
3.  Este ciclo constante de apertura/cierre de descriptores introduce latencia, aumenta el uso de CPU y puede provocar race conditions, además de generar excepciones de `SIGPIPE` en el escritor C si intenta escribir antes de que el lector vuelva a abrir el descriptor.

## Opciones Evaluadas

### Opción A: Bucle de Apertura y Cierre con Reintentos en Python
Mantener la apertura en solo lectura (`os.O_RDONLY`), capturando el EOF en cada segundo y volviendo a instanciar/abrir el archivo de forma reactiva.
*   **Ventajas:** Conceptualmente simple y no altera el flujo unidireccional de datos del pipe.
*   **Desventajas:** Alto costo computacional de I/O en la Raspberry Pi por abrir/cerrar descriptores de archivos 86,400 veces al día. Riesgo elevado de pérdida de tramas debido a race conditions en el cruce de aperturas.

### Opción B: Abrir el Named Pipe en Modo Lectura-Escritura (`os.O_RDWR`)
Abrir el descriptor del named pipe desde Python con el flag `os.O_RDWR`. Dado que el proceso lector mantiene un descriptor de escritura abierto sobre el mismo pipe en su propia tabla de archivos, el kernel de Linux nunca ve un estado de "cero escritores" y, por lo tanto, jamás envía un EOF al lector.
*   **Ventajas:**
    *   El pipe permanece abierto indefinidamente en el lector Python.
    *   Se elimina por completo el overhead de abrir y cerrar descriptores de archivos cada segundo.
    *   Flujo de datos continuo y robusto, libre de excepciones `SIGPIPE` para el proceso productor C.
*   **Desventajas:** El lector tiene permisos de escritura sobre el pipe (aunque no escribe en él, solo lo hace para mantener vivo el descriptor).

## Decisión

Se seleccionó la **Opción B (Abrir en modo `os.O_RDWR`)**.

Esta técnica, ampliamente utilizada en sistemas Unix para daemons de logging y streaming por named pipes, elimina la sobrecarga de I/O en el procesador y las race conditions de la capa física de transporte. La Raspberry Pi 3B+ conserva ciclos de reloj valiosos y el acoplamiento entre `registro_continuo` (C) y `stream_processor` (Python) se vuelve robusto y tolerante a fallas.

## Consecuencias

*   **Persistencia del Descriptor:** `StreamProcessor` abre el pipe una sola vez al iniciar su ciclo de ejecución (`run()`) y lo mantiene abierto hasta su detención.
*   **Gestión de Datos:** Se implementó un acumulador de bytes interno (`bytearray`) en el procesador para manejar lecturas parciales en el pipe de forma segura cuando el buffer no tiene tramas completas de 2506 bytes.
*   **Robustez de Escritor:** El programa en C puede cerrarse o reiniciarse sin afectar al daemon Python receptor, el cual simplemente queda en espera pasiva (bloqueante) de nuevos bytes en `os.read()`.

## Referencias

*   Contexto técnico relacionado: [stream_processor_context.md](file:///c:/Users/miltonrsa/Documents/git/rsa/RSA-Acelerografo/docs/context/stream_processor_context.md)

---
id: ADR-009
titulo: Memoria Compartida con Seqlock para IPC de Adquisición en Tiempo Real
estado: Aceptado
fecha: 2026-06-30
temas: [streaming, memoria-compartida, ipc, telemetria]
entorno: [acelerografo]
---

# ADR-009: Memoria Compartida con Seqlock para IPC de Adquisición en Tiempo Real

## Estado

**Aceptado** | Fecha: 2026-06-30

## Contexto

El daemon de adquisición del acelerógrafo (`stream_processor.py`) lee de forma continua tramas binarias de 2506 bytes desde un named pipe y las escribe en el disco a través de `RingBufferStore`. Para habilitar análisis secundarios en tiempo real sobre estas señales (como la inferencia sismológica mediante Machine Learning con GPD o el posterior envío de flujos vía SeedLink), se requiere comunicar la última trama decodificada a múltiples procesos consumidores locales en la Raspberry Pi 3B+.

Esta comunicación inter-procesos (IPC) debe cumplir con restricciones críticas del entorno embebido:
1.  **Ultra-baja latencia**: El intervalo de llegada de tramas es de 1 segundo (250 Hz × 3 componentes), por lo que el retraso en la transmisión debe ser despreciable (< 1 ms).
2.  **No bloqueo de la adquisición**: El proceso escritor (`stream_processor.py`) jamás debe bloquearse o retrasarse debido a que un lector esté lento, caído o procesando.
3.  **Cero desgaste de disco**: Evitar ciclos continuos de escritura física en la tarjeta SD de la Raspberry Pi.
4.  **Acceso Multi-lector**: Permitir que múltiples daemons locales lean la misma trama simultáneamente sin interferir entre sí.

## Opciones Evaluadas

### Opción A: Sockets de Dominio UNIX (UDS)
Establecer un servidor de streaming local en `stream_processor.py` que acepte conexiones de clientes locales vía sockets UNIX.
- **Ventajas**: Comunicación nativa de Linux, acoplamiento estándar y posibilidad de flujo bidireccional si se requiere.
- **Desventajas**: 
  - Introduce un overhead notable del kernel en la copia de buffers.
  - Obliga al escritor a mantener una lista de descriptores de archivos de clientes, manejar excepciones si un socket se rompe abruptamente y gestionar hilos o bucles de eventos asíncronos en el proceso de adquisición, incrementando la complejidad y riesgo de bloqueos.

### Opción B: Base de datos en memoria (Redis o SQLite en RAM)
Insertar las tramas en una instancia de Redis local o en una tabla de SQLite montada sobre `/dev/shm`.
- **Ventajas**: Acceso multi-cliente inmediato, consultas simples y estructuradas.
- **Desventajas**:
  - Consumo prohibitivo de memoria RAM y CPU en la Raspberry Pi 3B+ para levantar el motor de base de datos/servidor de Redis, restando ciclos de reloj vitales para los algoritmos de inferencia y adquisición.

### Opción C: Memoria Compartida (`/dev/shm`) con Sincronización Seqlock
Escribir las muestras en un archivo mapeado a memoria (`mmap`) ubicado en la ruta virtual en RAM `/dev/shm/rsa_current_frame`. Para la sincronización libre de locks, se implementa una variante del algoritmo **Seqlock** (Sequence Lock) en software.
- **Ventajas**:
  - Acceso directo a memoria RAM (latencia < 1 µs).
  - El escritor es completamente independiente (Single-Writer): incrementa la secuencia a impar al iniciar la escritura y a par al finalizar, escribiendo de forma secuencial sin bloquearse por semáforos ni Mutexes.
  - Los lectores (Multi-Reader) acceden de forma concurrente de solo lectura sin bloquear al escritor, garantizando consistencia mediante doble lectura de la secuencia (Seqlock Double-Read).
  - Aislamiento total: si un lector cae, el escritor sigue publicando con éxito y sin sobrecargas.
- **Desventajas**:
  - Los lectores deben implementar la lógica de reintentos (Double-Read) en caso de colisión con la escritura.
  - Requiere un tamaño de segmento estático (3024 bytes) y un layout de bytes rígido acordado de antemano.

## Decisión

Se seleccionó la **Opción C: Memoria Compartida (`/dev/shm`) con Sincronización Seqlock**, debido a su latencia insignificante, consumo nulo de CPU/RAM del sistema, eliminación total del desgaste de la SD y el aislamiento completo que protege al daemon de adquisición continua de cualquier fallo en la capa de procesamiento de señal o inferencia.

## Consecuencias

- **Positivas**:
  - Comunicación IPC ultra-veloz y libre de locks.
  - Despliegue transparente en Linux gracias al soporte nativo de `/dev/shm` (tmpfs).
  - Robustez del escritor ante fallos en los lectores.
  - El lector (`SharedMemoryReader`) auto-detecta si el archivo en `/dev/shm` fue eliminado y recreado (comparando el número de *inode*), permitiendo reconexión transparente tras reinicios del publicador.
- **Negativas / Deuda técnica**:
  - El segmento tiene un formato físico rígido (3024 bytes). Si el dsPIC cambia de frecuencia de muestreo (250 Hz) o de número de ejes (3), se requerirá actualizar el compilador, las plantillas y rediseñar el layout del bloque binario.
  - La sincronización depende de que la escritura de la secuencia de 8 bytes sea atómica (garantizado en procesadores ARM de 64 bits y controlado mediante la lógica del lector en 32 bits).

## Referencias

- Sesión de origen: [2026-06-30_shm_preprocesador_gpd.md](file:///home/rsa/git/institucional/RSA-Bitacora-LLM-Milton/sesiones/2026/06/2026-06-30_shm_preprocesador_gpd.md)
- Contexto técnico relacionado: [shared_memory_publisher_context.md](file:///home/rsa/git/montajes/acelerografo-DEV00/docs/context/shared_memory_publisher_context.md)

---
id: ADR-004
titulo: Implementación del Ring Buffer del Acelerógrafo
estado: Aceptado
fecha: 2026-06-18
temas: [acelerografo, streaming, ring-buffer, telemetria]
entorno: [acelerografo]
---

# ADR-004: Implementación del Ring Buffer del Acelerógrafo

## Estado

**Aceptado** | Fecha: 2026-06-18

## Contexto

El acelerógrafo registra un flujo continuo de datos sísmicos (tramas binarias de 2506 bytes) enviados por el hardware dsPIC. El sistema requiere poder atender solicitudes de telemetría bajo demanda vía MQTT para extraer segmentos de datos recientes (por ejemplo, los últimos 10 minutos para la detección y reporte inmediato de sismos) de forma rápida y sin interferir con la adquisición continua.

Anteriormente, el sistema persistía directamente los datos en archivos horarios miniSEED o históricos locales. Acceder a estos archivos horarios para consultar solo unos minutos de datos recientes presentaba un alto overhead en I/O. Adicionalmente, el reloj del dsPIC presenta desvíos y un bug documentado en el cambio de día (cruce de medianoche), donde el reloj reporta la hora `00:00:xx` pero la fecha lógica del sistema no avanza inmediatamente, provocando saltos temporales negativos que rompen el cálculo de la rotación basada puramente en diferencias de tiempo de las tramas.

Se necesitaba una solución que proporcionara persistencia temporal eficiente, con límites estrictos de consumo de espacio en la tarjeta SD de la Raspberry Pi y protección contra desvíos y saltos de reloj en los datos recibidos.

## Opciones Evaluadas

### Opción A: Base de datos local (SQLite o InfluxDB)
Consiste en insertar secuencialmente las tramas decodificadas o muestras directas en una base de datos relacional o de series temporales en la Raspberry Pi.
- **Ventajas**: Consultas y filtros nativos por rangos de tiempo altamente indexados y estandarizados.
- **Desventajas**: 
  - Alto overhead de CPU y consumo de memoria RAM.
  - Desgaste excesivo de la memoria Flash/tarjeta SD de la Raspberry Pi debido al tráfico continuo de escrituras transaccionales y diarios de escritura (WAL).
  - Requiere un mapeo de datos que añade latencia al flujo continuo.

### Opción B: Búfer circular exclusivo en memoria (RAM)
Mantener las tramas de los últimos minutos en una estructura de cola FIFO en la memoria RAM del proceso.
- **Ventajas**: Acceso ultra rápido a los datos, sin latencia de I/O y cero desgaste de disco.
- **Desventajas**:
  - Pérdida total de datos en caso de reinicio de la Raspberry Pi, fallo de energía o detención del servicio.
  - Capacidad limitada por los recursos del sistema embebido.

### Opción C: Almacén rotativo en archivos binarios planos con índice en memoria (RingBufferStore)
Concatenar las tramas directamente en archivos `.bin` planos de duración fija (ej. 5 minutos), indexando los archivos en memoria para búsquedas eficientes y aplicando una eliminación física de archivos antiguos basada en un límite de tamaño total del directorio (FIFO).
- **Ventajas**:
  - Escritura directa de bytes de muy bajo costo en disco (secuencial plano, ideal para SD).
  - Conservación de datos ante apagones.
  - Control de capacidad exacto a nivel del sistema de archivos.
  - Conversión directa a miniSEED sin sobrecargas de consulta intermedia.
- **Desventajas**:
  - La consulta requiere buscar en el índice en memoria y realizar lecturas secuenciales dentro de los archivos `.bin` relevantes.
  - Requiere desarrollar lógica específica para la rotación y retención FIFO.

## Decisión

Se seleccionó la **Opción C: Almacén rotativo en archivos binarios planos con índice en memoria (RingBufferStore)**, debido a su óptima eficiencia en I/O, control estricto de capacidad y persistencia ante caídas del sistema en la Raspberry Pi.

Para solventar las desventajas del índice propio y los problemas del reloj dsPIC, se implementaron las siguientes soluciones:
1. **Robustez de rotación (tiempo monótono)**: Para evitar el bloqueo de rotación por el bug del dsPIC a medianoche, se utiliza `time.monotonic()` (tiempo monótono del host) como el criterio de duración primario para la rotación del archivo activo (5 minutos/300 seg). De esta forma, el archivo rota de forma determinista por tiempo físico transcurrido.
2. **Corrección de nombres de archivo**: Durante la rotación en el cambio de día, si la trama presenta exactamente 1 día de desfase con respecto al host, se nombra el archivo usando la hora actual UTC del host, manteniendo la coherencia cronológica en el disco.
3. **Control thread-safe**: El acceso al índice y los flujos de archivos están protegidos por un semáforo exclusivo de lectura y escritura (`threading.Lock()`).

## Consecuencias

- **Positivas**:
  - Adquisición continua y robusta ante reinicios del daemon.
  - Consumo mínimo de recursos en la Raspberry Pi.
  - Protección ante desvíos y anomalías horarias del hardware.
  - Permite realizar fallback transparente a archivos miniSEED horarios si la consulta del evento requiere un rango temporal más antiguo que el disponible en el Ring Buffer.
- **Negativas / Deuda técnica**:
  - La lectura de tramas para la exportación a miniSEED se realiza de manera secuencial dentro del subconjunto de archivos devueltos por el índice. Para rangos temporales extensos (varias horas), el rendimiento en I/O de lectura puede degradarse levemente.
- **Trabajo futuro**:
  - Monitorear el estado físico de desgaste de las tarjetas SD a mediano plazo debido al ciclo continuo de escritura/borrado.

## Referencias

- Sesiones de origen: 
  - [2026-06-16_ring_buffer_acelerografo.md](file:///home/rsa/git/institucional/RSA-Bitacora-LLM-Milton/sesiones/2026/06/2026-06-16_ring_buffer_acelerografo.md)
  - [2026-06-17_ring_buffer_fase4_event_extractor.md](file:///home/rsa/git/institucional/RSA-Bitacora-LLM-Milton/sesiones/2026/06/2026-06-17_ring_buffer_fase4_event_extractor.md)
- Contexto técnico relacionado:
  - [ring_buffer_store_context.md](file:///home/rsa/git/montajes/acelerografo-DEV00/docs/context/ring_buffer_store_context.md)
  - [test_ring_buffer_store_context.md](file:///home/rsa/git/montajes/acelerografo-DEV00/docs/context/test_ring_buffer_store_context.md)

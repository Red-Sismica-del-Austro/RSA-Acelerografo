---
## Contexto de Sesión — Acelerógrafo DEV00 / Fases 4 y 5 del Ring Buffer
**Directorio de trabajo exclusivo**: `montajes/acelerografo-DEV00`
**Fecha de última actualización**: 2026-06-18
---

## Estado de Implementación

### ✅ Fase 4 Completada — Integración MQTT en `event_extractor.py`
- **Archivos**:
  - `scripts/operation/mqtt/event_extractor.py`
  - `scripts/operation/mqtt/test_event_extractor.py` (rediseño completo de tests unitarios)
- **Funcionamiento**:
  - El coordinador MQTT (`mqtt_coordinator.py`) invoca la extracción asíncrona ante el comando `extract_event`.
  - `event_extractor.py` consulta de forma prioritaria en el `RingBufferStore` si el rango temporal solicitado `[start, start + duration]` está cubierto en el buffer circular de tramas crudas en disco.
  - Si los datos están cubiertos, se extraen las tramas crudas, se escribe un archivo temporal `{CODIGO}_{YYMMDD}-{HHMMSS}.dat` en el directorio de eventos extraídos y se llama a `binary_to_mseed.py --file` como subproceso utilizando el Python del entorno virtual (`.venv/bin/python3`).
  - El `.mseed` resultante de la conversión se mueve a su destino final y se elimina el archivo temporal `.dat` para evitar acumular basura.
  - La respuesta MQTT de la extracción incluye ahora la clave `"source"` con el valor `"ring_buffer"`.
  - Si el rango no está cubierto por el ring buffer, el sistema realiza de forma transparente un **fallback automático** al método tradicional de extracción de archivos horarios en disco (`extract_segment.py`), retornando `"source": "mseed_archive"`.

### ✅ Fase 5 Completada — Configuración, Logger y Pruebas Unitarias
- **Archivos**:
  - `scripts/operation/structured_logger.py` (métodos de logging de streaming añadidos)
  - `configuration/configuracion_dispositivo.json.template` (bloque de streaming añadido)
- **Detalle de Configuración**:
  - Se añadió la sección `"streaming"` al archivo de plantilla de configuración:
    ```json
    "streaming": {
        "habilitado": true,
        "ring_buffer": {
            "directorio": "/home/rsa/data/ring-buffer/",
            "max_size_mb": 500,
            "archivo_duracion_min": 5
        }
    }
    ```
- **Logging**:
  - Se agregaron los métodos estructurados en `StructuredLogger` para registrar la actividad de la cola y del ring buffer: `ring_write`, `ring_rotate`, `ring_cleanup`, `ring_query`, `pipe_read` y `pipe_error`.
- **Pruebas Unitarias**:
  - El script `test_event_extractor.py` corre como suite automatizado simulando el broker y la conversión a miniSEED usando `unittest.mock.patch`. Pasa **3/3 tests exitosamente**:
    1. Extracción exitosa desde el ring buffer.
    2. Fallback correcto a `extract_segment.py` por rango externo.
    3. Comportamiento de bypass directo si `streaming.habilitado` está en `False`.

---

## Formato de Mensajes MQTT para Pruebas

Para validar la extracción a través de la red MQTT (por ejemplo, con **MQTT Explorer**):

* **Tópico de Comando (Publish)**: `rsa/seismic/smart/DEV00/cmd/extract_event`
* **Tópico de Respuesta (Subscribe)**: `rsa/seismic/smart/DEV00/cmd/extract_event/res`
* **Payload JSON sugerido**:
  ```json
  {
    "start": "2026-06-18Z15:00:00",
    "duration": 30.0,
    "upload": false,
    "delete_after_upload": false,
    "request_id": "prueba-ringbuffer-f4"
  }
  ```
  *(Nota: Se sugiere usar un timestamp de los últimos 5 a 10 minutos para asegurar que los datos estén cargados en el ring buffer circular).*

---

## Procedimiento de Despliegue en Producción

Para propagar e iniciar estos cambios en el entorno de ejecución del acelerógrafo:

1. **Sincronizar scripts en producción**:
   Ejecuta `update.sh` y selecciona la opción 3 en el menú interactivo para mover los nuevos archivos modificados al directorio del proyecto local y re-hidratar las configuraciones.
2. **Reiniciar demonios de Supervisor**:
   Ejecuta manualmente en la terminal del equipo remoto:
   ```bash
   sudo supervisorctl restart mqtt_coordinator
   sudo supervisorctl restart stream_processor
   ```
3. **Verificación Directa (Python)**:
   Puedes validar la integración localmente sin brokers MQTT abriendo la consola interactiva de Python de producción:
   ```bash
   /home/rsa/projects/acelerografo-rsa/.venv/bin/python3
   ```
   Y ejecutando:
   ```python
   import sys, os, datetime
   sys.path.insert(0, "/home/rsa/projects/acelerografo-rsa/scripts")
   os.environ["PROJECT_LOCAL_ROOT"] = "/home/rsa/projects/acelerografo-rsa"
   from mqtt.event_extractor import extraer_y_subir_evento
   
   hace_5_min = datetime.datetime.utcnow() - datetime.timedelta(minutes=5)
   start_utc_str = hace_5_min.strftime("%Y-%m-%dZ%H:%M:%S")
   
   res = extraer_y_subir_evento(start=start_utc_str, duration=10.0, upload=False)
   print("Resultado:", res)
   ```
   El diccionario de retorno debe contener `"source": "ring_buffer"` y `"status": "completed"`.

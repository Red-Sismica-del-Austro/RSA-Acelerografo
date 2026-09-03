---
## Contexto de Sesión — Acelerógrafo DEV00 / Sistema Ring Buffer

**Directorio de trabajo exclusivo**: `montajes/acelerografo-DEV00`
**Fecha de última actualización**: 2026-06-16

---

## Estado de Implementación

### ✅ Fase 1 Completada — `core/frame_decoder.py`
- **Archivo**: `scripts/operation/core/frame_decoder.py`
- **Tests**: `scripts/operation/core/test_frame_decoder.py` → **27/27 pasados**
- **Hallazgo crítico**: el firmware del dsPIC escribe la fuente de reloj en `tramaDatos[0]`, pero el bucle de muestras sobreescribe inmediatamente ese byte con el ID de la primera muestra. Por eso los offsets reales en la trama almacenada en disco y en el pipe son:
  - **Bytes 0..2499**: 250 muestras × 10 bytes (el byte 0 es ID de muestra 0, no clock_source)
  - **Bytes 2500..2505**: Timestamp [año-2000, mes, día, hora, minuto, segundo]
  - `clock_source` siempre decodifica como `0` desde archivos en disco (es una limitación del firmware, no del decodificador)
- El módulo soporta dos métodos de extracción de fecha controlados por `usar_fecha_filename`:
  - `False`: desde bytes 2500-2502 de la trama (método tradicional)
  - `True`: desde el nombre del archivo (`ring_YYYYMMDD_HHMMSS.bin` o `CODIGO_AAMMDD-HHMMSS.dat`)
  - El campo `USAR_FECHA_FILENAME` de `configuracion_mseed.json` controla esto; actualmente está en `True` por el bug de fecha del dsPIC.

### ✅ Fase 2 Completada — `streaming/ring_buffer_store.py`
- **Archivos**:
  - `scripts/operation/streaming/__init__.py`
  - `scripts/operation/streaming/ring_buffer_store.py`
  - `scripts/operation/streaming/test_ring_buffer_store.py` → **19/19 pasados**
- **Ruta de producción del ring buffer**: `/home/rsa/data/ring-buffer/`
- Formato de archivo: `ring_YYYYMMDD_HHMMSS.bin` — concatenación directa de tramas de 2506 bytes, sin header adicional (compatible con `binary_to_mseed.py`).
- Rotación: cada 300 s (configurable); retención FIFO al superar 500 MB.
- Thread-safe con `threading.Lock`.

### 🔲 Fase 3 Pendiente — `streaming/stream_processor.py`
- Servicio daemon que lee `/tmp/my_pipe` y alimenta el `RingBufferStore`.
- Ver plan de implementación para especificación completa.

### 🔲 Fases 4 y 5 Pendientes
- Integración MQTT en `event_extractor.py` y configuración/pruebas finales.

---

## Decisiones de Diseño Confirmadas

| Decisión | Valor |
|----------|-------|
| Ruta del ring buffer | `/home/rsa/data/ring-buffer/` |
| Apertura del pipe | **Opción B: `O_RDWR`** — mantiene el fd abierto, evita ciclo open/EOF/close por trama |
| Campo `source` en MQTT | Incluir `"ring_buffer"` / `"mseed_archive"` en la respuesta de `extract_event` |
| Método de fecha en frame_decoder | Dual (`usar_fecha_filename`), configurado desde `configuracion_mseed.json` |

---

## Comportamiento del Named Pipe

`registro_continuo_4.5.0.c` abre el pipe con `O_WRONLY | O_NONBLOCK`, escribe y cierra en cada trama (ver `GuardarVector()` en el código fuente C). Con la **Opción B (O_RDWR)**, el `stream_processor` debe:
1. Abrir el pipe con `os.open(PIPE_PATH, os.O_RDWR)` — esto evita el EOF al no haber escritor.
2. Leer exactamente 2506 bytes en un bucle con acumulación para lecturas parciales.
3. Descartar tramas con timestamp inválido (hora>23, min>59, seg>59) y loguear con warning.
4. Manejar `SIGTERM`/`SIGINT` para cierre limpio con `ring_store.close()`.

---

## Rutas Clave del Proyecto

```
scripts/operation/
├── core/
│   ├── __init__.py               ✅
│   ├── frame_decoder.py          ✅
│   └── test_frame_decoder.py     ✅
├── streaming/
│   ├── __init__.py               ✅
│   ├── ring_buffer_store.py      ✅
│   ├── test_ring_buffer_store.py ✅
│   └── stream_processor.py       🔲 ← PRÓXIMO A IMPLEMENTAR
├── mqtt/
│   └── event_extractor.py        🔲 Fase 4
├── mseed/
│   └── binary_to_mseed.py        (sin cambios en esta fase)
└── structured_logger.py          (sin cambios)
```

---

## Documentación Técnica de Referencia

Para entender el contexto, leer los siguientes archivos de contexto técnico si se necesitan detalles adicionales:
- **Firmware dsPIC**: `docs/context/firmware_context.md`
- **Adquisición C (RPi)**: `docs/context/registro_continuo_context.md`
- **Conversión miniSEED**: `docs/context/binary_to_mseed_context.md`
- **MQTT y extracción**: `docs/context/mqtt_coordinator_context.md` y `docs/context/extract_segment_context.md`
- **Restricción SSHFS**: No ejecutar comandos autónomos en rutas bajo `montajes/**`. Delegar al usuario con el comando exacto.

---

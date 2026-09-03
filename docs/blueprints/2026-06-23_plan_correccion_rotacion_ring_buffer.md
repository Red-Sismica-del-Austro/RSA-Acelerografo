# Plan Definitivo: Corrección del Bug de Rotación del Ring Buffer

**Fecha**: 2026-06-23
**Severidad**: Crítica — producción afectada desde 2026-06-18

---

## Causa Raíz Confirmada

### Evidencia del diagnóstico en caliente

| Variable | Valor | Significado |
|----------|-------|-------------|
| `_archivo_activo` | `None` | `_rebuild_index()` NO reabre el archivo para escritura |
| `_archivo_activo_inicio_mono` | `None` | Sin referencia monotónica restaurada |
| `start_time` | `2026-06-18 23:57:30` | Primera trama del archivo |
| `end_time` | `2026-06-18 17:51:22` | `end < start` → la fecha queda fija en Jun 18 (del filename) |
| `frames` | 409,987 | 4.74 días de escritura continua = sin rotación |
| `size_mb` | 979.8 | Supera los 500 MB sin retención |
| `dir mtime` | Jun 21 09:59 | Última creación/eliminación de archivo en el directorio |
| `frames_procesados` (daemon) | 501,300 | Diferencia: 501,300 − 409,987 = 91,313 ≈ 25.4h |
| `time.monotonic()` | Funciona (1.001s test) | El reloj monotónico NO es el problema |

### Cronología reconstruida

1. **Jun 17 ~22:14 local (03:14 UTC Jun 18)**: El daemon arranca exitosamente tras resolver los permisos del pipe. Directorio vacío. `_rebuild_index()` no encuentra archivos.
2. **Primeras ~25.4 horas**: El daemon opera correctamente. La rotación crea archivos cada 5 min, la retención elimina los más viejos. ~91,313 tramas se procesan en archivos que luego son rotados y eliminados.
3. **~Jun 18 23:57 dsPIC / ~Jun 19 04:39 UTC**: Se crea `ring_20260618_235730.bin`. Hasta el Jun 21 09:59 (mtime del directorio), se producen algunos eventos más de creación/eliminación de archivos.
4. **A partir de cierto punto**: La rotación **deja de crear archivos nuevos**. El archivo `ring_20260618_235730.bin` crece indefinidamente acumulando 409,987 tramas (979 MB).

### Mecanismo del fallo: Colisión de nombres por `diff_dias >= 2`

El bug está en la interacción entre el bug de fecha del dsPIC y la lógica de naming en `_rotate_file()` ([líneas 390-395](file:///home/rsa/git/montajes/acelerografo-DEV00/scripts/operation/streaming/ring_buffer_store.py#L390)):

```python
ahora_utc = datetime.datetime.utcnow()
diff_dias = (ahora_utc.date() - timestamp.date()).days
ts_nombre = ahora_utc if diff_dias == 1 else timestamp
```

La corrección de naming fue diseñada para el caso `diff_dias == 1` (cruce de medianoche del primer día). **Pero cuando pasan más de 2 días**, `diff_dias` se convierte en 2, 3, 4... y la condición `diff_dias == 1` deja de cumplirse. A partir de ese momento:

- `ts_nombre = timestamp` → se usa la fecha del dsPIC (**siempre Jun 18**) y la hora del dsPIC.
- Como la hora del dsPIC cicla cada 24 horas, los nombres `ring_20260618_HHMMSS.bin` **se repiten cada 24 horas**.
- Cuando un nombre colisiona con un archivo que todavía existe en el búfer de retención (~11 horas de ventana), `open(nuevo_path, "wb")` **trunca silenciosamente** el archivo existente, destruyendo los datos.

Este truncamiento repetido mantiene un solo archivo activo (el que coincide con la hora actual del dsPIC) que se trunca y reescribe periódicamente. Sin embargo, en algún momento la interacción entre retención y colisiones convergió a un estado donde un solo archivo sobrevive y crece sin límite porque:
- Cada truncamiento reseteaba la `_archivo_activo_inicio_mono`, permitiendo 5 minutos más de escritura.
- Al siguiente intento de rotación, si el nombre colisiona con el archivo activo actual, `open("wb")` trunca el propio archivo activo.
- `_enforce_retention()` no puede actuar sobre un solo archivo (`len(self._index) <= 1`).

> [!CAUTION]
> **Resumen**: La corrección `diff_dias == 1` solo funciona el primer día. A partir del segundo día, los nombres generados por `_rotate_file()` ciclan con la fecha fija del dsPIC, causando colisiones con archivos existentes. La acumulación de entradas duplicadas en el `_index` (apuntando al mismo filepath) degrada progresivamente la lógica de retención hasta que un solo archivo crece indefinidamente.

### Defecto secundario: Logger invisible

[stream_processor.py línea 213](file:///home/rsa/git/montajes/acelerografo-DEV00/scripts/operation/streaming/stream_processor.py#L213) pasa `logger=None` al `RingBufferStore`. Los mensajes `RING_ROTATE`, `RING_REBUILD`, `RING_CLEANUP` se emitían al root logger de Python (sin handlers configurados), haciéndolos **completamente invisibles**.

### Defecto terciario: `_rebuild_index()` no reanuda el archivo activo

El diagnóstico confirmó que instanciar un `RingBufferStore` con un archivo existente deja `_archivo_activo = None`. La próxima escritura dispara `_rotate_file()` creando un archivo nuevo. Si el nombre colisiona (probable después de >1 día), se trunca el existente, perdiendo datos.

---

## Plan de Correcciones

### Corrección 1: Generalizar `diff_dias` para cubrir todos los días

**Archivo**: [ring_buffer_store.py línea 392](file:///home/rsa/git/montajes/acelerografo-DEV00/scripts/operation/streaming/ring_buffer_store.py#L392)

**Antes**:
```python
ts_nombre = ahora_utc if diff_dias == 1 else timestamp
```

**Después**:
```python
ts_nombre = ahora_utc if diff_dias >= 1 else timestamp
```

Esto asegura que cuando la fecha del dsPIC tiene **cualquier** cantidad de días de atraso respecto al host (1, 2, 5...), se use la fecha UTC del host para nombrar el archivo, evitando colisiones por fecha fija del dsPIC.

### Corrección 2: Prevención de colisión de nombres con sufijo incremental

Después de generar el nombre, verificar si el archivo ya existe en disco. Si existe, añadir un sufijo numérico:

```python
# Evitar colisión de nombres (protección ante edge cases)
if os.path.exists(nuevo_path):
    for i in range(1, 1000):
        nombre_alt = f"ring_{ts_str}_{i:03d}.bin"
        path_alt = os.path.join(self._directorio, nombre_alt)
        if not os.path.exists(path_alt):
            nuevo_path = path_alt
            nombre = nombre_alt
            break
```

### Corrección 3: `_rebuild_index()` reanuda el último archivo en modo append

Si hay archivos existentes al reconstruir el índice, reabrir el último en modo `"ab"` (append) para continuar la escritura sin truncar:

```python
# Al final de _rebuild_index(), después de poblar self._index:
if indice_recuperado:
    ultimo = indice_recuperado[-1]
    self._archivo_activo = open(ultimo.filepath, "ab")
    self._archivo_activo_path = ultimo.filepath
    self._archivo_activo_inicio = ultimo.start_time
    self._archivo_activo_inicio_mono = time.monotonic()
    self._archivo_activo_frame_count = ultimo.frame_count
```

### Corrección 4: Pasar el logger del `StreamProcessor` al `RingBufferStore`

**Archivo**: [stream_processor.py línea 213](file:///home/rsa/git/montajes/acelerografo-DEV00/scripts/operation/streaming/stream_processor.py#L213)

```diff
 self._ring_store = RingBufferStore(
     directorio=self._buffer_dir,
     max_size_mb=self._max_size_mb,
     archivo_duracion_s=self._archivo_duracion_s,
     usar_fecha_filename=self._usar_fecha_filename,
-    logger=None,  # Usamos nuestro propio logger
+    logger=self._logger,
 )
```

### Corrección 5: Logging diagnóstico en `_debe_rotar()`

Añadir un log de nivel DEBUG en `_debe_rotar()` que registre la decisión de rotación para facilitar el diagnóstico futuro.

---

## Pruebas Unitarias a Actualizar

| Test | Descripción |
|------|-------------|
| `test_rotacion_multiples_dias` | Simular escritura continua con dsPIC date fijo durante >2 días, verificar que no hay colisión de nombres y se crean archivos distintos |
| `test_rebuild_reanuda_archivo` | Crear archivos `.bin`, instanciar nuevo `RingBufferStore`, verificar que `_archivo_activo` apunta al último y está en modo append |
| `test_colision_nombre_sufijo` | Crear un archivo con nombre conocido, forzar rotación con mismo timestamp, verificar que se genera nombre con sufijo `_001` |
| `test_retencion_archivo_unico_gigante` | Verificar que un solo archivo mayor que `max_size_mb` no bloquea el sistema |

---

## Despliegue

1. Detener el daemon:
   ```bash
   sudo supervisorctl stop stream_processor
   ```
2. Respaldar el archivo actual (contiene ~5 días de datos sísmicos):
   ```bash
   cp /home/rsa/data/ring-buffer/ring_20260618_235730.bin /home/rsa/data/ring-buffer-backup/
   ```
3. Desplegar código corregido vía `update.sh` opción 3
4. Reiniciar:
   ```bash
   sudo supervisorctl start stream_processor
   ```
5. Verificar rotación cada 5 minutos:
   ```bash
   watch -n 30 'ls -la /home/rsa/data/ring-buffer/ && echo "---" && grep RING_ROTATE /home/rsa/projects/acelerografo/log-files/stream_processor.log | tail -5'
   ```

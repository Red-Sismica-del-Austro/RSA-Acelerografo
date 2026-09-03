# Resumen de Sesión: Identificación y Plan de Corrección del Bug de Rotación en Ring Buffer

**Fecha**: 2026-06-23  
**Repositorio**: `acelerografo-DEV00`  
**Agente de IA**: Antigravity  
**Usuario**: Milton  

---

## 🎯 Objetivo de la Sesión
El objetivo principal de la sesión fue diagnosticar y planificar la solución del bug crítico de rotación en el almacén de tramas binarias (`RingBufferStore`), el cual impedía que el buffer circular rotara correctamente, provocando que un solo archivo (`ring_20260618_235730.bin`) creciera indefinidamente (alcanzando 979.8 MB) y omitiendo la política de retención FIFO de 500 MB.

---

## 📂 Estructura del Repositorio Implementada
Estructura de directorios y archivos bajo análisis y modificación:

```text
montajes/acelerografo-DEV00/
├── docs/
│   └── progress/
│       ├── 2026-06-16_contexto-agente.md
│       ├── 2026-06-17_contexto-agente.md
│       ├── 2026-06-18_contexto-agente.md
│       └── 2026-06-23_contexto-agente.md (Nuevo)
└── scripts/
    └── operation/
        ├── core/
        │   └── frame_decoder.py
        └── streaming/
            ├── ring_buffer_store.py
            └── stream_processor.py
```

---

## ⚙️ Configuración del Entorno Virtual (`.venv`)
- **Entorno Virtual**: Localizado en `/home/rsa/projects/acelerografo-rsa/.venv/`.
- **Configuración de Streaming**: Definida en `configuration/configuracion_dispositivo.json.template` (con directivas de `streaming.habilitado: true`, `directorio: "/home/rsa/data/ring-buffer/"`, `max_size_mb: 500` y `archivo_duracion_min: 5`).
- **Control de Procesos**: El daemon de procesamiento `stream_processor` y el coordinador `mqtt_coordinator` son gestionados a través de Supervisor (`supervisorctl`).

---

## 🛠️ Modificaciones de Código y Refactorización
Durante esta sesión se realizó un diagnóstico exhaustivo en caliente del estado del ring buffer, identificando los siguientes fallos de diseño técnico y planificando sus correcciones correspondientes (pendientes de aplicación):

1. **Bug en `_rotate_file()` (Colisión por `diff_dias >= 2`)**:
   La lógica para corregir el bug de fecha del dsPIC al cruzar la medianoche generaba nombres basados en `utcnow()` si y solo si `diff_dias == 1`. Si el desfase superaba un día (por ejemplo, el dsPIC seguía estancado en Jun 18 mientras el sistema estaba en Jun 23), `diff_dias` pasaba a ser `5`, lo que causaba que `ts_nombre = timestamp` (Jun 18). Esto generaba nombres colisionantes tipo `ring_20260618_HHMMSS.bin` que se repetían cada 24 horas y truncaban silenciosamente los archivos existentes con `open(..., "wb")`.
   * **Corrección**: Cambiar la condición a `diff_dias >= 1`.

2. **Falta de nombres incrementales anti-colisión**:
   Si un archivo calculado ya existe por alguna regresión de reloj o reintento, el sistema lo abría en modo `"wb"`, truncando el contenido.
   * **Corrección**: Añadir sufijos del tipo `_001`, `_002` si el archivo destino existe.

3. **Inexistencia de reanudación al inicializar (`_rebuild_index()`)**:
   Al instanciar `RingBufferStore` tras un reinicio, `self._archivo_activo` se inicializaba en `None` en lugar de apuntar al último archivo activo del índice en memoria, disparando una rotación forzada e innecesaria en la primera escritura.
   * **Corrección**: Reabrir el último archivo en modo append (`"ab"`) y recuperar su contexto.

4. **Logger del `RingBufferStore` inactivo (Invisible)**:
   Se pasaba `logger=None` desde `stream_processor.py`, enviando los eventos `RING_ROTATE` y `RING_CLEANUP` al root logger que no tenía handlers asociados.
   * **Corrección**: Pasar `logger=self._logger` al instanciar.

---

## 📋 Pasos Sugeridos para el Siguiente Agente

Para continuar de inmediato con la implementación y resolución del bug, siga estos pasos de forma secuencial:

1. **Detener el daemon de Supervisor** para evitar escrituras concurrentes:
   ```bash
   sudo supervisorctl stop stream_processor
   ```

2. **Respaldar el archivo de datos gigante** en el directorio de respaldos:
   ```bash
   cp /home/rsa/data/ring-buffer/ring_20260618_235730.bin /home/rsa/data/ring-buffer-backup/
   ```

3. **Aplicar las modificaciones en `scripts/operation/streaming/ring_buffer_store.py`**:
   - Cambiar `diff_dias == 1` por `diff_dias >= 1` en `_rotate_file`.
   - Incorporar la lógica incremental en `_rotate_file` si `os.path.exists(nuevo_path)`.
   - Modificar `_rebuild_index()` para abrir el último archivo en modo `"ab"` y rellenar las variables del archivo activo (`_archivo_activo`, `_archivo_activo_path`, etc.).
   - Agregar un mensaje de log con nivel DEBUG en `_debe_rotar()`.

4. **Actualizar la inicialización en `scripts/operation/streaming/stream_processor.py`**:
   - Pasar `logger=self._logger` a la instancia de `RingBufferStore`.

5. **Actualizar e incorporar pruebas unitarias** en la suite del proyecto para validar:
   - Rotación multidía sin colisiones.
   - Reanudación del último archivo tras reconstruir el índice.
   - Sufijos incrementales ante nombres duplicados.
   - Comportamiento de retención con un único archivo gigante.

6. **Desplegar y Verificar**:
   - Ejecutar `update.sh` (opción 3) para sincronizar los archivos en producción.
   - Reiniciar el daemon: `sudo supervisorctl start stream_processor`.
   - Ejecutar un monitoreo en tiempo real: `watch -n 30 'ls -la /home/rsa/data/ring-buffer/ && echo "---" && grep RING_ROTATE /home/rsa/projects/acelerografo/log-files/stream_processor.log | tail -5'`.

# Resumen de Sesión: Corrección de bugs de remuestreo y offset de gravedad en el Worker GPD, y optimización de logs

**Fecha**: 2026-07-14  
**Repositorio**: `acelerografo-DEV00`  
**Agente de IA**: Antigravity (Google DeepMind)  
**Usuario**: Milton  

---

## 🎯 Objetivo de la Sesión
Depurar y resolver los errores del worker de inferencia GPD en tiempo real (`gpd_stream_worker.py`) en la Raspberry Pi, enfocándose en solucionar el fallo de inicialización por dependencias de NumPy, el problema de inferencias constantes producidas por bugs en el remuestreo en ARM y el offset de gravedad en el eje Z, y la reducción del volumen de logs para evitar el sobrellenado de disco.

---

## 📂 Estructura del Repositorio Implementada

```text
montajes/acelerografo-DEV00/
│
├── configuration/
│   └── configuracion_dispositivo.json.template     [MODIFICADO] Añadido parámetro "debug": false
│
├── requirements.txt                                [MODIFICADO] Bloqueo de numpy<2.0.0
│
├── scripts/operation/
│   ├── core/
│   │   └── signal_preprocessor.py                  [MODIFICADO] Implementado demean y casting float64
│   │
│   └── streaming/
│       ├── gpd_stream_worker.py                    [MODIFICADO] Reducción de logs por defecto e intro de --debug
│       ├── check_shm.py                            [NUEVO] Script de diagnóstico de SHM
│       └── check_preprocessor.py                   [NUEVO] Script de diagnóstico del preprocesador
```

---

## ⚙️ Configuración del Entorno Virtual (`.venv`)
- Se detectó un conflicto crítico: `tflite-runtime` está compilado para NumPy 1.x, mientras que `obspy` actualizó el entorno virtual a NumPy 2.x en ejecuciones previas, causando un fallo fatal de importación binaria (`_ARRAY_API not found`).
- **Solución**: Se editó `requirements.txt` forzando `numpy<2.0.0`. Al ejecutar `update.sh`, pip degradó NumPy a `1.26.4`, solucionando el problema de carga.

---

## 🛠️ Modificaciones de Código y Refactorización

### 1. Resolución de Remuestreo en ARM (SciPy bug)
- **Problema**: El script reportaba inferencias constantes de `noise=0.126 P=0.091 S=0.783`. El diagnóstico de preprocesamiento reveló que `scipy.signal.resample_poly` devolvía un array relleno de ceros en la Raspberry Pi (ARM) al recibir datos en formato `int32`.
- **Solución**: Se modificó `SignalPreprocessor.resample_frame()` en `signal_preprocessor.py` para realizar un casting explícito a `float64` antes de invocar `resample_poly()`.

### 2. Eliminación de Transitorio de Filtro por Gravedad
- **Problema**: El eje Z del sensor posee un offset de gravedad estático masivo de `~256k` counts. Al aplicar el filtro pasabanda IIR (`sosfiltfilt`) a la ventana de 8 segundos sin retirar el offset, se excitaba un transitorio de escalón gigantesco que ahogaba la vibración real y distorsionaba la normalización.
- **Solución**: Se integró una remoción de media (*demean*) por canal en `SignalPreprocessor.prepare_window()` previo al filtrado.

### 3. Reducción de Ruido en Logs
- **Problema**: El worker escribía un registro `DEBUG` por cada inferencia (una por segundo), haciendo crecer el archivo `gpd_stream_worker.log` excesivamente.
- **Solución**: Se ajustó el nivel de logging del archivo por defecto a `INFO`. Se agregó soporte para elevarlo a `DEBUG` temporalmente mediante la bandera CLI `--debug` o persistente mediante `"debug": true` en el bloque `gpd` del archivo de configuración.

---

## 📋 Pasos Sugeridos para el Siguiente Agente
1. **Verificación de Detecciones Reales**:
   - Monitorear el archivo `/home/rsa/projects/acelerografo/log-files/gpd_stream_worker.log` en el equipo remoto para verificar que la fluctuación de probabilidades continúe variando con el ruido del sensor.
   - Si se simula un sismo o golpe en el sensor, comprobar si supera el umbral de `0.95` en P o S y verificar que se gatille la extracción de eventos (`event_extractor.py`) de forma autónoma.
2. **Reversión del Modo de Adquisición**:
   - Si el dispositivo va a operar de manera permanente en campo en modo offline (autónomo), cambiar el valor de `"modo_adquisicion"` de `"online"` a `"offline"` en la sección `"dispositivo"` de `configuracion_dispositivo.json` (mediante el panel web de configuración Flask en el puerto `5000` o modificando el archivo directo en el dispositivo).
3. **Monitoreo de Estabilidad de Supervisor**:
   - Verificar de forma periódica el uptime de `gpd_worker` mediante `sudo supervisorctl status` para asegurar que no ocurran memory leaks u OOM (Out Of Memory) en el buffer circular de inferencia.

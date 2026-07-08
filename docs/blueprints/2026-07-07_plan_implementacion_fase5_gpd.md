# Plan de Implementación — Fase 5: Configuración, Supervisor y Pruebas de Integración

**Fecha**: 2026-07-07  
**Repositorio**: `acelerografo-DEV00`  
**Base**: [Plan general de inferencia GPD](file:///home/rsa/git/montajes/acelerografo-DEV00/docs/blueprints/2026-06-18_plan_inferencia_gpd_tiempo_real.md) + [Resumen de Fase 4 (Contexto)](file:///home/rsa/git/montajes/acelerografo-DEV00/docs/progress/2026-07-07_contexto-agente.md)

---

## 🎯 Resumen Ejecutivo

La Fase 5 cierra el ciclo de desarrollo de la inferencia GPD en tiempo real del acelerógrafo RSA. Esta fase se enfoca en operacionalizar los desarrollos completados en la Fase 4:

1. **Configuración del Servicio en Supervisor**: Permitir que `gpd_stream_worker.py` corra en segundo plano de manera persistente con reinicio automático.
2. **Automatización del Despliegue**: Modificar `update.sh` para copiar el archivo de servicio de Supervisor y el modelo TFLite (`models/gpd.tflite`) a producción.
3. **Pruebas y Verificación Integrada**: Definir el protocolo de pruebas de software (unitarias) e integración (en el hardware remoto) bajo la restricción SSHFS.

---

## 📂 Estructura de Archivos a Crear y Modificar

```text
montajes/acelerografo-DEV00/
│
├── configuration/
│   └── configuracion_dispositivo.json.template [VERIFICADO] Configuración gpd y shared_memory lista
│
├── scripts/task/
│   └── gpd_worker.conf                         [NUEVO] Configuración de Supervisor para el worker
│
├── scripts/setup/
│   └── update.sh                               [MODIFICADO] Copia del modelo TFLite y conf de Supervisor
│
└── docs/blueprints/
    └── 2026-07-07_plan_implementacion_fase5_gpd.md [NUEVO] Este plan
```

---

## 🛠️ Detalles de Implementación

### 1. Archivo Nuevo: `scripts/task/gpd_worker.conf`
Este archivo define la tarea del worker GPD para Supervisor.

- Se define `startsecs=10` porque la carga del modelo `gpd.tflite` e inicialización de librerías tarda entre 5 y 8 segundos en la Raspberry Pi 3B+.
- El worker se ejecuta bajo el usuario `rsa`.
- Redirección de logs a `log-files/supervisor_gpd_worker.log` y `err` correspondiente.

```ini
[program:gpd_worker]
command={{PROJECT_LOCAL_ROOT}}/.venv/bin/python3 {{PROJECT_LOCAL_ROOT}}/scripts/streaming/gpd_stream_worker.py
directory={{PROJECT_LOCAL_ROOT}}/scripts/streaming/
environment=PROJECT_LOCAL_ROOT="{{PROJECT_LOCAL_ROOT}}"
autostart=true
autorestart=true
startretries=3
startsecs=10
user=rsa
stdout_logfile={{PROJECT_LOCAL_ROOT}}/log-files/supervisor_gpd_worker.log
stderr_logfile={{PROJECT_LOCAL_ROOT}}/log-files/supervisor_gpd_worker.err
```

---

### 2. Modificación: `scripts/setup/update.sh`
Se agregará la lógica para:
- Copiar y templatedizar `gpd_worker.conf`.
- Copiar el modelo `models/gpd.tflite` a production (`$PROJECT_LOCAL_ROOT/models/`).

#### Fragmento de cambios en `update.sh`:

```bash
# --- En la función update_supervisor_config ---
    # --- gpd_worker ---
    local src_gpd="$PROJECT_GIT_ROOT/scripts/task/gpd_worker.conf"
    local temp_gpd="$PROJECT_LOCAL_ROOT/tmp-files/gpd_worker.conf.tmp"
    local dest_gpd="/etc/supervisor/conf.d/gpd_worker.conf"

    sed "s|{{PROJECT_LOCAL_ROOT}}|$PROJECT_LOCAL_ROOT|g" "$src_gpd" > "$temp_gpd"

    if [ ! -f "$dest_gpd" ] || ! cmp -s "$temp_gpd" "$dest_gpd"; then
        echo "Actualizando configuración de Supervisor: $dest_gpd"
        sudo cp "$temp_gpd" "$dest_gpd"
        sudo supervisorctl reread
        sudo supervisorctl update
    else
        echo "No se detectaron cambios en la configuración de Supervisor (gpd_worker)."
    fi
```

```bash
# --- Al final del script, antes de update_venv_if_changed ---
# Copiar modelo TFLite para GPD
mkdir -p "$PROJECT_LOCAL_ROOT/models"
if [ -f "$PROJECT_GIT_ROOT/models/gpd.tflite" ]; then
    cp "$PROJECT_GIT_ROOT/models/gpd.tflite" "$PROJECT_LOCAL_ROOT/models/"
    echo "Modelo GPD TFLite copiado a producción."
else
    echo "Advertencia: No se encontró el modelo $PROJECT_GIT_ROOT/models/gpd.tflite para copiar."
fi
```

---

### 3. Verificación de la Configuración
La sección `streaming.gpd` y `streaming.shared_memory` en `configuracion_dispositivo.json.template` ya está configurada adecuadamente:

```json
        "shared_memory": {
            "habilitado": true,
            "ruta": "/dev/shm/rsa_current_frame"
        },
        "gpd": {
            "habilitado": true,
            "modelo_ruta": "models/gpd.tflite",
            "umbral_p": 0.95,
            "umbral_s": 0.95,
            "cooldown_s": 30,
            "ventana_pre_evento_s": 60,
            "ventana_post_evento_s": 60,
            "auto_extract": true,
            "auto_upload": true,
            "filtro": {
                "habilitado": true,
                "freq_min_hz": 3.0,
                "freq_max_hz": 20.0
            }
        }
```

---

## 📋 Protocolo de Pruebas y Validación (Delegación por SSHFS)

Debido a la limitación de **Restricción SSHFS**, no se pueden correr comandos en el hardware remoto de forma autónoma. El usuario ejecutará manualmente los siguientes pasos para validar la Fase 5:

### Paso 1: Ejecución de Tests Unitarios de Registro
Verificar que la lógica de registro CSV no tenga fallos ni dependencias ausentes:
```bash
cd /home/rsa/projects/acelerografo-rsa
.venv/bin/python3 -m pytest scripts/core/test_event_logger.py -v
```

### Paso 2: Despliegue de Cambios mediante `update.sh`
Actualizar archivos de producción, configuraciones de Supervisor y copiar el modelo TFLite:
```bash
cd /home/rsa/projects/acelerografo-rsa
sudo ./scripts/setup/update.sh
```

### Paso 3: Verificar el Estado de Supervisor
Confirmar que el servicio `gpd_worker` ha sido registrado y está activo:
```bash
sudo supervisorctl status
```
*Resultado esperado*: Los 4 procesos (`stream_processor`, `mqtt_coordinator`, `config_server`, `gpd_worker`) deben reportar estado `RUNNING`.

### Paso 4: Monitoreo de Inicialización de `gpd_worker`
Verificar que el worker cargó correctamente el modelo TFLite y está a la escucha de la memoria compartida:
```bash
tail -n 50 -f /home/rsa/projects/acelerografo-rsa/log-files/supervisor_gpd_worker.log
```
*Resultado esperado*: Registro de carga del modelo `models/gpd.tflite` y arranque del loop principal.

### Paso 5: Prueba de Integración E2E (Modo Online)
Simular una detección GPD local publicando un mensaje MQTT para forzar la extracción automática coordinada.

1. Suscribirse a los tópicos de respuesta en una terminal:
   ```bash
   mosquitto_sub -h localhost -t "+/cmd/extract_event/res" -v
   ```
2. Publicar una detección sintética simulada:
   ```bash
   mosquitto_pub -h localhost -t "DEV00/events/detected" -m '{"type": "P", "probability": 0.98, "timestamp": "2026-07-07T22:00:00.000Z", "station_id": "DEV00", "model": "gpd.tflite", "source": "streaming"}'
   ```
3. Verificar en el log del coordinador (`/home/rsa/projects/acelerografo-rsa/log-files/supervisor_mqtt_coordinator.log`) que:
   - Se recibe la detección local.
   - Se inicia la extracción de ventana de 120s (60s antes y después de `22:00:00.000`).
   - Se actualiza el CSV en `/home/rsa/data/eventos-detectados/YYYY-MM_detecciones.csv` a `confirmado=True` y se escribe el nombre del archivo `.mseed` generado.

### Paso 6: Prueba de Integración E2E (Modo Offline)
1. Modificar temporalmente `modo_adquisicion` a `"offline"` en `/home/rsa/projects/acelerografo-rsa/configuracion/configuracion_dispositivo.json`.
2. Reiniciar el worker GPD:
   ```bash
   sudo supervisorctl restart gpd_worker
   ```
3. Simular la detección en el worker (por ejemplo, introduciendo señal o forzando la publicación interna). El worker debería extraer directamente el MiniSEED sin publicar a MQTT y actualizar su CSV de forma autónoma.
4. Restaurar la configuración a `"online"` si se completó la prueba.

---

## ⚠️ Riesgos y Mitigaciones en la Fase 5

| Riesgo | Impacto | Mitigación |
|---|---|---|
| Supervisor considera crasheado a `gpd_worker` al tardar la inicialización de TFLite | El servicio entra en bucle de reinicios rápidos | `startsecs=10` en `gpd_worker.conf` le da suficiente margen al intérprete para cargarse. |
| Modelo `gpd.tflite` ausente en el repositorio de Git | El servicio no puede iniciar en producción | Validación en `update.sh` que previene el error e informa en los logs si el archivo del modelo no existe. |
| Permisos insuficientes al copiar `gpd_worker.conf` | Error al reiniciar Supervisor | Uso de `sudo cp` y `sudo supervisorctl` en `update.sh`. |

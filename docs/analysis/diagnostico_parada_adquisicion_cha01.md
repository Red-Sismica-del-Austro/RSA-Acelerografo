# Diagnóstico Técnico: Interrupción de Adquisición y Subida de Datos en Estación CHA1

**Fecha**: 2026-09-01  
**Estación / Dispositivo afectado**: CHA1 (CHA01)  
**Estado**: Diagnosticado / Mitigado localmente / Pendiente de despliegue global  
**Severidad/Prioridad**: Alta (Afectó la adquisición continua, el streaming y las subidas a Google Drive en la estación afectada)  

---

## 1. Resumen Ejecutivo

Durante la monitorización de la flota de 6 estaciones acelerográficas, se detectó que la estación **CHA1** había dejado de subir datos horarios y detecciones sísmicas a Google Drive. El análisis de los registros reveló que el problema no residía en las credenciales o el servicio de Google Drive (el cual completó exitosamente subidas pendientes una vez restablecida la conectividad el 2026-08-28), sino en una **parada no recuperada del proceso de adquisición base (`registro_continuo_4.5.0.c`) tras un reinicio del sistema el 27 de agosto a las 19:17 UTC**.

Esta interrupción provocó un fallo en cascada por dependencias entre procesos: la desaparición del named pipe (`/tmp/my_pipe`) causó que `stream_processor` cayera en bucle de error, impidiendo la creación del segmento de memoria compartida (`/dev/shm/rsa_current_frame`) y congelando el Ring Buffer. En consecuencia, el trabajador de inferencia neuronal (`gpd_stream_worker`) quedó inoperativo, la conversión horaria a MiniSEED no generó nuevos archivos y las solicitudes remotas de extracción de sismos por MQTT fallaron por ausencia de cobertura temporal de datos. La intervención manual (limpieza de pipe y reinicio coordinado de servicios) restableció exitosamente el pipeline completo.

---

## 2. Evidencia y Análisis de Logs

* **Ruta de los logs analizados**: `/home/rsa/projects/acelerografo/log-files/` (copia de auditoría en `/home/rsa/git/tmp-extern-files/log-files/`).
  * `registro_continuo.log`
  * `supervisor_stream_processor.err` y `stream_processor.log`
  * `supervisor_gpd_worker.err` y `gpd_stream_worker.log`
  * `supervisor_mqtt.err` y `mqtt_coordinator.log`
  * `gestor_acq.log`, `mseed.log` y `drive.log`
  * `mqtt_state.json`

* **Extractos relevantes de logs**:
  * **`registro_continuo.log`** (Último registro antes de la congelación):
    ```text
    2026-08-27 19:00:00 - INFO - Archivo cerrado: /home/rsa/projects/acelerografo/datos/RC/CHA1_260827-180000.dat
    2026-08-27 19:00:00 - INFO - Archivo creado: /home/rsa/projects/acelerografo/datos/RC/CHA1_260827-190000.dat
    ```
  * **`mqtt_state.json`** (Reinicio del sistema registrado):
    ```json
    {
        "on": "2026-08-27T19:17:14Z",
        "online": "2026-08-28T01:19:25Z",
        "offline": "2026-08-18T14:12:43Z"
    }
    ```
  * **`supervisor_stream_processor.err`** (Fallo de permisos y ausencia de FIFO):
    ```text
    PermissionError: [Errno 13] Permission denied: '/tmp/my_pipe'
    ...
    FileNotFoundError: Named pipe no encontrado: /tmp/my_pipe. ¿Está corriendo registro_continuo?
    ```
  * **`gpd_stream_worker.log`** (Incapacidad de abrir memoria compartida):
    ```text
    2026-09-01 10:48:56,172 [ERROR] [GPD_SHM_FAIL] No se pudo abrir el SHM al arrancar: SHM no disponible tras 30s de espera: /dev/shm/rsa_current_frame. Terminando.
    ```
  * **`gestor_acq.log`** (Omisión de subidas por falta de nuevos MiniSEED):
    ```text
    2026-09-01 09:05:08,829 - gestor_archivos - INFO - [RESUMEN] archivos_subidos=0/0 | archivos_omitidos=637 | razon=ya_subidos
    ```
  * **`supervisor_mqtt.err`** (Fallo en extracción regional solicitada por la red):
    ```text
    INFO:CHA1_mqtt_coordinator.log:[EVENT_EXTRACTOR] Rango solicitado [2026-08-31 17:49:30 a 2026-08-31 17:51:30] fuera de la cobertura del ring buffer [2026-08-26 19:22:36 a 2026-08-27 19:46:03]
    INFO:CHA1_mqtt_coordinator.log:[ERROR] | error=[EVENT_EXTRACTOR] extract_segment.py falló (código 1): Error: No se encontraron archivos miniSEED para la fecha 20260831 en /home/rsa/data/mseed/
    INFO:CHA1_mqtt_coordinator.log:[EXTRACT_EVENT] Pipeline finalizado → status=error, archivo=None
    ```

* **Cronología del evento**:
  1. **2026-08-27 19:00:00 UTC**: `registro_continuo` rota y abre `CHA1_260827-190000.dat`.
  2. **2026-08-27 19:17:14 UTC**: Ocurre un reinicio en la estación `CHA1`. El servicio base de adquisición no reanuda su ejecución correctamente o colapsa al inicio.
  3. **2026-08-27 19:17:15 UTC**: Supervisor levanta `stream_processor`, el cual falla con `PermissionError` y luego `FileNotFoundError` sobre `/tmp/my_pipe`. Entra en bucle de crash continuo.
  4. **2026-08-27 a 2026-09-01**: `gpd_stream_worker` reinicia en bucle cada 30 segundos por falta de `/dev/shm/rsa_current_frame`. `binary_to_mseed.py` reconvierte cíclicamente el archivo estancado del 27 de agosto. `gestor_archivos_acq.py` omite todos los archivos ya subidos.
  5. **2026-08-31**: Las órdenes MQTT para extracción de eventos externos fallan porque no hay datos temporales disponibles ni en el ring buffer ni en MiniSEED.
  6. **2026-09-01 15:10:37 UTC**: Se aplica la intervención técnica: eliminación de `/tmp/my_pipe`, reinicio de `rsa-acelerografo.service` y de los procesos de Supervisor. El pipeline completo vuelve a estado nominal.

---

## 3. Hallazgos y Causa Raíz (Root Cause Analysis)

### Hallazgo 1: Detención y falta de auto-recuperación de `registro_continuo`
* **Descripción técnica**: El binario en C `registro_continuo_4.5.0` se detuvo tras el reinicio del sistema y no volvió a ejecutarse.
* **Causa**: A diferencia de los componentes en Python que operan bajo **Supervisor** con directivas `autorestart=true`, `registro_continuo` corre a nivel de sistema (habitualmente vía servicio systemd o script de inicio). Si el servicio no cuenta con `Restart=always` o si falló la inicialización SPI con el microcontrolador dsPIC durante el arranque, el servicio queda en estado `failed` o `inactive` indefinidamente.
* **Condiciones de activación**: Ocurrió exclusivamente en `CHA1` debido a un evento local de alimentación eléctrica o reinicio en caliente. Adicionalmente, `registro_continuo` carece de un protocolo de re-sincronización robusto si el dsPIC no responde de inmediato con la interrupción `0xB2`.

### Hallazgo 2: Conflicto de permisos en el FIFO (`PermissionError: /tmp/my_pipe`)
* **Descripción técnica**: `stream_processor` no pudo abrir el FIFO en modo lectura/escritura (`os.O_RDWR | os.O_NONBLOCK`).
* **Causa**: `registro_continuo` se ejecuta como superusuario (`root`) para manipular periféricos GPIO/SPI (`wiringPi`/`bcm2835`). Al crear el named pipe mediante `mkfifo("/tmp/my_pipe", 0666)`, la máscara del proceso (`umask`) de root limitó los permisos a `0644` (`prw-r--r--`). Cuando `stream_processor` arrancó bajo el usuario sin privilegios `rsa`, el kernel denegó la apertura con permisos de escritura.
* **Condiciones de activación**: Se manifiesta cuando el pipe es creado por root sin forzar explícitamente un `chmod(PIPE_NAME, 0666)` posterior al `mkfifo()`.

### Hallazgo 3: Efecto Dominó en la Arquitectura de Streaming y Extracción
* **Descripción técnica**: El colapso del proceso productor (`registro_continuo`) no solo detuvo el guardado en disco, sino que bloqueó las capas desacopladas de Ring Buffer, inferencia neuronal (GPD) y el coordinador regional MQTT.
* **Causa**:
  1. Sin `/tmp/my_pipe`, `stream_processor` no arranca y no publica en `/dev/shm/rsa_current_frame`.
  2. `gpd_stream_worker` no puede consumir tramas ni alimentar el modelo TFLite.
  3. Al recibir solicitudes MQTT `cmd/extract_event`, `mqtt_coordinator.py` no encuentra cobertura en el Ring Buffer ni archivos MiniSEED generados en disco, provocando el fallo del comando con `status=error`.

---

## 4. Mitigaciones / Acciones Aplicadas en la Estación

Para restablecer la estación `CHA1` se ejecutaron las siguientes acciones en la Raspberry Pi:

1. **Limpieza del named pipe huérfano**:
   ```bash
   sudo rm -f /tmp/my_pipe
   ```
2. **Reinicio forzado del servicio de adquisición**:
   ```bash
   sudo systemctl restart rsa-acelerografo.service
   ```
3. **Reinicio de procesos dependientes en Supervisor**:
   ```bash
   sudo supervisorctl restart stream_processor gpd_worker mqtt_coordinator
   ```
4. **Verificación de operatividad**:
   - `stream_processor.log`: Pipe abierto en fd=5 (`O_RDWR|O_NONBLOCK`), memoria compartida creada y bucle de lectura iniciado (`[STREAM_LOOP]`).
   - `gpd_stream_worker.log`: Segmento SHM enlazado (`[GPD_SHM_OK]`), cliente MQTT conectado e inferencia en ejecución (`[GPD_START]`, `[GPD_BUF]`).

---

## 5. Puntos de Mejora y Recomendaciones para la Flota (Backlog)

Para evitar la repetición de este incidente en las 6 estaciones de la red sísmica, se recomiendan las siguientes mejoras:

1. **Garantizar permisos en la creación del Named Pipe en C (`registro_continuo.c`)**:
   - Forzar explícitamente permisos `0666` tras la llamada a `mkfifo()` mediante `chmod(PIPE_NAME, 0666);` o ajustando temporalmente `umask(0);` antes de su creación.
2. **Robustecer el archivo de servicio Systemd (`rsa-acelerografo.service`)**:
   - Configurar reinicio automático y limpieza previa del pipe huérfano en `/etc/systemd/system/rsa-acelerografo.service`:
     ```ini
     [Service]
     Restart=always
     RestartSec=5
     ExecStartPre=/bin/rm -f /tmp/my_pipe
     ```
3. **Manejo defensivo de apertura de pipe en `stream_processor.py`**:
   - En lugar de abortar inmediatamente con `STREAM_FATAL` cuando el pipe no existe o tiene error de permisos transitorio al arrancar, implementar un ciclo de reintentos con backoff exponencial antes de terminar el daemon.
4. **Alerta de telemetría por latencia de adquisición**:
   - Incorporar en `mqtt_coordinator.py` un watchdog periódico de salud que publique un estado `warning`/`critical` al broker MQTT central si no se detectan nuevas tramas en el Ring Buffer durante más de 5 minutos, permitiendo la detección temprana de nodos congelados.

---
proyecto: acelerografo
tipo: diagnostico_tecnico
resolucion: pendiente
temas: [adquisicion, streaming, ring-buffer, named-pipe, supervisor, gdrive]
fecha: 2026-09-01
---

# Diagnóstico Técnico: Interrupción de Adquisición y Subida de Datos en Estación CHA1

**Fecha**: 2026-09-01  
**Proyecto / Repositorio**: `RSA-Acelerografo`  
**Componente(s) afectado(s)**: `registro_continuo_4.5.0.c`, `stream_processor.py`, `gpd_stream_worker.py`, `binary_to_mseed.py`, `gestor_archivos_acq.py`, `mqtt_coordinator.py`  
**Estado**: Mitigado localmente | Pendiente de despliegue global  
**Severidad**: Alta  

---

## 1. Resumen Ejecutivo

Durante la monitorización de la flota de 6 estaciones acelerográficas de la Red Sísmica del Austro (RSA), se detectó que la estación **CHA1** (configurada internamente como `CHA01`) dejó de reportar y subir datos continuos en formato MiniSEED y detecciones sísmicas a Google Drive. La sospecha inicial apuntaba a una falla en las credenciales o el servicio de Google Drive; sin embargo, la auditoría profunda de logs demostró que el gestor de subidas operaba normalmente (completando 27/27 subidas pendientes tras resolver una intermitencia de DNS el 28 de agosto).

La causa raíz real fue una **parada total del proceso de adquisición continua (`registro_continuo_4.5.0.c`) tras un reinicio del sistema ocurrido el 27 de agosto a las 19:17 UTC**. Al no reiniciarse este proceso base, el named pipe `/tmp/my_pipe` quedó con permisos restrictivos o desapareció, desatando un efecto dominó que colapsó a `stream_processor`, congeló el Ring Buffer, impidió la creación de la memoria compartida `/dev/shm/rsa_current_frame` y dejó a `gpd_stream_worker` en un bucle continuo de reinicios. Al no existir nuevos datos `.dat`, la conversión horaria se estancó y `gestor_archivos_acq.py` omitió todos los archivos por estar ya subidos.

La aplicación de mitigaciones manuales en el nodo (limpieza de FIFO y reinicio ordenado de systemd y Supervisor) restableció el pipeline completo. Se documentan aquí las causas técnicas, la evidencia cronológica y las mejoras necesarias para inmunizar a la flota ante eventos similares.

---

## 2. Estado Actual

| Componente | Estado Pre-Intervención | Estado Post-Intervención | Observaciones |
|---|---|---|---|
| `registro_continuo_4.5.0.c` | ❌ Inoperativo | ✅ Operativo | Proceso C detenido desde 2026-08-27 19:17 UTC. Restablecido vía systemd. |
| `/tmp/my_pipe` (FIFO) | ❌ Inaccesible / Ausente | ✅ Operativo | Bloqueado por permisos (`0644 root`) y luego eliminado. Recreado con permisos nominales. |
| `stream_processor.py` | ❌ Bucle de Crash | ✅ Operativo | Fallaba con `PermissionError` y `FileNotFoundError`. Ahora procesa tramas y escribe al Ring Buffer. |
| `/dev/shm/rsa_current_frame` | ❌ Inexistente | ✅ Operativo | Segmento SHM Seqlock creado y mapeado correctamente. |
| `gpd_stream_worker.py` | ❌ Bucle de Crash | ✅ Operativo | Reintentaba cada 30 s por falta de SHM. Inferencia en tiempo real activa y buffer de 8 s lleno. |
| `binary_to_mseed.py` | ⚠️ Estancado | ✅ Operativo | Reconvertía repetitivamente el último `.dat` existente. Listo para procesar nuevos bloques horarios. |
| `gestor_archivos_acq.py` | ⚠️ Sin datos nuevos | ✅ Operativo | Omitía 637 archivos ya subidos. Listo para subir los nuevos MiniSEED en la próxima hora. |
| `mqtt_coordinator.py` | ⚠️ Fallo en extracciones | ✅ Operativo | Conectado a MQTT; las extracciones fallaban por falta de datos en Ring Buffer. Ahora operativo. |

---

## 3. Evidencia y Análisis

* **Ruta de los recursos analizados**:
  * Logs locales de la estación: `/home/rsa/projects/acelerografo/log-files/`
  * Archivos de auditoría externa: `/home/rsa/git/tmp-extern-files/log-files/`
  * Verificación de restablecimiento: `/home/rsa/git/logs.tmp`

* **Extractos relevantes**:

  * **1. `registro_continuo.log`** — Último archivo generado antes del cese de adquisición:
    ```text
    2026-08-27 19:00:00 - INFO - Archivo cerrado: /home/rsa/projects/acelerografo/datos/RC/CHA1_260827-180000.dat
    2026-08-27 19:00:00 - INFO - Archivo creado: /home/rsa/projects/acelerografo/datos/RC/CHA1_260827-190000.dat
    ```

  * **2. `mqtt_state.json`** — Registro de reinicio del dispositivo:
    ```json
    {
        "on": "2026-08-27T19:17:14Z",
        "online": "2026-08-28T01:19:25Z",
        "offline": "2026-08-18T14:12:43Z"
    }
    ```

  * **3. `supervisor_stream_processor.err`** — Conflicto de permisos y ausencia del named pipe:
    ```text
    PermissionError: [Errno 13] Permission denied: '/tmp/my_pipe'
    Traceback (most recent call last):
      File "/home/rsa/projects/acelerografo/scripts/streaming/stream_processor.py", line 231, in run
        self._abrir_pipe()
      File "/home/rsa/projects/acelerografo/scripts/streaming/stream_processor.py", line 286, in _abrir_pipe
        raise FileNotFoundError("Named pipe no encontrado: /tmp/my_pipe. ¿Está corriendo registro_continuo?")
    FileNotFoundError: Named pipe no encontrado: /tmp/my_pipe. ¿Está corriendo registro_continuo?
    ```

  * **4. `gpd_stream_worker.log`** — Bucle de espera y terminación por SHM ausente:
    ```text
    2026-09-01 10:48:56,172 [ERROR] [GPD_SHM_FAIL] No se pudo abrir el SHM al arrancar: SHM no disponible tras 30s de espera: /dev/shm/rsa_current_frame. Terminando.
    2026-09-01 10:48:56,792 [INFO] [GPD_STOP] GPDStreamWorker detenido.
    ```

  * **5. `gestor_acq.log`** — Estado de subidas a Google Drive sin nuevos datos:
    ```text
    2026-09-01 09:05:08,829 - gestor_archivos - INFO - [RESUMEN] archivos_subidos=0/0 | archivos_omitidos=637 | razon=ya_subidos
    ```

  * **6. `supervisor_mqtt.err`** — Fallo en extracción regional por falta de cobertura temporal:
    ```text
    INFO:CHA1_mqtt_coordinator.log:[EVENT_EXTRACTOR] Rango solicitado [2026-08-31 17:49:30 a 2026-08-31 17:51:30] fuera de la cobertura del ring buffer [2026-08-26 19:22:36 a 2026-08-27 19:46:03]
    INFO:CHA1_mqtt_coordinator.log:[ERROR] | error=[EVENT_EXTRACTOR] extract_segment.py falló (código 1): Error: No se encontraron archivos miniSEED para la fecha 20260831 en /home/rsa/data/mseed/
    INFO:CHA1_mqtt_coordinator.log:[EXTRACT_EVENT] Pipeline finalizado → status=error, archivo=None
    ```

  * **7. `logs.tmp`** — Verificación del restablecimiento nominal:
    ```text
    2026-09-01 15:10:37,993 - stream_processor - INFO - [PIPE_OPEN] Pipe abierto: /tmp/my_pipe (fd=5, O_RDWR|O_NONBLOCK)
    2026-09-01 15:10:37,993 - stream_processor - INFO - [STREAM_LOOP] Iniciando bucle de lectura.
    2026-09-01 15:10:41,256 [INFO] [GPD_SHM_OK] SHM abierto: /dev/shm/rsa_current_frame
    2026-09-01 15:10:41,256 [INFO] [GPD_START] Bucle de inferencia iniciado.
    2026-09-01 15:10:41,263 [INFO] [GPD_BUF] Llenando buffer: 1/8 tramas (1 s)
    ```

* **Cronología del evento**:
  1. **2026-08-27 19:00:00 UTC**: `registro_continuo` realiza rotación horaria normal y crea `CHA1_260827-190000.dat`.
  2. **2026-08-27 19:17:14 UTC**: Ocurre un reinicio en la estación `CHA1` (registrado en `mqtt_state.json`).
  3. **2026-08-27 19:17:15 UTC**: `stream_processor` arranca vía Supervisor. Falla al abrir `/tmp/my_pipe` por permisos denegados (`PermissionError`) y posteriormente por desaparición del pipe (`FileNotFoundError`).
  4. **2026-08-27 a 2026-09-01**: `stream_processor` y `gpd_stream_worker` reinician en bucle continuo. El cron horario reconvierte repetitivamente el último `.dat` estancado. `gestor_archivos_acq.py` no encuentra archivos nuevos para subir.
  5. **2026-08-31 UTC**: Órdenes MQTT de extracción de eventos regionales fallan con `status=error` por falta de cobertura en Ring Buffer y disco.
  6. **2026-09-01 15:10:37 UTC**: Se aplica la mitigación técnica en la estación, logrando el restablecimiento total.

---

## 4. Hallazgos y Causa Raíz

### Hallazgo 1: Detención y falta de auto-recuperación de `registro_continuo_4.5.0.c`
* **Descripción técnica**: El proceso principal de adquisición en C no reanudó su ejecución tras el reinicio del sistema a las 19:17 UTC.
* **Causa raíz**: El servicio systemd responsable de la adquisición (`rsa-acelerografo.service`) carecía de directivas de auto-reinicio (`Restart=always`). Al fallar la sincronización SPI inicial con el microcontrolador dsPIC33 durante el arranque en caliente, el proceso terminó y el sistema operativo lo dejó en estado `failed`/`inactive`.
* **Condiciones de activación**: Afectó exclusivamente a `CHA1` debido a una fluctuación de energía local que reinició la Raspberry Pi sin resetear en frío el microcontrolador dsPIC.

### Hallazgo 2: Conflicto de permisos en el FIFO (`PermissionError: /tmp/my_pipe`)
* **Descripción técnica**: `stream_processor.py` fue incapaz de abrir el FIFO en modo lectura/escritura (`os.O_RDWR | os.O_NONBLOCK`).
* **Causa raíz**: `registro_continuo` corre con privilegios de `root` (acceso directo a periféricos SPI/GPIO vía `bcm2835`). La llamada `mkfifo("/tmp/my_pipe", 0666)` heredó la máscara por defecto del superusuario (`umask 022`), asignando permisos `0644` (`prw-r--r--`). Cuando `stream_processor` ejecutó bajo el usuario no privilegiado `rsa`, el kernel denegó el acceso de escritura.
* **Condiciones de activación**: Ocurre siempre que el pipe sea creado por un proceso root sin un `chmod(PIPE_NAME, 0666)` explícito o ajuste de `umask(0)`.

### Hallazgo 3: Efecto Dominó por Acoplamiento en la Capa de Streaming e Inferencia
* **Descripción técnica**: La caída del productor primario paralizó completamente las capas desacopladas de inferencia neuronal en tiempo real (GPD) y el coordinador regional MQTT.
* **Causa raíz**: `stream_processor` maneja la ausencia del FIFO como un error irrecuperable (`STREAM_FATAL`), terminando inmediatamente y destruyendo `/dev/shm/rsa_current_frame`. `gpd_stream_worker` tiene un timeout estricto de 30 s para encontrar la memoria compartida, terminando con `GPD_SHM_FAIL`.
* **Condiciones de activación**: Ocurre en cualquier escenario donde `registro_continuo` demore más de 30 segundos en inicializarse o sufra un reinicio desfasado respecto a Supervisor.

---

## 5. Evaluación de Riesgo

| # | Escenario | Probabilidad | Impacto | Mitigación Requerida |
|---|---|---|---|---|
| R1 | Microcorte eléctrico en cualquier estación de la flota que detenga `registro_continuo`. | Alta | Crítico (pérdida total de datos en la estación) | Configurar `Restart=always` y `ExecStartPre` en systemd. |
| R2 | Creación de `/tmp/my_pipe` con permisos `0644` impidiendo la apertura por `stream_processor`. | Media | Alto (parálisis de Ring Buffer e inferencia GPD) | Forzar `chmod 0666` en C y reintentos en Python. |
| R3 | Desincronización silenciosa donde la estación no alerta a la red central de que dejó de adquirir. | Alta | Medio (detección tardía del incidente) | Watchdog en `mqtt_coordinator` que publique alerta si el Ring Buffer se congela > 5 min. |

---

## 6. Opciones y Decisiones

### Decisión 1: Estrategia de Permisos y Ciclo de Vida del FIFO `/tmp/my_pipe`

| Opción | Descripción | Ventaja | Desventaja |
|---|---|---|---|
| A | Forzar `chmod(PIPE_NAME, 0666)` en `registro_continuo_4.5.0.c`. | Solución directa en el código fuente; garantiza permisos independientemente del entorno. | Requiere recompilar y desplegar el binario C en las estaciones. |
| B | Gestionar el pipe mediante `ExecStartPre` y permisos en el servicio Systemd. | No requiere recompilación de código C; se aplica por configuración de OS. | Si el binario recrea el pipe en tiempo de ejecución, puede sobreescribir los permisos. |
| C | Enfoque híbrido (A + B): `chmod` en código C y limpieza previa en Systemd. | Máxima robustez y defensa en profundidad ante cualquier tipo de reinicio. | Requiere actualizar tanto el binario C como la plantilla del servicio. |

> **Recomendación**: Implementar la **Opción C** para garantizar que tanto a nivel de sistema operativo como a nivel de aplicación el pipe sea accesible por el usuario `rsa`.

---

## 7. Mitigaciones Aplicadas

En la estación afectada (`CHA1`), se ejecutaron las siguientes acciones correctivas manuales:

1. **Purga de named pipe residual**:
   ```bash
   sudo rm -f /tmp/my_pipe
   ```
2. **Reinicio de adquisición base**:
   ```bash
   sudo systemctl restart rsa-acelerografo.service
   ```
3. **Reinicio de daemons en Supervisor**:
   ```bash
   sudo supervisorctl restart stream_processor gpd_worker mqtt_coordinator
   ```
4. **Validación operativa**:
   - Confirmación de apertura de `/tmp/my_pipe` en fd=5 con `O_RDWR|O_NONBLOCK`.
   - Inicialización exitosa de `/dev/shm/rsa_current_frame`.
   - Conexión e inicio nominal del bucle de inferencia en `gpd_stream_worker.py`.

---

## 8. Backlog de Mejoras

1. **Permisos explícitos en `registro_continuo_4.5.0.c`**:
   - Agregar `chmod(PIPE_NAME, 0666);` inmediatamente después de `mkfifo(PIPE_NAME, 0666);` en la rutina de inicio de `registro_continuo`.
2. **Robustecimiento del servicio Systemd (`rsa-acelerografo.service`)**:
   - Actualizar la plantilla del servicio para incluir:
     ```ini
     [Service]
     Restart=always
     RestartSec=5
     ExecStartPre=/bin/rm -f /tmp/my_pipe
     ```
3. **Reintentos resilientes en `stream_processor.py`**:
   - Reemplazar la excepción fatal inmediata por un bucle de reintento con backoff exponencial al intentar abrir el pipe al inicio.
4. **Monitoreo de latencia de adquisición en `mqtt_coordinator.py`**:
   - Implementar un chequeo periódico que reporte estado `warning` al broker si la última trama en el Ring Buffer supera los 5 minutos de antigüedad.

---

## 9. Dependencias y Prerrequisitos

| Prerrequisito | Estado | Acción Requerida |
|---|---|---|
| Acceso SSH a las 6 estaciones de la flota | ✅ Disponible | Desplegar la actualización de configuración y binario C. |
| Toolchain de compilación en Raspberry Pi (`gcc`, `libbcm2835-dev`, `wiringpi`) | ✅ Disponible | Recompilar `registro_continuo_4.5.0.c` con el ajuste de permisos. |
| Permisos de sudo en estaciones | ✅ Disponible | Modificar `/etc/systemd/system/rsa-acelerografo.service`. |

---

## 10. Plan de Validación

| # | Checkpoint | Criterio de Éxito |
|---|---|---|
| CP-1 | Simulación de reinicio de servicio `rsa-acelerografo.service` | `/tmp/my_pipe` se crea con permisos `prw-rw-rw-` (`0666`) y propietario verificable. |
| CP-2 | Simulación de fallo en `registro_continuo` (`kill -9`) | Systemd reinicia automáticamente el proceso en menos de 5 segundos sin intervención. |
| CP-3 | Verificación de Supervisor tras parada transitoria | `stream_processor` y `gpd_stream_worker` se reconectan automáticamente al reaparecer el pipe y SHM. |
| CP-4 | Ciclo horario de subida a Google Drive | `binary_to_mseed.py` y `gestor_archivos_acq.py` procesan y suben los MiniSEED de forma ininterrumpida. |

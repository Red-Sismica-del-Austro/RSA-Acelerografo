# Resumen de Sesión: Auto-Recuperación (Self-Healing) en Streaming, Depuración de Falsos Positivos de Google Drive y Modernización de Comandos de Operación

**Fecha**: 2026-09-15  
**Repositorio**: `acelerografo-DEV00`  
**Agente de IA**: Antigravity  
**Usuario**: Milton Muñoz  

---

## 🎯 Objetivo de la Sesión

Resolver dos condiciones de advertencia operativas reportadas por la telemetría MQTT en la estación de pruebas `DEV00`, modernizar las herramientas de línea de comandos del operador y actualizar la memoria técnica institucional:
1. **Diagnosticar y corregir el estancamiento de adquisición en el Ring Buffer (`status: warning, reason: stale_data`)**: Identificar por qué `stream_processor.py` dejaba de registrar datos al Ring Buffer tras reinicios o paradas de seguridad (`cmd/stop_acquisition_safety`), implementando una solución de auto-recuperación (Self-Healing) resiliente ante recreaciones de inodo en el named pipe (`/tmp/my_pipe`).
2. **Diagnosticar y eliminar falsos positivos en el auditor de Google Drive (`failed_uploads_protected: 1, reason: upload_retry_retained`)**: Verificar el estado real de los archivos retenidos en disco, erradicar discrepancias entre el registro histórico JSON y el almacenamiento físico, y sanear la base de datos de subidas.
3. **Modernizar integralmente el script de operaciones de campo (`ayuda.sh`)**: Depurar comandos obsoletos (`extraerevento`, `conversor_mseed.py`), incorporar comandos de control de adquisición continua, consulta de systemd, sincronización manual y auditoría de Google Drive, y control exhaustivo de servicios en Supervisor.
4. **Sincronizar y consolidar la memoria técnica institucional**: Actualizar contextos técnicos (`stream_processor_context.md`, `drive_watchdog_context.md`, `ayuda_context.md`), enmendar los registros de decisiones arquitectónicas `ADR-006` y `ADR-020` tanto en el repositorio local de la estación como en `RSA-Metodologias`, y catalogar las actualizaciones en el índice federado.

---

## 📂 Estructura del Repositorio Implementada

```text
montajes/acelerografo-DEV00/
├── docs/
│   ├── adr/
│   │   ├── 006_apertura_named_pipe_lectura_escritura.md                       # [MODIFICADO] Enmienda Self-Healing por recreación de inodo
│   │   └── 020_telemetria_especializada_cadencia_unificada_y_parada_seguridad_estaciones.md # [MODIFICADO] Verificación física en disco contra falsos positivos
│   ├── context/
│   │   ├── ayuda_context.md                                                   # [NUEVO] Contexto técnico y matriz de comandos de ayuda.sh
│   │   ├── drive_watchdog_context.md                                          # [MODIFICADO] Filtro de presencia física y suite de 8 tests
│   │   └── stream_processor_context.md                                        # [MODIFICADO] Lógica Self-Healing, diagrama Mermaid y 23 tests
│   └── progress/
│       ├── 2026-09-14_contexto-agente.md
│       └── 2026-09-15_contexto-agente.md                                      # [NUEVO] Este documento de transición técnica
└── scripts/
    ├── operation/
    │   ├── mqtt/
    │   │   ├── drive_watchdog.py                                              # [MODIFICADO] Filtrado archivos_disco para failed_uploads_protected
    │   │   └── test_drive_watchdog.py                                         # [MODIFICADO] Test de exclusión de archivos no presentes físicamente (8/8)
    │   └── streaming/
    │       ├── stream_processor.py                                            # [MODIFICADO] Self-Healing: _pipe_es_valido() y _reconectar_pipe()
    │       └── test_stream_processor.py                                       # [MODIFICADO] 23 tests de inodo, buffers y reconexión (100% OK)
    └── task/
        └── ayuda.sh                                                           # [MODIFICADO] Comandos actuales de adquisición, Drive, Supervisor y mantenimiento
```

---

## ⚙️ Configuración del Entorno Virtual (`.venv`)

El entorno operativo reside en la Raspberry Pi 3B+ bajo la ruta:
`/home/rsa/projects/acelerografo/.venv/` (Python 3.9+ / Raspberry Pi OS Bullseye/Bookworm).

* **Aislamiento de Dependencias**:
  - `stream_processor.py` utiliza librerías de la biblioteca estándar (`os`, `time`, `logging`, `math`, `struct`) y no requiere paquetes externos adicionales, garantizando baja sobrecarga de memoria en el subproceso de adquisición.
  - `drive_watchdog.py` opera dentro de la suite de telemetría de `mqtt_coordinator.py`, empleando `shutil` y `json` estándar para inspeccionar `/home/rsa/data/mseed`.
  - La ejecución de scripts de sincronización manual (`gestor_archivos_acq.py`) en `ayuda.sh` fue configurada apuntando explícitamente al intérprete del entorno virtual (`$PROJECT_LOCAL_ROOT/.venv/bin/python3`) para prevenir conflictos con los paquetes del sistema o dependencias faltantes en entornos no interactivos.

---

## 🛠️ Modificaciones de Código y Refactorización

### 1. Auto-Recuperación (Self-Healing) en `StreamProcessor` (`stream_processor.py`)
* **Problema Raíz**: Al reiniciar `rsa-acelerografo.service` o invocar la orden remota `cmd/stop_acquisition_safety`, la directiva de systemd `ExecStartPre=/bin/rm -f /tmp/my_pipe` desvincula (`unlink`) el nodo del FIFO en el sistema de ficheros. Al reiniciar el ejecutable en C (`registro_continuo`), este crea un nuevo FIFO con un `st_ino` completamente diferente. Aunque Python mantenía el descriptor abierto con `os.O_RDWR` (según ADR-006), dicho descriptor quedaba asociado al inodo huérfano (`deleted`), provocando que `os.read()` retornara siempre 0 bytes (`BlockingIOError` o `b''`), dejando sordo al daemon indefinidamente.
* **Solución Implementada**:
  - `_pipe_es_valido()`: Compara `os.fstat(self._fd).st_ino == os.stat(self._pipe_path).st_ino`. Detecta eliminación del FIFO o divergencia de inodos.
  - `_reconectar_pipe()`: Cierra de forma segura el descriptor huérfano, limpia el acumulador de bytes parciales y entra en un bucle de espera con backoff exponencial hasta que el nuevo FIFO esté disponible en `/tmp/my_pipe`.
  - En `_bucle_lectura()`, ante lecturas vacías o excepciones de I/O no bloqueante, se valida el inodo a una cadencia de 1 segundo sin esperar el timeout largo de 10 segundos, reanudando la captura instantáneamente.
* **Validación**: 23/23 pruebas unitarias aprobadas en `test_stream_processor.py` y validación empírica en caliente deteniendo y arrancando el servicio de C en la estación remota (`[PIPE_RECONNECT]` → `[PIPE_RECONNECTED]`).

### 2. Inmunidad a Falsos Positivos en Google Drive (`drive_watchdog.py`)
* **Problema Raíz**: En `uploaded_files_registry.json` constaba una entrada de archivo fallido (`DEV0_20260907_155830.mseed`). Dicho archivo ya no existía en disco (había sido purgado/rotado), pero el watchdog leía ciegamente las claves del JSON y computaba `failed_uploads_protected = 1`, disparando alertas permanentes `upload_retry_retained`.
* **Solución Implementada**:
  - En `_obtener_datos_legacy()` y `_obtener_datos_manager()`, se aplicó una intersección estricta: `protegidos = {f for f in protegidos if f in archivos_disco}`.
  - Se añadieron pruebas en `test_drive_watchdog.py` validando que claves huérfanas en el registro sean ignoradas si el archivo físico no reside en `/home/rsa/data/mseed` (8/8 pruebas aprobadas).
  - En la estación, se invocó la rutina nativa `DriveStatusManager.limpiar_archivos_inexistentes()`, dejando el registro en un estado nominal y limpio.

### 3. Actualización de Utilidades de Operación (`ayuda.sh`)
* **Depuración**: Eliminadas referencias obsoletas a `extraerevento` y al script no mantenido `conversor_mseed.py`.
* **Adquisición Continua**:
  - Agregado `registrocontinuo restart` y alias `reiniciar`.
  - Agregado `sudo systemctl status rsa-acelerografo.service` para auditoría directa del daemon en C.
  - Mantenidos `comprobar` y `sudo resetmaster`.
* **Google Drive**:
  - Comando de subida manual mediante `$PROJECT_LOCAL_ROOT/.venv/bin/python3 .../gestor_archivos_acq.py --verbose`.
  - Modo simulación con flag `--dry-run`.
  - Visualización del log de subidas (`tail -n 50 -f /home/rsa/data/mseed/subida_drive.log`).
  - Inspección del registro de sincronización (`cat /home/rsa/data/mseed/uploaded_files_registry.json`).
* **Supervisor**:
  - Comandos para los 4 servicios core: `config_server`, `gpd_worker`, `mqtt_coordinator`, `stream_processor`.
  - Comandos globales: `status`, `restart all`, `reread`, `update` y seguimiento de logs en vivo con `tail -f`.
* **Mantenimiento**: Verificación de punto de acceso Wi-Fi (`wifiap`) e información del sistema (`informacion`).

### 4. Actualización de Contextos y Memoria Semántica (ADRs)
* Creado [`ayuda_context.md`](file:///home/rsa/git/montajes/acelerografo-DEV00/docs/context/ayuda_context.md) y actualizados [`stream_processor_context.md`](file:///home/rsa/git/montajes/acelerografo-DEV00/docs/context/stream_processor_context.md) y [`drive_watchdog_context.md`](file:///home/rsa/git/montajes/acelerografo-DEV00/docs/context/drive_watchdog_context.md).
* Actualizados **ADR-006** (incorporando la sección de Self-Healing ante recreación de inodo) y **ADR-020** (incorporando validación física en disco contra falsos positivos) en `montajes/acelerografo-DEV00/docs/adr/` y `rsa/RSA-Metodologias/decisiones/`.
* Actualizados [`indice_tematico.md`](file:///home/rsa/git/rsa/RSA-Metodologias/indice/indice_tematico.md) e [`index.md`](file:///home/rsa/git/rsa/RSA-Metodologias/decisiones/index.md) en el repositorio central de metodologías.

---

## 📋 Pasos Sugeridos para el Siguiente Agente

1. **Instalar el script actualizado de `ayuda` en la estación**:
   - En la estación `DEV00`, ejecutar `./menu.sh` (Opción 3: Actualizar) para que el nuevo contenido de `scripts/task/ayuda.sh` sea copiado a `/usr/local/bin/ayuda`.
   - Probar la ejecución interactiva escribiendo `ayuda` en la terminal remota y verificar la correcta visualización de los nuevos comandos de Supervisor y Google Drive.
2. **Monitoreo de Telemetría en Grafana / MQTT**:
   - Monitorear durante 24 horas el comportamiento del tópico `rsa/seismic/smart/DEV0/status/drive` y `rsa/seismic/smart/DEV0/status/acquisition`.
   - Constatar que no se produzcan regresiones tras reinicios programados o paradas de contingencia.
3. **Replicar en Estaciones Adicionales**:
   - Una vez consolidada la estabilidad en `DEV00`, propagar estas enmiendas (`stream_processor.py`, `drive_watchdog.py`, `ayuda.sh`) hacia las estaciones de producción en campo (`CHA01`, `PNS01`, etc.) mediante el flujo de actualización estándar.

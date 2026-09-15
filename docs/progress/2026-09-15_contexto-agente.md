# Resumen de Sesión: Auto-Recuperación en Streaming, Corrección en Drive y Task-Script de Diagnóstico Automatizado de Telemetría

**Fecha**: 2026-09-15  
**Repositorio**: `acelerografo-DEV00`  
**Agente de IA**: Antigravity  
**Usuario**: Milton Muñoz  

---

## 🎯 Objetivo de la Sesión

Consolidar la resiliencia operativa y la capacidad de auto-diagnóstico asistido por IA de la estación acelerográfica `DEV00`:
1. **Resolver alertas en telemetría MQTT (Self-Healing en Streaming y Falsos Positivos de Drive)**:
   - Corregir el estancamiento de adquisición en el Ring Buffer (`status: warning, reason: stale_data`) implementando auto-recuperación (Self-Healing) ante recreación de inodos en el named pipe (`/tmp/my_pipe`).
   - Corregir discrepancias históricas en `drive_watchdog.py` para ignorar archivos fallidos que ya no existen físicamente en disco (`upload_retry_retained`).
2. **Diseñar e Implementar el Task-Script de Diagnóstico Automatizado (`diagnostico.sh`)**:
   - Generar un blueprint de 4 fases para crear una herramienta CLI que recolecte de forma automática evidencia del estado general del sistema, pipeline de adquisición SPI, integridad del sensor y sincronización de Google Drive.
   - Implementar `scripts/task/diagnostico.sh` y verificar su despliegue a `/usr/local/bin/diagnostico` (Opción 3 de `menu.sh`).
   - Validar en producción la generación del reporte `$PROJECT_LOCAL_ROOT/log-files/diagnostico_report.log` contra los estados nominales de los tópicos MQTT.
3. **Actualizar Documentación Operativa y Contexto Técnico**:
   - Integrar la sección de Diagnóstico Automatizado en `scripts/task/ayuda.sh`.
   - Generar la documentación de contexto técnico `docs/context/diagnostico_context.md` y archivar el blueprint en `docs/blueprints/`.

---

## 📂 Estructura del Repositorio Implementada

```text
montajes/acelerografo-DEV00/
├── docs/
│   ├── adr/
│   │   ├── 006_apertura_named_pipe_lectura_escritura.md                       # [MODIFICADO] Enmienda Self-Healing por recreación de inodo
│   │   └── 020_telemetria_especializada_cadencia_unificada_y_parada_seguridad_estaciones.md # [MODIFICADO] Verificación física en disco contra falsos positivos
│   ├── blueprints/
│   │   └── 2026-09-15_plan_diagnostico_automatizado_telemetria.md             # [NUEVO] Plan detallado de 4 fases para diagnostico.sh
│   ├── context/
│   │   ├── ayuda_context.md                                                   # [NUEVO] Contexto técnico y matriz de comandos de ayuda.sh
│   │   ├── diagnostico_context.md                                             # [NUEVO] Contexto técnico para agentes IA y guía de interpretación
│   │   ├── drive_watchdog_context.md                                          # [MODIFICADO] Filtro de presencia física y suite de tests
│   │   └── stream_processor_context.md                                        # [MODIFICADO] Lógica Self-Healing, diagrama Mermaid y tests
│   └── progress/
│       ├── 2026-09-14_contexto-agente.md
│       └── 2026-09-15_contexto-agente.md                                      # [ACTUALIZADO] Este documento de transición técnica
└── scripts/
    ├── operation/
    │   ├── mqtt/
    │   │   ├── drive_watchdog.py                                              # [MODIFICADO] Filtrado archivos_disco para failed_uploads_protected
    │   │   └── test_drive_watchdog.py                                         # [MODIFICADO] Test de exclusión de archivos no presentes físicamente
    │   └── streaming/
    │       ├── stream_processor.py                                            # [MODIFICADO] Self-Healing: _pipe_es_valido() y _reconectar_pipe()
    │       └── test_stream_processor.py                                       # [MODIFICADO] Tests de validación de inodo y reconexión
    └── task/
        ├── ayuda.sh                                                           # [MODIFICADO] Incorporación sección Diagnóstico Automatizado
        └── diagnostico.sh                                                     # [NUEVO] Script de recolección y diagnóstico para agentes IA
```

---

## ⚙️ Configuración del Entorno Virtual (`.venv`)

El entorno operativo reside en la Raspberry Pi 3B+ bajo:
`/home/rsa/projects/acelerografo/.venv/` (Python 3.9+).

* **Sin Dependencias Nuevas**:
  - `diagnostico.sh` es Bash puro y utiliza únicamente herramientas nativas de Linux (`df`, `uptime`, `vcgencmd`, `systemctl`, `supervisorctl`, `grep`, `tail`, `find`, `stat`, `ping`).
  - Para auditar el acelerómetro, `diagnostico.sh` invoca directamente `$PROJECT_LOCAL_ROOT/.venv/bin/python3 $PROJECT_LOCAL_ROOT/scripts/acelerografo/comprobar_registro_wrapper.py`, garantizando acceso limpio a las librerías del proyecto sin alterar el entorno global del sistema.

---

## 🛠️ Modificaciones de Código y Refactorización

### 1. Auto-Recuperación (Self-Healing) en `StreamProcessor` (`stream_processor.py`)
* **Problema**: Tras reinicios del servicio en C (`rsa-acelerografo.service`), el FIFO `/tmp/my_pipe` se recreaba con un nuevo `st_ino`, dejando huérfano el descriptor de lectura de Python y deteniendo la escritura al Ring Buffer.
* **Solución**: Detección activa de divergencia de inodos (`_pipe_es_valido`) y reconexión automática en caliente con backoff exponencial (`_reconectar_pipe`).

### 2. Saneamiento de Falsos Positivos en Google Drive (`drive_watchdog.py`)
* **Problema**: Registros JSON con archivos fallidos retenidos que ya habían sido purgados físicamente disparaban permanentemente `upload_retry_retained`.
* **Solución**: Intersección de archivos protegidos contra los archivos físicamente presentes en `/home/rsa/data/mseed/`.

### 3. Task-Script de Diagnóstico Automatizado (`scripts/task/diagnostico.sh`)
* **Objetivo**: Proveer un script que ante una alerta en `rsa/seismic/smart/*/status/*` recopile inmediatamente el estado completo del sistema y genere `$PROJECT_LOCAL_ROOT/log-files/diagnostico_report.log`.
* **Canales y Sintaxis**:
  - `diagnostico` o `diagnostico all`: Diagnóstico integral (General + Adquisición + Sensor + Drive).
  - `diagnostico acquisition`: Inspección de `systemd`, `journalctl`, `stream_processor`, `/tmp/my_pipe`, `ring-buffer/` y descriptores activos.
  - `diagnostico sensor`: Ejecución del wrapper, detalle de archivo, lecturas físicas triaxiales y reloj.
  - `diagnostico drive`: Registro de subidas, backlog MiniSEED en disco, `gestor_acq.log` y ping a Google APIs.
  - Bandera `--quiet` / `-q`: Modo silencioso para automatización (no imprime a consola, solo genera el log).
* **Validación en Producción**:
  - Desplegado mediante Opción 3 de `menu.sh` a `/usr/local/bin/diagnostico`.
  - Ejecutado en vivo y validado con el archivo de salida [logs.tmp](file:///home/rsa/git/logs.tmp):
    - Hardware: 63.3 °C, sin estrangulamiento (`throttled=0x0`).
    - 4 daemons de Supervisor en `RUNNING`.
    - Descriptor 5 de `stream_processor` conectado al FIFO.
    - Sensor reportando valores físicos en reposo (`ax: 0.425`, `ay: 0.129`, `az: 9.586`) con reloj sincronizado.
    - 0 archivos MiniSEED pendientes y sincronización con Google Drive nominal.

### 4. Actualización de Utilidades de Operación (`ayuda.sh`)
* Se agregó la sección de ayuda para `diagnostico`, permitiendo que el operador descubra los comandos de diagnóstico selectivo y la ubicación del reporte consolidado.
* Despliegue verificado en `/usr/local/bin/ayuda`.

### 5. Documentación de Memoria Técnica
* **Blueprint**: Guardado en `docs/blueprints/2026-09-15_plan_diagnostico_automatizado_telemetria.md`.
* **Contexto Técnico**: Creado `docs/context/diagnostico_context.md`, documentando el propósito, la arquitectura de recolección y la matriz de interpretación para agentes IA.

---

## 📋 Pasos Sugeridos para el Siguiente Agente

1. **Monitoreo Pasivo de Telemetría**:
   - Vigilar los tópicos MQTT `rsa/seismic/smart/DEV0/status/*` para constatar estabilidad continua tras las mejoras.
2. **Consumo del Reporte ante Incidencias**:
   - Si un watchdog notifica una advertencia o error (ej. `stale_data`, `accelerometer_anomaly`, `pending_backlog`), invocar `diagnostico [canal]` y cargar `$PROJECT_LOCAL_ROOT/log-files/diagnostico_report.log` como contexto primario para identificar la causa raíz de forma instantánea.
3. **Propagación a Estaciones de Campo**:
   - Tras consolidar las pruebas en la estación piloto `DEV00`, desplegar los cambios en las estaciones remotas (`CHA01`, `PNS01`, etc.) mediante el flujo Git y `menu.sh`.

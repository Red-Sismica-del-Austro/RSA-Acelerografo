#!/bin/bash

# ===================================================================
# diagnostico.sh - Script de Diagnóstico Automatizado de Telemetría
# Red Sísmica del Austro (RSA)
#
# Genera un reporte consolidado de salud del sistema, adquisición,
# sensor y almacenamiento en $PROJECT_LOCAL_ROOT/log-files/diagnostico_report.log
# ===================================================================

# Cargar variables de entorno del sistema si existen
if [ -f /usr/local/bin/project_paths ]; then
    source /usr/local/bin/project_paths
fi

# Si PROJECT_LOCAL_ROOT no está definido, usar la ruta estándar
if [ -z "$PROJECT_LOCAL_ROOT" ]; then
    PROJECT_LOCAL_ROOT="/home/rsa/projects/acelerografo"
fi

VENV_PYTHON="$PROJECT_LOCAL_ROOT/.venv/bin/python3"
LOG_DIR="$PROJECT_LOCAL_ROOT/log-files"
REPORT_FILE="$LOG_DIR/diagnostico_report.log"

# Asegurar existencia del directorio de logs
mkdir -p "$LOG_DIR"

# Parseo de argumentos
QUIET=false
TARGET_CHANNEL="all"

for arg in "$@"; do
    case "$arg" in
        -q|--quiet)
            QUIET=true
            ;;
        acquisition|sensor|drive|all)
            TARGET_CHANNEL="$arg"
            ;;
        -h|--help)
            echo "Uso: diagnostico [--quiet|-q] [all|acquisition|sensor|drive]"
            echo "  all          : Ejecuta diagnóstico completo (por defecto)"
            echo "  acquisition  : Inspecciona servicio systemd, stream_processor, pipe y ring buffer"
            echo "  sensor       : Ejecuta wrapper y evalúa acelerómetro y reloj"
            echo "  drive        : Verifica sincronización, backlog MiniSEED y almacenamiento"
            echo "  --quiet, -q  : Modo silencioso (no imprime a terminal, solo escribe a $REPORT_FILE)"
            exit 0
            ;;
        *)
            echo "Advertencia: Parámetro desconocido '$arg'. Opciones válidas: all, acquisition, sensor, drive, --quiet"
            ;;
    esac
done

# Función: Diagnóstico General del Sistema
diagnostico_general() {
    echo "--- SECCIÓN: ESTADO GENERAL DEL SISTEMA ---"
    echo "[Información del Sistema]"
    date --iso-8601=seconds 2>/dev/null || date -Iseconds 2>/dev/null || date
    hostname 2>/dev/null
    uptime 2>/dev/null
    echo ""

    echo "[Hardware Raspberry Pi]"
    if command -v vcgencmd >/dev/null 2>&1; then
        vcgencmd measure_temp 2>&1
        vcgencmd get_throttled 2>&1
    else
        echo "vcgencmd no disponible en este sistema"
    fi
    echo ""

    echo "[Espacio en Disco]"
    df -h
    echo ""

    echo "[Estado de Servicios Supervisor]"
    if command -v supervisorctl >/dev/null 2>&1; then
        sudo supervisorctl status 2>&1
    else
        echo "supervisorctl no disponible"
    fi
    echo ""

    echo "[Estado Servicio rsa-acelerografo.service]"
    if command -v systemctl >/dev/null 2>&1; then
        sudo systemctl status rsa-acelerografo.service --no-pager -l 2>&1
    else
        echo "systemctl no disponible"
    fi
    echo ""
}

# Función: Diagnóstico de Adquisición
diagnostico_acquisition() {
    echo "--- SECCIÓN: DIAGNÓSTICO ADQUISICIÓN ---"
    echo "[1. Estado del servicio systemd (registro_continuo en C)]"
    if command -v systemctl >/dev/null 2>&1; then
        sudo systemctl status rsa-acelerografo.service --no-pager -l 2>&1
        echo ""
        echo "[Últimos 30 logs de systemd]"
        sudo journalctl -u rsa-acelerografo.service --no-pager -n 30 2>&1
    else
        echo "systemctl no disponible"
    fi
    echo ""

    echo "[2. Estado del proceso stream_processor (Supervisor)]"
    if command -v supervisorctl >/dev/null 2>&1; then
        sudo supervisorctl status stream_processor 2>&1
    fi
    echo "--- Últimas 50 líneas de supervisor_stream_processor.log ---"
    if [ -f "$LOG_DIR/supervisor_stream_processor.log" ]; then
        tail -n 50 "$LOG_DIR/supervisor_stream_processor.log" 2>&1
    else
        echo "Archivo supervisor_stream_processor.log no encontrado"
    fi
    echo "--- Últimas 20 líneas de supervisor_stream_processor.err ---"
    if [ -f "$LOG_DIR/supervisor_stream_processor.err" ]; then
        tail -n 20 "$LOG_DIR/supervisor_stream_processor.err" 2>&1
    else
        echo "Archivo supervisor_stream_processor.err no encontrado"
    fi
    echo ""

    echo "[3. Inspección del Named Pipe /tmp/my_pipe]"
    ls -la /tmp/my_pipe 2>&1
    stat /tmp/my_pipe 2>&1
    echo ""

    echo "[4. Estado del Ring Buffer]"
    if [ -d /home/rsa/data/ring-buffer ]; then
        echo "Listado de /home/rsa/data/ring-buffer/ (10 más recientes):"
        ls -lt /home/rsa/data/ring-buffer/ 2>&1 | head -10
        echo "Últimos 5 archivos ring_*.bin por fecha de modificación:"
        find /home/rsa/data/ring-buffer/ -name "ring_*.bin" -printf "%T+ %p\n" 2>/dev/null | sort -r | head -5
    else
        echo "Directorio /home/rsa/data/ring-buffer no existe"
    fi
    echo ""

    echo "[5. Verificación de proceso stream_processor y descriptores de pipe]"
    PROC_PIDS=$(pgrep -f stream_processor.py 2>/dev/null)
    if [ -n "$PROC_PIDS" ]; then
        echo "PID(s) stream_processor: $PROC_PIDS"
        for pid in $PROC_PIDS; do
            echo "Descriptores de archivo para PID $pid:"
            ls -la "/proc/$pid/fd/" 2>/dev/null | grep pipe || echo "No se detectaron descriptores de pipe abiertos"
        done
    else
        echo "stream_processor.py no se encuentra en ejecución"
    fi
    echo ""

    echo "[6. Entradas de adquisición en mqtt_coordinator.log]"
    if [ -f "$LOG_DIR/mqtt_coordinator.log" ]; then
        grep -i -E "ACQUISITION|STALE|PIPE_RECONNECT|PIPE_RECONNECTED" "$LOG_DIR/mqtt_coordinator.log" 2>/dev/null | tail -20 || echo "Sin entradas de adquisición recientes"
    else
        echo "mqtt_coordinator.log no encontrado"
    fi
    echo ""
}

# Función: Diagnóstico de Sensor
diagnostico_sensor() {
    echo "--- SECCIÓN: DIAGNÓSTICO SENSOR ---"
    echo "[1. Ejecución directa del wrapper comprobar_registro_wrapper.py]"
    WRAPPER_PATH="$PROJECT_LOCAL_ROOT/scripts/acelerografo/comprobar_registro_wrapper.py"
    if [ ! -f "$WRAPPER_PATH" ]; then
        if [ -f "$PROJECT_LOCAL_ROOT/scripts/operation/acelerografo/comprobar_registro_wrapper.py" ]; then
            WRAPPER_PATH="$PROJECT_LOCAL_ROOT/scripts/operation/acelerografo/comprobar_registro_wrapper.py"
        fi
    fi

    if [ -f "$WRAPPER_PATH" ]; then
        if [ -x "$VENV_PYTHON" ]; then
            "$VENV_PYTHON" "$WRAPPER_PATH" 2>&1
        elif command -v python3 >/dev/null 2>&1; then
            python3 "$WRAPPER_PATH" 2>&1
        else
            echo "Error: Intérprete Python no encontrado ($VENV_PYTHON)"
        fi
    else
        echo "Error: Wrapper no encontrado en $WRAPPER_PATH"
    fi
    echo ""

    echo "[2. Detalle de archivo del wrapper]"
    ls -la "$WRAPPER_PATH" 2>&1
    echo ""

    echo "[3. Entradas de sensor en mqtt_coordinator.log]"
    if [ -f "$LOG_DIR/mqtt_coordinator.log" ]; then
        grep -i -E "SENSOR|ANOMALY|clock|wrapper" "$LOG_DIR/mqtt_coordinator.log" 2>/dev/null | tail -20 || echo "Sin entradas de sensor recientes"
    else
        echo "mqtt_coordinator.log no encontrado"
    fi
    echo ""

    echo "[4. Estado del servicio de adquisición (rsa-acelerografo)]"
    if command -v systemctl >/dev/null 2>&1; then
        sudo systemctl is-active rsa-acelerografo.service 2>&1
    else
        echo "systemctl no disponible"
    fi
    echo ""
}

# Función: Diagnóstico de Drive y Almacenamiento
diagnostico_drive() {
    echo "--- SECCIÓN: DIAGNÓSTICO DRIVE ---"
    echo "[1. Registro de subidas a Google Drive]"
    if [ -f "$LOG_DIR/uploaded_files_registry.json" ]; then
        cat "$LOG_DIR/uploaded_files_registry.json"
        echo ""
    elif [ -f "$LOG_DIR/drive_status.json" ]; then
        cat "$LOG_DIR/drive_status.json"
        echo ""
    else
        echo "No se encontró archivo de registro de subidas (uploaded_files_registry.json ni drive_status.json)"
    fi
    echo ""

    echo "[2. Archivos MiniSEED en cola de subida]"
    if [ -d /home/rsa/data/mseed ]; then
        COUNT_MSEED=$(ls -1 /home/rsa/data/mseed/*.mseed 2>/dev/null | wc -l)
        echo "Cantidad de archivos MiniSEED en disco: $COUNT_MSEED"
        echo "Últimos 10 archivos MiniSEED:"
        ls -lt /home/rsa/data/mseed/*.mseed 2>/dev/null | head -10
    else
        echo "Directorio /home/rsa/data/mseed no existe"
    fi
    echo ""

    echo "[3. Espacio en disco de almacenamiento de datos]"
    df -h /home/rsa/data/ 2>&1 || df -h
    echo ""

    echo "[4. Últimas 30 líneas de gestor_acq.log]"
    if [ -f "$LOG_DIR/gestor_acq.log" ]; then
        tail -n 30 "$LOG_DIR/gestor_acq.log" 2>&1
    else
        echo "Log del gestor no encontrado ($LOG_DIR/gestor_acq.log)"
    fi
    echo ""

    echo "[5. Entradas de Drive en mqtt_coordinator.log]"
    if [ -f "$LOG_DIR/mqtt_coordinator.log" ]; then
        grep -i -E "DRIVE|UPLOAD|SYNC|upload_retry|pending_backlog" "$LOG_DIR/mqtt_coordinator.log" 2>/dev/null | tail -20 || echo "Sin entradas de Drive recientes"
    else
        echo "mqtt_coordinator.log no encontrado"
    fi
    echo ""

    echo "[6. Conectividad con Google APIs]"
    ping -c 2 -W 3 www.googleapis.com 2>&1 || echo "Sin acceso a www.googleapis.com"
    echo ""
}

# Generador del reporte completo
generar_reporte() {
    echo "==================================================================="
    echo "REPORTE DE DIAGNÓSTICO AUTOMATIZADO - ESTACIÓN ACELEROGRÁFICA RSA"
    echo "==================================================================="
    echo "Fecha de generación : $(date --iso-8601=seconds 2>/dev/null || date -Iseconds 2>/dev/null || date)"
    echo "Estación            : $(hostname 2>/dev/null || echo 'desconocida')"
    echo "Canal diagnosticado : $TARGET_CHANNEL"
    echo "==================================================================="
    echo ""

    # Siempre incluir estado general del sistema
    diagnostico_general

    case "$TARGET_CHANNEL" in
        acquisition)
            diagnostico_acquisition
            ;;
        sensor)
            diagnostico_sensor
            ;;
        drive)
            diagnostico_drive
            ;;
        all)
            diagnostico_acquisition
            diagnostico_sensor
            diagnostico_drive
            ;;
    esac

    echo "==================================================================="
    echo "FIN DEL REPORTE"
    echo "==================================================================="
}

# Ejecución y redirección
if [ "$QUIET" = true ]; then
    generar_reporte > "$REPORT_FILE" 2>&1
else
    generar_reporte 2>&1 | tee "$REPORT_FILE"
fi

exit 0

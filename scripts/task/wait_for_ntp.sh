#!/bin/bash
# wait_for_ntp.sh - Espera activa con timeout para sincronización de reloj NTP
# Diseñado para ejecutarse como ExecStartPre en rsa-acelerografo.service

MAX_WAIT=${1:-120}  # Timeout por defecto: 120 segundos
INTERVAL=2
ELAPSED=0

echo "[WAIT_NTP] Verificando sincronización de reloj NTP (timeout: ${MAX_WAIT}s)..."

while [ "$ELAPSED" -lt "$MAX_WAIT" ]; do
    # 1. Comprobar via ntpstat (estándar RSA)
    if command -v ntpstat >/dev/null 2>&1 && ntpstat >/dev/null 2>&1; then
        echo "[WAIT_NTP] Reloj sincronizado con éxito vía ntpstat (${ELAPSED}s transcurridos)."
        exit 0
    fi

    # 2. Comprobar via timedatectl (systemd-timesyncd / fallback)
    if command -v timedatectl >/dev/null 2>&1; then
        if timedatectl status 2>/dev/null | grep -qi "synchronized: yes"; then
            echo "[WAIT_NTP] Reloj sincronizado con éxito vía timedatectl (${ELAPSED}s transcurridos)."
            exit 0
        fi
    fi

    # 3. Comprobar via chronyc (fallback si se usa chrony)
    if command -v chronyc >/dev/null 2>&1; then
        if chronyc tracking 2>/dev/null | grep -qi "Leap status.*Normal"; then
            echo "[WAIT_NTP] Reloj sincronizado con éxito vía chronyc (${ELAPSED}s transcurridos)."
            exit 0
        fi
    fi

    sleep "$INTERVAL"
    ELAPSED=$((ELAPSED + INTERVAL))
done

echo "[WAIT_NTP] ADVERTENCIA: Timeout de ${MAX_WAIT}s alcanzado sin confirmación NTP. Continuando arranque..."
exit 0

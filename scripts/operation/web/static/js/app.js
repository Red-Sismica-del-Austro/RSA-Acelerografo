/**
 * app.js — Lógica del panel de configuración del Acelerógrafo RSA
 *
 * Seguridad:
 * - NUNCA se usa innerHTML para datos provenientes de la API.
 *   Se utiliza exclusivamente textContent y createElement/setAttribute/appendChild.
 * - No se almacenan tokens en localStorage/sessionStorage.
 * - Los logs de consola no exponen datos sensibles.
 * - Validación en cliente duplica la del servidor (no la reemplaza).
 */

"use strict";

// ---------------------------------------------------------------------------
// Estado interno
// ---------------------------------------------------------------------------
let _configActual = null; // Última configuración cargada desde la API

// ---------------------------------------------------------------------------
// Referencias DOM
// ---------------------------------------------------------------------------
const $loadingOverlay = document.getElementById("loading-overlay");
const $configForm     = document.getElementById("config-form");
const $globalAlert    = document.getElementById("global-alert");
const $btnApply       = document.getElementById("btn-apply");
const $btnReset       = document.getElementById("btn-reset");
const $stationChip    = document.getElementById("station-chip");
const $badgeRc        = document.getElementById("badge-rc");
const $badgeMqtt      = document.getElementById("badge-mqtt");
const $confirmModal   = document.getElementById("confirm-modal");
const $modalDiff      = document.getElementById("modal-diff");
const $btnModalCancel = document.getElementById("btn-modal-cancel");
const $btnModalConfirm= document.getElementById("btn-modal-confirm");

// ---------------------------------------------------------------------------
// Mostrar alertas globales
// Usa textContent exclusivamente para evitar XSS.
// ---------------------------------------------------------------------------
function mostrarAlerta(tipo, mensaje, detalles = null) {
    $globalAlert.className = `global-alert ${tipo}`;

    // Limpiar contenido anterior de forma segura
    $globalAlert.replaceChildren();

    const span = document.createElement("span");
    span.textContent = mensaje;
    $globalAlert.appendChild(span);

    if (detalles && Array.isArray(detalles)) {
        const ul = document.createElement("ul");
        ul.style.marginTop = "0.4rem";
        ul.style.paddingLeft = "1.2rem";
        detalles.forEach(d => {
            const li = document.createElement("li");
            li.textContent = d;
            ul.appendChild(li);
        });
        $globalAlert.appendChild(ul);
    }

    $globalAlert.classList.remove("hidden");

    // Auto-ocultar alertas de éxito después de 8 segundos
    if (tipo === "success") {
        setTimeout(() => $globalAlert.classList.add("hidden"), 8000);
    }
}

// ---------------------------------------------------------------------------
// Actualizar badges de estado de servicios
// ---------------------------------------------------------------------------
function actualizarBadge(elemento, estado) {
    elemento.classList.remove("running", "stopped", "unknown");
    if (estado === true || estado === "RUNNING") {
        elemento.classList.add("running");
    } else if (estado === false || estado === "STOPPED" || estado === "FATAL") {
        elemento.classList.add("stopped");
    } else {
        elemento.classList.add("unknown");
    }
}

// ---------------------------------------------------------------------------
// Cargar estado de servicios desde /api/status
// ---------------------------------------------------------------------------
async function cargarEstado() {
    try {
        const resp = await fetch("/api/status", { cache: "no-store" });
        if (!resp.ok) return;
        const data = await resp.json();

        actualizarBadge($badgeRc,   data?.registro_continuo?.running);
        actualizarBadge($badgeMqtt, data?.mqtt_coordinator?.status);
    } catch {
        // Error silencioso: el estado de los badges no es crítico
    }
}

// ---------------------------------------------------------------------------
// Poblar formulario con la configuración cargada
// Solo se usa .value y .textContent (nunca innerHTML con datos externos)
// ---------------------------------------------------------------------------
function poblarFormulario(config) {
    document.getElementById("estacion_id").value         = config.estacion_id        ?? "";
    document.getElementById("nombre").value              = config.nombre              ?? "";
    document.getElementById("latitud").value             = config.coordenadas?.latitud  ?? "";
    document.getElementById("longitud").value            = config.coordenadas?.longitud ?? "";
    document.getElementById("altitud").value             = config.coordenadas?.altitud  ?? "";
    document.getElementById("fuente_reloj").value        = config.adquisicion?.fuente_reloj       ?? "0";
    document.getElementById("modo_adquisicion").value    = config.adquisicion?.modo_adquisicion    ?? "offline";
    document.getElementById("deteccion_eventos").value   = config.adquisicion?.deteccion_eventos   ?? "no";
    document.getElementById("publicar_eventos").value    = config.adquisicion?.publicar_eventos    ?? "no";
    document.getElementById("drive_continuos_id").value  = config.drive_folder_ids?.continuos_id   ?? "";
    document.getElementById("drive_mseed_id").value      = config.drive_folder_ids?.mseed_id       ?? "";
    document.getElementById("drive_events_id").value     = config.drive_folder_ids?.events_id      ?? "";
    document.getElementById("drive_tmp_id").value        = config.drive_folder_ids?.tmp_id         ?? "";
    document.getElementById("drive_logs_id").value       = config.drive_folder_ids?.logs_id        ?? "";

    // Actualizar el chip de estación en el header (solo textContent)
    $stationChip.textContent = config.estacion_id ?? "—";
}

// ---------------------------------------------------------------------------
// Recoger valores del formulario y construir el payload
// ---------------------------------------------------------------------------
function recogerPayload() {
    return {
        estacion_id: document.getElementById("estacion_id").value.trim().toUpperCase(),
        nombre:      document.getElementById("nombre").value.trim(),
        coordenadas: {
            latitud:  parseFloat(document.getElementById("latitud").value),
            longitud: parseFloat(document.getElementById("longitud").value),
            altitud:  parseFloat(document.getElementById("altitud").value),
        },
        adquisicion: {
            fuente_reloj:       document.getElementById("fuente_reloj").value,
            modo_adquisicion:   document.getElementById("modo_adquisicion").value,
            deteccion_eventos:  document.getElementById("deteccion_eventos").value,
            publicar_eventos:   document.getElementById("publicar_eventos").value,
        },
        drive_folder_ids: {
            continuos_id: document.getElementById("drive_continuos_id").value.trim(),
            mseed_id:     document.getElementById("drive_mseed_id").value.trim(),
            events_id:    document.getElementById("drive_events_id").value.trim(),
            tmp_id:       document.getElementById("drive_tmp_id").value.trim(),
            logs_id:      document.getElementById("drive_logs_id").value.trim(),
        },
    };
}

// ---------------------------------------------------------------------------
// Validaciones del lado del cliente (espejo de las del backend)
// ---------------------------------------------------------------------------
const _ESTACION_RE = /^[A-Z]{3}\d$/;

function validarPayload(p) {
    const errores = [];

    if (!_ESTACION_RE.test(p.estacion_id)) {
        errores.push("Código de estación inválido. Debe ser 3 letras mayúsculas + 1 dígito (ej: NOM0).");
        marcarCampoError("estacion_id", "Formato incorrecto");
    } else {
        limpiarCampoError("estacion_id");
    }

    if (!p.nombre) {
        errores.push("El nombre completo es obligatorio.");
        marcarCampoError("nombre", "Obligatorio");
    } else if (p.nombre !== p.nombre.toUpperCase()) {
        errores.push("El nombre completo debe estar todo en mayúsculas.");
        marcarCampoError("nombre", "Debe estar en mayúsculas");
    } else { limpiarCampoError("nombre"); }

    if (isNaN(p.coordenadas.latitud) || p.coordenadas.latitud < -90 || p.coordenadas.latitud > 90) {
        errores.push("Latitud debe estar entre -90 y 90.");
        marcarCampoError("latitud", "Fuera de rango");
    } else { limpiarCampoError("latitud"); }

    if (isNaN(p.coordenadas.longitud) || p.coordenadas.longitud < -180 || p.coordenadas.longitud > 180) {
        errores.push("Longitud debe estar entre -180 y 180.");
        marcarCampoError("longitud", "Fuera de rango");
    } else { limpiarCampoError("longitud"); }

    if (isNaN(p.coordenadas.altitud) || p.coordenadas.altitud < 0) {
        errores.push("Altitud debe ser un número >= 0.");
        marcarCampoError("altitud", "Valor inválido");
    } else { limpiarCampoError("altitud"); }

    return errores;
}

function marcarCampoError(id, msg) {
    const group = document.getElementById(id)?.closest(".field-group");
    if (!group) return;
    group.classList.add("has-error");
    let errEl = group.querySelector(".field-error");
    if (!errEl) {
        errEl = document.createElement("span");
        errEl.className = "field-error";
        group.appendChild(errEl);
    }
    errEl.textContent = msg; // Solo textContent, nunca innerHTML
}

function limpiarCampoError(id) {
    const group = document.getElementById(id)?.closest(".field-group");
    if (!group) return;
    group.classList.remove("has-error");
    group.querySelector(".field-error")?.remove();
}

// ---------------------------------------------------------------------------
// Mostrar resumen de cambios en el modal de confirmación
// Usa solo métodos seguros del DOM.
// ---------------------------------------------------------------------------
function mostrarDiffEnModal(actual, nuevo) {
    $modalDiff.replaceChildren();

    if (!actual) {
        const p = document.createElement("p");
        p.textContent = "Configuración inicial (sin datos anteriores para comparar).";
        $modalDiff.appendChild(p);
        return;
    }

    const cambios = [];

    if (actual.estacion_id !== nuevo.estacion_id)
        cambios.push(`Código estación: ${actual.estacion_id} → ${nuevo.estacion_id}`);
    if (actual.nombre !== nuevo.nombre)
        cambios.push(`Nombre: ${actual.nombre} → ${nuevo.nombre}`);
    if (actual.coordenadas?.latitud !== nuevo.coordenadas?.latitud)
        cambios.push(`Latitud: ${actual.coordenadas?.latitud} → ${nuevo.coordenadas?.latitud}`);
    if (actual.coordenadas?.longitud !== nuevo.coordenadas?.longitud)
        cambios.push(`Longitud: ${actual.coordenadas?.longitud} → ${nuevo.coordenadas?.longitud}`);
    if (actual.coordenadas?.altitud !== nuevo.coordenadas?.altitud)
        cambios.push(`Altitud: ${actual.coordenadas?.altitud} → ${nuevo.coordenadas?.altitud}`);
    if (actual.adquisicion?.modo_adquisicion !== nuevo.adquisicion?.modo_adquisicion)
        cambios.push(`Modo: ${actual.adquisicion?.modo_adquisicion} → ${nuevo.adquisicion?.modo_adquisicion}`);

    if (cambios.length === 0) {
        const p = document.createElement("p");
        p.textContent = "No se detectan cambios en los campos principales.";
        $modalDiff.appendChild(p);
        return;
    }

    cambios.forEach(c => {
        const line = document.createElement("p");
        line.textContent = "• " + c; // Solo textContent
        $modalDiff.appendChild(line);
    });
}

// ---------------------------------------------------------------------------
// Enviar configuración al servidor
// ---------------------------------------------------------------------------
async function enviarConfiguracion(payload) {
    $btnApply.disabled = true;
    $btnApply.classList.add("loading");
    $btnApply.textContent = "Aplicando...";

    try {
        const resp = await fetch("/api/config", {
            method:  "POST",
            headers: { "Content-Type": "application/json" },
            body:    JSON.stringify(payload),
        });

        const data = await resp.json().catch(() => ({}));

        if (resp.ok) {
            _configActual = payload;
            $stationChip.textContent = payload.estacion_id;

            let msg = data.message ?? "Configuración aplicada.";
            mostrarAlerta("success", msg,
                data.advertencias?.length ? data.advertencias : null
            );
            // Recargar estado de servicios
            setTimeout(cargarEstado, 2000);
        } else {
            const detalles = data.detalles ?? (data.detalle ? [data.detalle] : null);
            mostrarAlerta("error", data.error ?? "Error al aplicar la configuración.", detalles);
        }
    } catch (err) {
        console.error("Error de red al enviar configuración."); // Sin datos sensibles
        mostrarAlerta("error", "No se pudo conectar con el servidor. Comprueba la conexión.");
    } finally {
        $btnApply.disabled = false;
        $btnApply.classList.remove("loading");
        $btnApply.textContent = "Aplicar Configuración";
    }
}

// ---------------------------------------------------------------------------
// Inicialización: carga configuración actual
// ---------------------------------------------------------------------------
async function inicializar() {
    try {
        const resp = await fetch("/api/config", { cache: "no-store" });
        if (!resp.ok) throw new Error("HTTP " + resp.status);

        _configActual = await resp.json();
        poblarFormulario(_configActual);
    } catch {
        mostrarAlerta("error", "No se pudo cargar la configuración desde el servidor.");
    } finally {
        $loadingOverlay.classList.add("hidden");
        $configForm.classList.remove("hidden");
    }

    await cargarEstado();
}

// Actualizar badges de estado cada 30 segundos
setInterval(cargarEstado, 30_000);

// ---------------------------------------------------------------------------
// Manejadores de eventos
// ---------------------------------------------------------------------------

// Envío del formulario → validar → mostrar modal de confirmación
$configForm.addEventListener("submit", (e) => {
    e.preventDefault();
    $globalAlert.classList.add("hidden");

    const payload = recogerPayload();
    const errores = validarPayload(payload);

    if (errores.length > 0) {
        mostrarAlerta("error", "Corrija los errores antes de aplicar:", errores);
        return;
    }

    mostrarDiffEnModal(_configActual, payload);
    $confirmModal.classList.remove("hidden");
});

// Cancelar modal
$btnModalCancel.addEventListener("click", () => {
    $confirmModal.classList.add("hidden");
});

// Confirmar en modal → enviar
$btnModalConfirm.addEventListener("click", async () => {
    $confirmModal.classList.add("hidden");
    const payload = recogerPayload();
    await enviarConfiguracion(payload);
});

// Cerrar modal con Escape
document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && !$confirmModal.classList.contains("hidden")) {
        $confirmModal.classList.add("hidden");
    }
});

// Descartar cambios: volver a la configuración original
$btnReset.addEventListener("click", () => {
    if (_configActual) {
        poblarFormulario(_configActual);
        $globalAlert.classList.add("hidden");
        // Limpiar errores de validación
        document.querySelectorAll(".field-group.has-error").forEach(g => {
            g.classList.remove("has-error");
            g.querySelector(".field-error")?.remove();
        });
    }
});

// Auto-capitalizar estacion_id en tiempo real
document.getElementById("estacion_id").addEventListener("input", function () {
    const pos = this.selectionStart;
    this.value = this.value.toUpperCase();
    this.setSelectionRange(pos, pos);
});

// Auto-capitalizar nombre en tiempo real
document.getElementById("nombre").addEventListener("input", function () {
    const pos = this.selectionStart;
    this.value = this.value.toUpperCase();
    this.setSelectionRange(pos, pos);
});

// ---------------------------------------------------------------------------
// Arranque
// ---------------------------------------------------------------------------
document.addEventListener("DOMContentLoaded", inicializar);

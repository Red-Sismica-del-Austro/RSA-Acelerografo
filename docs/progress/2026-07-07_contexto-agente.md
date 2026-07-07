# Resumen de Sesión: Implementación Completa — Fase 4 Pipeline GPD (Extracción Automática + Registro CSV)

**Fecha**: 2026-07-07  
**Repositorio**: `acelerografo-DEV00`  
**Agente de IA**: Antigravity (Google DeepMind)  
**Usuario**: Milton

---

## 🎯 Objetivo de la Sesión

Implementar la Fase 4 del pipeline de inferencia GPD en tiempo real, conectando la detección de fases sísmicas (ya operativa en la Fase 3) con la extracción automática de eventos y su registro persistente en CSV mensual. La implementación sigue las directrices del blueprint `2026-07-06_arquitectura_flujo_gpd_online_offline.md`, que introduce la bifurcación por modo de adquisición (online/offline) como nuevo eje de diseño respecto al plan original de junio.

---

## 📂 Estructura del Repositorio Implementada

Archivos **creados** y **modificados** durante la sesión:

```text
montajes/acelerografo-DEV00/
│
├── docs/
│   ├── blueprints/
│   │   └── 2026-07-06_plan_implementacion_fase4_gpd.md   [NUEVO] Plan de implementación
│   └── progress/
│       └── 2026-07-07_contexto-agente.md                 [NUEVO] Este archivo
│
├── scripts/operation/
│   ├── core/
│   │   ├── event_logger.py        [NUEVO]  Módulo de registro CSV thread-safe
│   │   └── test_event_logger.py   [NUEVO]  Suite de 11 tests unitarios
│   │
│   ├── streaming/
│   │   └── gpd_stream_worker.py   [MODIFICADO] Modo online/offline + CSV + extracción offline
│   │
│   ├── mqtt/
│   │   └── mqtt_coordinator.py    [MODIFICADO] Handler GPD local + actualización CSV
│   │
│   └── structured_logger.py       [MODIFICADO] 7 métodos GPD nuevos
│
└── configuration/
    └── configuracion_mqtt.json.template  [MODIFICADO] events_local en subscriptions
```

---

## ⚙️ Configuración del Entorno Virtual

No se crearon ni modificaron entornos virtuales en esta sesión. El módulo `core/event_logger.py` fue implementado con **stdlib únicamente** (`csv`, `os`, `threading`, `shutil`, `tempfile`, `datetime`) para no introducir dependencias nuevas.

---

## 🛠️ Modificaciones de Código y Refactorización

### Paso 1 — `core/event_logger.py` (nuevo)

Módulo thread-safe para registro CSV de detecciones GPD. Columnas del CSV mensual:

| Campo | Tipo | Descripción |
|---|---|---|
| `timestamp_centro` | str (ISO8601) | Centro de la ventana evaluada |
| `fase` | str | `"P"`, `"S"`, `"EXTERNAL"`, `"N/A"` |
| `probabilidad` | float | Probabilidad del modelo [0.0–1.0] |
| `timestamp_local` | str (ISO8601) | Momento de escritura en el sistema |
| `confirmado` | bool | True si fue extraído y validado |
| `archivo_mseed` | str | Nombre del archivo MiniSEED generado |
| `metodo` | str | `"local_gpd"` o `"network_cmd"` |

**Decisiones de diseño clave:**

- `actualizar_confirmacion()` usa **reescritura atómica** (`tempfile.mkstemp` + `shutil.move`) para evitar corrupción de datos ante fallos de proceso durante la escritura.
- `_csv_path_from_iso()` degrada graciosamente: si el timestamp es malformado, usa el mes UTC actual en lugar de lanzar excepción.
- `registrar_evento_externo()` es un wrapper semántico sobre `registrar_deteccion()` con `fase="EXTERNAL"`, `prob=0.0`, `confirmado=True`, `metodo="network_cmd"`.

**Tests unitarios** (`test_event_logger.py`, 11 tests):

| Test | Criterio |
|---|---|
| `test_crear_csv_nuevo` | CSV creado con headers correctos al primer registro |
| `test_registrar_deteccion` | Todos los campos escritos correctamente |
| `test_registrar_multiples` | Acumulación sin sobrescritura |
| `test_actualizar_confirmacion` | `confirmado` y `archivo_mseed` actualizados |
| `test_actualizar_solo_primera_ocurrencia` | Solo el primer match es modificado |
| `test_actualizar_no_encontrado` | Retorna `False` sin crash |
| `test_actualizar_csv_no_existe` | Retorna `False` sin crash |
| `test_registrar_evento_externo` | Campos canónicos `EXTERNAL` / `network_cmd` |
| `test_concurrencia` | 10 hilos simultáneos → CSV íntegro |
| `test_rotacion_mensual` | Meses distintos → archivos separados |
| `test_timestamp_iso_invalido` | No lanza excepción, usa mes actual |
| `test_directorio_se_crea_automaticamente` | `csv_dir` creado si no existe |
| `test_probabilidad_se_redondea` | Almacena 4 decimales |

---

### Paso 2 — `streaming/gpd_stream_worker.py` (modificado)

**Nuevas importaciones:**
- `import threading`, `timedelta` (stdlib)
- `from core.event_logger import EventLogger`
- Importación condicional de `extraer_y_subir_evento` (try/except → `_EXTRACTOR_AVAILABLE`)

**Nuevos atributos en `__init__`:**
- `self._modo_adquisicion` — leído desde `config["modo_adquisicion"]` (default: `"online"`)
- `self._event_logger` — instancia de `EventLogger`

**Método `_publicar_deteccion()` refactorizado:**
Ahora bifurca por modo. Siempre registra en CSV con `confirmado=False`, luego:
- **Online** → `_publicar_mqtt(deteccion)` (comportamiento anterior, extraído a método propio)
- **Offline** → `_lanzar_extraccion_offline(deteccion)` (nuevo hilo daemon)

**Nuevos métodos:**
- `_publicar_mqtt()` — lógica MQTT extraída (sin cambio de comportamiento)
- `_lanzar_extraccion_offline()` — calcula ventana pre/post, parsea timestamp, lanza hilo
- `_run_extraccion_offline()` — invoca `extraer_y_subir_evento(upload=False)` y actualiza CSV

**En `main()`:**
```python
gpd_config["modo_adquisicion"] = full_config.get("dispositivo", {}).get("modo_adquisicion", "online")
```

---

### Paso 3 — `mqtt/mqtt_coordinator.py` (modificado)

**Nuevas importaciones:**
- `timedelta` en `from datetime import ...`
- `from core.event_logger import EventLogger`

**`CommandDispatcher.__init__`:**
Nuevo parámetro `event_logger=None` → `self.event_logger`.

**`_run_extraction_pipeline()` (comandos de red):**
Tras extracción exitosa, intenta `actualizar_confirmacion(timestamp_centro=start)`. Si retorna `False` → `registrar_evento_externo(start, archivo)`. Esto registra en el CSV todos los eventos disparados por comandos externos.

**Nuevas funciones de módulo:**

- `_manejar_deteccion_gpd_local(client, userdata, payload)`:
  Valida payload → verifica `modo_adquisicion == "online"` → verifica `auto_extract` → calcula ventana → publica ACK → lanza hilo.

- `_run_gpd_extraction_pipeline(...)`:
  Hilo: extrae → publica resultado con `source: "gpd_auto"` → `actualizar_confirmacion()`. Si no hay match: `registrar_deteccion(confirmado=True)` (fallback para condición de carrera).

**`on_message()` — nueva rama:**
```python
elif "/events/detected" in topic and config["id"] in topic:
    _manejar_deteccion_gpd_local(client, userdata, payload)
```

**`iniciar_cliente()`:**
Pasa `event_logger` desde `userdata` al constructor de `CommandDispatcher`.

**`main()`:**
- Carga `configuracion_dispositivo.json` (para parámetros GPD y `modo_adquisicion`).
- Crea `EventLogger` antes de `userdata`.
- Agrega `device_config` y `event_logger` al dict `userdata`.

---

### Paso 4 — `structured_logger.py` (modificado)

7 nuevos métodos al final de la clase `StructuredLogger`:

```python
gpd_load(model_path, load_time_s)       # SUMMARY — modelo cargado
gpd_inference(prob_noise, prob_p, prob_s) # DEBUG — resultado por ventana
gpd_detection(phase_type, probability, timestamp) # SUMMARY — fase detectada
gpd_cooldown(remaining_s)               # DEBUG — descartado por cooldown
gpd_error(operation, error)             # SUMMARY — error en pipeline
gpd_csv_write(csv_file, timestamp_centro) # INFO — escritura en CSV
gpd_csv_update(csv_file, timestamp_centro, confirmado) # INFO — actualización CSV
```

---

### Paso 5 — `configuracion_mqtt.json.template` (modificado)

```diff
 "subscriptions": [
     "events_regional",
     "cmd_execute",
     "cmd_broadcast",
-    "config_set"
+    "config_set",
+    "events_local"
 ],
```

El coordinador MQTT ahora se suscribe explícitamente al tópico propio (`{id}/events/detected`), lo que activa la rama GPD en `on_message()`.

---

## 📋 Pasos Sugeridos para el Siguiente Agente

> **Contexto**: La Fase 4 está **completamente implementada** a nivel de código. Los siguientes pasos son de validación, integración y cierre del ciclo de la Fase 4.

1. **Ejecutar la suite de tests de `event_logger.py`** en el dispositivo o entorno con Python 3.x:
   ```bash
   cd /home/rsa/projects/acelerografo-rsa
   .venv/bin/python3 -m pytest scripts/operation/core/test_event_logger.py -v
   ```
   Todos los 13 tests deben pasar en verde antes de proceder.

2. **Verificar que `configuracion_dispositivo.json`** en el dispositivo remoto tiene el campo `modo_adquisicion` en la sección `dispositivo`:
   ```json
   "dispositivo": {
       "id": "DEV00",
       "modo_adquisicion": "online",
       ...
   }
   ```
   Si falta el campo, el sistema usará `"online"` por defecto (comportamiento seguro).

3. **Regenerar `configuracion_mqtt.json`** desde el template actualizado en el dispositivo remoto, o añadir manualmente `"events_local"` a la lista `subscriptions` del JSON activo.

4. **Prueba de integración manual** (con broker MQTT activo):
   - Iniciar `mqtt_coordinator.py` y verificar en los logs que se suscribe a `{id}/events/detected`.
   - Iniciar `gpd_stream_worker.py` en modo simulación (si existe) o con señal real.
   - Verificar que al producirse una detección GPD:
     - Se crea el CSV en `/home/rsa/data/eventos-detectados/YYYY-MM_detecciones.csv`.
     - El CSV contiene la fila con `confirmado=False`.
     - El coordinador recibe la detección y lanza la extracción.
     - El CSV se actualiza a `confirmado=True` con el nombre del archivo.

5. **Validar modo offline** cambiando `modo_adquisicion` a `"offline"` en `configuracion_dispositivo.json`:
   - El worker debe extraer directamente (sin publicar MQTT).
   - El coordinador debe loguear `[GPD_LOCAL] Modo offline` y no lanzar extracción.
   - El CSV debe actualizarse directamente desde el worker.

6. **Actualizar el `indice_tematico.md`** en `RSA-Metodologias` para registrar la Fase 4 como completada.

7. **Ejecutar volcado de bitácora** al finalizar la validación: `"ejecuta el volcado de bitácora"`.

---

## 📌 Notas Técnicas para el Siguiente Agente

- **Restricción SSHFS**: `montajes/acelerografo-DEV00` está montado remotamente. No ejecutar comandos de forma autónoma en esa ruta; presentar los comandos al usuario.
- **Flujo del pipeline Fase 4 (modo online)**:
  ```
  gpd_stream_worker detecta → registra CSV (confirmado=False) → publica MQTT
  → mqtt_coordinator recibe → lanza extracción en hilo → actualiza CSV (confirmado=True)
  ```
- **Flujo del pipeline Fase 4 (modo offline)**:
  ```
  gpd_stream_worker detecta → registra CSV (confirmado=False) → lanza extracción local
  → actualiza CSV (confirmado=True) [sin MQTT]
  ```
- **Ruta del CSV**: `/home/rsa/data/eventos-detectados/YYYY-MM_detecciones.csv` (en el dispositivo remoto).
- **`_EXTRACTOR_AVAILABLE`**: Si `mqtt.event_extractor` no está en el path al importar `gpd_stream_worker`, el modo offline degrada graciosamente con un warning, sin crash.
- **Commits pendientes** (formato institucional, en minúsculas):
  ```
  feat: agregar modulo event_logger para registro csv mensual de detecciones gpd y sus tests unitarios
  feat: integrar modo online/offline y registro csv en gpd_stream_worker
  feat: integrar handler de deteccion gpd local y actualizacion csv en mqtt_coordinator
  feat: agregar metodos gpd a structured_logger y suscripcion events_local a mqtt template
  ```

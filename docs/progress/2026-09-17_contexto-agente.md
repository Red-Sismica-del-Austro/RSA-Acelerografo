# Resumen de Sesión: Optimización del Registro de Sincronización de Google Drive y Síntesis de Diagnóstico

**Fecha**: 2026-09-17  
**Repositorio**: `acelerografo-DEV00`  
**Agente de IA**: Antigravity  
**Usuario**: Milton Muñoz  

---

## 🎯 Objetivo de la Sesión

Resolver de raíz el crecimiento desmedido e infinito del archivo de registro de Google Drive (`uploaded_files_registry.json`) y la saturación por inundación de terminal en la herramienta CLI `diagnostico.sh`. Establecer formalmente el principio de "Registro Espejo" (donde el registro JSON representa exclusivamente el inventario de subida de los archivos físicamente presentes en disco local para deduplicación activa), automatizar la poda periódica tras las políticas de retención, habilitar herramientas de saneamiento manual (`--purge-registry`), transformar el diagnóstico de Drive en un reporte ejecutivo sintetizado y consolidar la documentación técnica y arquitectónica federada (ADR-021).

---

## 📂 Estructura del Repositorio Implementada

```text
montajes/acelerografo-DEV00/
├── docs/
│   ├── adr/
│   │   └── 021_sincronizacion_espejo_registro_drive_y_sintesis_diagnostico.md # [NUEVO] ADR formalizando el principio de Registro Espejo
│   ├── blueprints/
│   │   └── 2026-09-17_plan_optimizacion_registro_drive_diagnostico.md         # [NUEVO] Blueprint de 4 fases de optimización y diagnóstico
│   ├── context/
│   │   ├── ayuda_context.md                                                   # [MODIFICADO] Actualización con banderas --purge-registry y --raw
│   │   ├── diagnostico_context.md                                             # [MODIFICADO] Salida ejecutiva de 25 líneas y bandera --raw
│   │   ├── drive_status_manager_context.md                                    # [NUEVO] Contexto técnico, arquitectura y suite de tests
│   │   └── gestor_archivos_acq_context.md                                     # [MODIFICADO] Diagrama de ciclo de retención con poda integrada
│   └── progress/
│       ├── 2026-09-15_contexto-agente.md
│       └── 2026-09-17_contexto-agente.md                                      # [NUEVO] Este documento de transición técnica
└── scripts/
    ├── operation/
    │   └── drive/
    │       ├── drive_status_manager.py                                        # [MODIFICADO] Validación os.path.isdir, métricas y resumen diagnóstico
    │       ├── gestor_archivos_acq.py                                         # [MODIFICADO] Poda periódica, flag --purge-registry y desglose CLI
    │       └── test_drive_status_manager.py                                   # [NUEVO] Suite de 7 pruebas unitarias independientes
    └── task/
        ├── ayuda.sh                                                           # [MODIFICADO] Documentación de opciones --raw y --purge-registry
        └── diagnostico.sh                                                     # [MODIFICADO] Resumen sintético vía Python y soporte flag --raw
```

*(En el repositorio institucional federado `rsa/RSA-Metodologias/` se incorporó `decisiones/021_sincronizacion_espejo_registro_drive_y_sintesis_diagnostico.md`, actualizando su índice general `decisiones/index.md` y el índice maestro `indice/indice_tematico.md`).*

---

## ⚙️ Configuración del Entorno Virtual (`.venv`)

El entorno operativo reside en la Raspberry Pi 3B+ bajo:
`/home/rsa/projects/acelerografo/.venv/` (Python 3.9+).

* **Cero Dependencias Externas Nuevas**:
  - Tanto `drive_status_manager.py`, `gestor_archivos_acq.py` como `test_drive_status_manager.py` utilizan exclusivamente la biblioteca estándar de Python (`os`, `json`, `time`, `datetime`, `argparse`, `unittest`, `tempfile`, `fcntl`).
  - `diagnostico.sh` invoca `$VENV_PYTHON` (`$PROJECT_LOCAL_ROOT/.venv/bin/python3`) de forma embebida para ejecutar de manera aislada y atómica `drive_status_manager.obtener_resumen_diagnostico()`, con fallback nativo en Bash (`head -n 25`) en caso de anomalía.

---

## 🛠️ Modificaciones de Código y Refactorización

### 1. Robustecimiento de `drive_status_manager.py` y Suite de Tests (Fase 1)
* **Validación de Directorios**: Se implementó una verificación preventiva con `os.path.isdir(directorio)` en `limpiar_archivos_inexistentes()`. Si un directorio no existe o está desmontado, se omite su poda para prevenir que una desconexión transitoria vacíe el registro erróneamente.
* **Métricas Detalladas**: La función de limpieza ahora retorna un diccionario granular con el balance de entradas podadas (`exitosos_removidos`, `fallidos_removidos` y desglose por tipo `mseed`, `continuous`, `event`).
* **Resumen Diagnóstico**: Se implementó `obtener_resumen_diagnostico(log_directory, max_ultimos=5)` que extrae métricas de balance, conteo total de claves indexadas, presencia física en disco y últimos archivos procesados.
* **Suite de Pruebas Unitarias**: Se creó `scripts/operation/drive/test_drive_status_manager.py` con 7 casos de prueba cubriendo creación/actualización de JSON, poda selectiva de archivos inexistentes, protección ante directorios inválidos y consistencia de reportes sintéticos. Validado en producción con resultado `OK (7/7)`.

### 2. Integración de Poda Periódica en `gestor_archivos_acq.py` (Fase 2)
* **Ciclo de Vida Unificado**: Al término de las rutinas de retención temporal y espacio en disco, `gestor_archivos_acq.py` invoca automáticamente `limpiar_archivos_inexistentes()`, eliminando de inmediato las claves de archivos físicos borrados.
* **Soporte `--dry-run`**: La poda respeta la bandera de simulación, calculando las claves candidatas a ser purgadas sin modificar el archivo JSON en disco, reportando el balance a nivel `SUMMARY`.
* **Regresión Verificada**: Se ejecutó la suite `test_drive_watchdog.py` confirmando total compatibilidad (8/8 tests superados).

### 3. Síntesis de Reporte en `diagnostico.sh` (Fase 3)
* **Fin de la Inundación de Terminal**: Se eliminó el `cat` masivo de `uploaded_files_registry.json` (que generaba miles de líneas). En su lugar, se invoca `drive_status_manager.obtener_resumen_diagnostico()` vía Python embebido, produciendo un resumen ejecutivo limpio de ~25 líneas.
* **Bandera `--raw`**: Se añadió soporte para `diagnostico drive --raw` y `diagnostico all --raw` (o `-r`), permitiendo al operador volcar el JSON sin formato si necesita una auditoría cruda.
* **Actualización en `ayuda.sh`**: Se documentó la opción `--raw` en el menú interactivo CLI. Validado en producción con el reporte integral de `diagnostico` reducido a 170 líneas legibles.

### 4. Parámetro `--purge-registry` bajo Demanda (Fase 4 - Puntos 1 y 2)
* **Saneamiento Explícito**: Se agregó el argumento CLI `--purge-registry` a `gestor_archivos_acq.py` para permitir al operador purgar el registro en cualquier momento sin esperar al ciclo de retención.
* **Inventario Desglosado**: Reporta en consola el total de archivos indexados, la cantidad de archivos físicos presentes en disco por tipo, y el balance de claves huérfanas podadas.
* **Compatibilidad Combinada**: Permite `gestor_archivos_acq.py --purge-registry --dry-run` para previsualizar el impacto sin alterar el archivo JSON.
* **Prueba en Estación DEV00**: Ejecutado en vivo. Se constató que los 2.903 archivos registrados (407 mseed + 2.496 event) residen físicamente en `/home/rsa/data/`, reportando exactamente 0 huérfanos y confirmando el comportamiento correcto del software.

### 5. Documentación y Arquitectura (Fase 4 - Punto 3)
* **ADR-021**: Formalizado en `docs/adr/021_sincronizacion_espejo_registro_drive_y_sintesis_diagnostico.md` y replicado en `rsa/RSA-Metodologias/decisiones/`.
* **Contextos Técnicos**: Actualizados según `generar_contexto.md` (`gestor_archivos_acq_context.md`, `diagnostico_context.md`, `ayuda_context.md`) y creado `drive_status_manager_context.md`.
* **Índice Federado**: Actualizado `rsa/RSA-Metodologias/indice/indice_tematico.md` con enlaces directos a los nuevos componentes y decisiones.

---

## 📋 Pasos Sugeridos para el Siguiente Agente

1. **Gestión de Retención para `eventos-extraidos`**:
   - Actualmente `gestor_archivos_acq.py` aplica retención por días a `mseed` (continuo) y `registro-continuo` (binario), pero los archivos generados en `eventos-extraidos/` no tienen una política de retención automática por antigüedad en dicho gestor (acumulando 2.496 archivos en DEV00).
   - Evaluar o diseñar la política de retención para `eventos-extraidos` (por ejemplo, retención de $N$ días o retención post-confirmación de subida) para evitar que el almacenamiento de la microSD crezca indefinidamente con eventos históricos.

2. **Saneamiento Inicial en Estación `TEST`**:
   - Cuando se despliegue esta versión en la estación `TEST` (que acumula >4.700 entradas de meses anteriores cuyos archivos físicos ya no existen):
     - Ejecutar primero: `python3 scripts/operation/drive/gestor_archivos_acq.py --purge-registry --dry-run` para verificar las entradas huérfanas detectadas (~4.000 huérfanos esperados).
     - Ejecutar luego: `python3 scripts/operation/drive/gestor_archivos_acq.py --purge-registry` para realizar la poda definitiva.
     - Comprobar con `diagnostico drive` que el tamaño del registro baje a ~749 archivos activos y 0 huérfanos.

3. **Monitoreo Continuo de Telemetría**:
   - Monitorear los tópicos MQTT de telemetría (`rsa/seismic/smart/DEV00/status/drive`) para verificar que el reporte periódico de `drive_watchdog.py` mantenga métricas consistentes con el registro saneado.

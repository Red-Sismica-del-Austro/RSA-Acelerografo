# Diagnóstico Técnico: Automatización y Saneamiento del Despliegue en Estaciones Acelerográficas

**Fecha**: 2026-09-01  
**Estación / Dispositivo afectado**: ACEL-DEVP-UNIV-01 / DEV00 (Flota Acelerógrafos RSA)  
**Estado**: Diagnosticado / Saneamiento validado / Pendiente de despliegue global  
**Severidad/Prioridad**: Media (Mantenibilidad, seguridad y resiliencia operativa)  

---

## 1. Resumen Ejecutivo
Durante las sesiones de mantenimiento y despliegue de nuevas versiones del software en las estaciones (`ACEL-DEVP-UNIV-01`), se evidenció una acumulación progresiva de ramas locales huérfanas (derivadas de ramas de trabajo tipo `task/gpd`) y una mezcla entre archivos de desarrollo/documentación (`docs/`, `AGENTS.md`) y el código operativo en la rama de producción (`main`). 

Asimismo, el mecanismo actual de actualización depende de intervenciones manuales recurrentes vía SSH ejecutando `menu.sh`. El diagnóstico evaluó los mecanismos para sanear las ramas en las estaciones, segregar el ciclo de vida de la documentación y estructurar un pipeline de actualización remota Over-The-Air (OTA) resiliente y seguro apoyado en la infraestructura MQTT existente.

---

## 2. Evidencia y Análisis de Logs
* **Ruta de los logs y contexto analizado**: `logs.tmp`, historial de Git en estaciones remotas (`~/git/RSA-Acelerografo`).
* **Extractos relevantes**:
  * Presencia de ramas de desarrollo y tareas huérfanas en las estaciones de campo desconectadas del repositorio central (`ahead/behind` con ramas `task/*` ya integradas).
  * En la rama `main`, presencia inicial de artefactos de documentación interna:
    ```text
    rm 'AGENTS.md'
    rm 'docs/CHANGELOG.md'
    rm 'docs/context/binary_to_mseed_context.md'
    ...
    ```
  * Verificación de staging selectivo exitoso desde `develop`:
    ```text
    Changes to be committed:
      deleted:    AGENTS.md
      deleted:    docs/...
      new file:   configuration/...
      new file:   models/gpd.tflite
      new file:   requirements.txt
      new file:   scripts/operation/streaming/...
    ```

---

## 3. Hallazgos y Causa Raíz (Root Cause Analysis)

* **Hallazgo 1: Acumulación de ramas huérfanas de trabajo en estaciones remotas**
  * *Causa*: Los despliegues de prueba se realizaban directamente mediante `git checkout task/...` en las estaciones en lugar de consolidar previamente en ramas maestras.
  * *Condiciones de activación*: Estaciones utilizadas como banco de pruebas interactivo durante el desarrollo del pipeline GPD.

* **Hallazgo 2: Contaminación de `docs/` y `AGENTS.md` en la rama de producción `main`**
  * *Causa*: Fusiones completas (`git merge develop`) sin filtrado de rutas trasladaban documentación técnica y reglas del agente a los dispositivos en campo donde solo se requiere código operativo.
  * *Condiciones de activación*: Falta de una política explícita de release y exclusión de directorios entre `develop` y `main`.

* **Hallazgo 3: Riesgo de interrupción de procesos en actualizaciones remotas (Process Suicide)**
  * *Causa*: Si el coordinador MQTT (`mqtt_coordinator.py`) ejecuta un script de actualización de forma síncrona/hijo directo y este script invoca `supervisorctl restart all`, Supervisor termina al coordinador y mata el subproceso de actualización antes de que finalice la compilación y el despliegue.
  * *Condiciones de activación*: Intentos de automatizar `update.sh` mediante llamadas estándar bloqueantes desde servicios supervisados.

* **Hallazgo 4: Exposición de seguridad en comandos remotos sobre broker MQTT**
  * *Causa*: Un canal de comandos OTA que admita instrucciones de shell libres o carezca de control de acceso permitiría ejecución remota de código no autorizada si el broker está expuesto.
  * *Condiciones de activación*: Ausencia de ACLs en el broker MQTT o uso de payloads sin verificación de tokens.

---

## 4. Mitigaciones / Acciones Aplicadas en la Estación

1. **Saneamiento masivo de ramas locales**:
   Se definió y aplicó el procedimiento de poda y alineación estricta con producción:
   ```bash
   git fetch origin --prune
   git checkout main
   git reset --hard origin/main
   git branch | grep -v "main" | xargs git branch -D 2>/dev/null || true
   ```
2. **Segregación limpia de producción**:
   Se purgó `docs/` y `AGENTS.md` de la rama `main` y se sincronizaron únicamente los componentes de operación (`scripts/`, `models/`, `configuration/`, `main-libraries/`, `menu.sh`, `requirements.txt`).
3. **Validación en Staging**:
   Se confirmó que `main` contiene exclusivamente los archivos necesarios para la ejecución operativa sin dependencias de documentación.

---

## 5. Puntos de Mejora y Recomendaciones para la Flota (Backlog)

1. **[Mejora 1 - Módulo OTA en `mqtt_coordinator.py`]**:
   Implementar un handler de comando en el tópico `rsa/seismic/smart/{station_id}/cmd/update` que lance el proceso de actualización en una sesión desacoplada (`subprocess.Popen(..., start_new_session=True)`).
2. **[Mejora 2 - Validación y Rollback Automático en `update.sh`]**:
   Garantizar que `scripts/setup/update.sh` verifique el éxito de la compilación en C (`registro_continuo_4.5.0.c`) y dependencias Python antes de reiniciar Supervisor. En caso de fallo, aplicar automáticamente `git reset --hard HEAD@{1}` para evitar dejar la estación inoperativa.
3. **[Mejora 3 - Fortalecimiento de Seguridad MQTT]**:
   Configurar Listas de Control de Acceso (ACLs) en el broker Mosquitto: las estaciones solo deben suscribirse a su canal de comandos y publicar en sus canales de datos/telemetría, restringiendo la publicación en canales de comando exclusivamente al servidor central.
4. **[Criterios para aplicación futura]**:
   * Implementar la actualización OTA vía MQTT una vez que la flota supere las 5 estaciones activas en campo para reducir el tiempo de mantenimiento manual por SSH.

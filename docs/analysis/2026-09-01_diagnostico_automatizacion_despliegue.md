---
proyecto: acelerografo
tipo: diagnostico_tecnico
resolucion: pendiente
temas: [despliegue, git, mqtt, supervisor, ota, seguridad]
fecha: 2026-09-01
---

# Diagnóstico Técnico: Automatización y Saneamiento del Despliegue en Estaciones Acelerográficas

**Fecha**: 2026-09-01  
**Proyecto / Repositorio**: `RSA-Acelerografo`  
**Componente(s) afectado(s)**: `scripts/setup/update.sh`, `scripts/operation/mqtt/mqtt_coordinator.py`, `menu.sh`, ciclo de ramas Git (`main` / `develop`)  
**Estado**: Mitigado localmente | Pendiente de despliegue global  
**Severidad**: Media  

---

## 1. Resumen Ejecutivo

Durante los ciclos de mantenimiento y actualización de la flota de estaciones acelerográficas de la Red Sísmica del Austro (RSA), se detectó que el procedimiento de despliegue presentaba dos deficiencias operativas principales:
1. **Desorden de ramas en campo**: La acumulación progresiva de ramas locales huérfanas derivadas de tareas de desarrollo interactivo (`task/gpd`, `task/*`), provocando inconsistencias respecto al repositorio central en GitHub.
2. **Contaminación de la rama de producción**: La presencia de documentación interna técnica (`docs/`), planos y reglas de agentes (`AGENTS.md`) dentro de la rama `main`, la cual debe contener exclusivamente el código y binarios de operación necesarios para las estaciones.

Adicionalmente, el esquema manual de actualización basado en conexiones interactivas SSH (`menu.sh`) genera demoras operativas a medida que la red crece. Se analizó la viabilidad y seguridad de transicionar hacia un esquema de actualización remota Over-The-Air (OTA) apalancado en el broker MQTT institucional y el daemon `mqtt_coordinator.py`, identificando los riesgos críticos de interrupción de procesos por Supervisor (*process suicide*), la necesidad de ejecución desacoplada en nueva sesión y la configuración requerida de Listas de Control de Acceso (ACLs).

---

## 2. Estado Actual

| Componente / Área | Estado Pre-Intervención | Estado Post-Intervención | Observaciones |
|---|---|---|---|
| **Rama `main` (Producción)** | ⚠️ Contaminada con `docs/` y `AGENTS.md` | ✅ Limpia y segregada | Contiene únicamente `configuration/`, `main-libraries/`, `menu.sh`, `models/`, `README.md`, `requirements.txt` y `scripts/`. |
| **Ramas Locales en Estación** | ⚠️ Acumulación de ramas huérfanas `task/*` | ✅ Saneadas | Se ejecutó poda con `git fetch --prune`, alineación con `reset --hard` y borrado masivo de ramas huérfanas. |
| **Pipeline de Actualización** | ⚠️ 100% Manual interactivo vía SSH (`menu.sh`) | ⚠️ Manual estabilizado (OTA diseñado) | Procedimiento manual documentado en `README.md`. Arquitectura OTA vía MQTT analizada y lista para backlog. |
| **Daemon `mqtt_coordinator.py`** | ⬜ Sin soporte de comandos OTA | ⬜ Sin soporte de comandos OTA | Pendiente implementación de handler desacoplado para `.../cmd/update`. |
| **Script `update.sh`** | ⚠️ Sin rollback automático ante fallos | ⚠️ Sin rollback automático | Requiere verificación de retorno de compilación en C antes de reiniciar servicios. |

---

## 3. Evidencia y Análisis

* **Ruta de los recursos analizados**:
  * Registros temporales y staging: `/home/rsa/git/logs.tmp`
  * Repositorio de la estación: `~/git/RSA-Acelerografo` en `ACEL-DEVP-UNIV-01`
  * Guía de comandos del proyecto: `/home/rsa/git/README.md`

* **Extractos relevantes**:

  * **1. Purgado de artefactos no operativos en `main`**:
    ```text
    rsa@ACEL-DEVP-UNIV-01:~/git/RSA-Acelerografo $ git rm -rf docs AGENTS.md
    rm 'AGENTS.md'
    rm 'docs/CHANGELOG.md'
    rm 'docs/context/binary_to_mseed_context.md'
    rm 'docs/context/comprobar_registro_context.md'
    rm 'docs/context/extraer_evento_context.md'
    rm 'docs/context/firmware_context.md'
    rm 'docs/context/gestor_archivos_acq_context.md'
    rm 'docs/context/orquestador_rc_context.md'
    rm 'docs/context/registro_continuo_context.md'
    ```

  * **2. Sincronización selectiva y verificación de staging limpio**:
    ```text
    rsa@ACEL-DEVP-UNIV-01:~/git/RSA-Acelerografo $ git checkout develop -- configuration/ main-libraries/ menu.sh models/ README.md requirements.txt scripts/
    rsa@ACEL-DEVP-UNIV-01:~/git/RSA-Acelerografo $ git status
    On branch main
    Changes to be committed:
      deleted:    AGENTS.md
      deleted:    docs/...
      modified:   README.md
      new file:   configuration/configuracion_dispositivo.json.template
      new file:   configuration/configuracion_maestra.json
      new file:   models/gpd.tflite
      new file:   requirements.txt
      new file:   scripts/operation/streaming/...
      new file:   scripts/setup/update.sh
    ```

* **Cronología del evento**:
  1. Identificación de ramas locales desactualizadas y conflictos al intentar actualizar la estación `ACEL-DEVP-UNIV-01`.
  2. Definición del flujo de separación estricta: `develop` como rama de trabajo integral y `main` como rama de distribución limpia para producción.
  3. Ejecución del procedimiento de limpieza en `main` y validación del árbol de directorios resultante.
  4. Análisis técnico de los riesgos de automatización vía MQTT y diseño de mitigaciones defensivas para la flota.

---

## 4. Hallazgos y Causa Raíz

### Hallazgo 1: Acumulación de ramas huérfanas de trabajo en estaciones remotas
* **Descripción técnica**: Las estaciones mantenían múltiples ramas locales (`task/gpd`, etc.) desconectadas de GitHub, generando confusión sobre cuál era el código activo en ejecución.
* **Causa**: Durante el desarrollo y pruebas en caliente, se creaban ramas directamente en las estaciones sin eliminarlas tras su consolidación en `develop`.
* **Condiciones de activación**: Estaciones utilizadas como banco de pruebas interactivo sin un protocolo formal de limpieza.

### Hallazgo 2: Contaminación de documentación en entornos de producción
* **Descripción técnica**: Carpetas pesadas de documentación interna (`docs/`) y archivos de configuración del agente (`AGENTS.md`) eran clonados en estaciones con almacenamiento limitado.
* **Causa**: Fusiones directas (`git merge develop`) hacia `main` sin filtrado selectivo de directorios.
* **Condiciones de activación**: Ausencia de una estrategia de empaquetado/checkout selectivo para la rama de release.

### Hallazgo 3: Riesgo de "suicidio" de procesos en actualizaciones remotas (*Process Suicide*)
* **Descripción técnica**: Si `mqtt_coordinator.py` ejecuta `update.sh` de forma síncrona o como subproceso hijo estándar, la llamada a `supervisorctl restart all` dentro de `update.sh` termina al propio coordinador, matando inmediatamente el subproceso antes de compilar y reiniciar el sistema.
* **Causa**: Árbol de procesos jerárquico donde el proceso padre es detenido por una orden emitida desde su propio subproceso.
* **Condiciones de activación**: Intentos de lanzar scripts de actualización globales directamente desde servicios gestionados por Supervisor.

### Hallazgo 4: Vulnerabilidad ante ejecución arbitraria de comandos por MQTT
* **Descripción técnica**: Si un atacante o cliente no autorizado publica en el tópico de comandos de la estación, podría desencadenar reinicios o inyectar instrucciones maliciosas si el payload admite texto libre.
* **Causa**: Falta de ACLs restrictivas en el broker MQTT y ausencia de payloads estrictamente tipados.
* **Condiciones de activación**: Broker expuesto en IP pública sin particionamiento de permisos de publicación/suscripción.

---

## 5. Evaluación de Riesgo

| # | Escenario de Riesgo | Probabilidad | Impacto | Mitigación Requerida |
|---|---|---|---|---|
| **R1** | Estación inaccesible (*bricked*) por fallo a mitad de actualización (compilación C rota o dependencias fallidas). | Media | Crítico | Implementar verificación previa de compilación con rollback automático (`git reset --hard HEAD@{1}`) en `update.sh`. |
| **R2** | Actualización truncada por terminación prematura del proceso en Supervisor. | Alta | Alto | Lanzar `update.sh` desacoplado del árbol de procesos (`subprocess.Popen(..., start_new_session=True)`). |
| **R3** | Ejecución no autorizada de comandos por secuestro de tópicos MQTT. | Baja | Crítico | Configurar ACLs en Mosquitto (estaciones solo leen comandos, solo el servidor publica) y validar tokens en payload. |
| **R4** | Deriva de configuración o conflictos Git por modificaciones locales en campo. | Media | Medio | Forzar actualización destructiva controlada en producción con `git reset --hard origin/main`. |

---

## 6. Opciones y Decisiones

### Evaluación de Estrategias para Actualización de la Flota

| Opción | Descripción | Ventajas | Desventajas |
|---|---|---|---|
| **A: Actualización OTA vía MQTT** *(Recomendada)* | Publicación de comando JSON en `rsa/seismic/smart/{id}/cmd/update` procesado por `mqtt_coordinator.py`. | Funciona detrás de NAT/4G, centralizado, no requiere IP pública en estaciones. | Requiere manejo desacoplado de procesos y ACLs estrictas. |
| **B: CI/CD con GitHub Actions + SSH** | GitHub Actions conecta por SSH a cada estación tras cada push a `main`. | Totalmente automático al hacer push. | Requiere que todas las estaciones tengan IP accesible o VPN activa (Tailscale). |
| **C: Polling periódico en estación (Cron)** | Tarea cron periódica verifica commits remotos y ejecuta `update.sh`. | Autónomo y descentralizado. | Retraso en la aplicación de parches y consumo innecesario de red por polling. |
| **D: Despliegue manual SSH masivo (CLI local)** | Script Bash en PC de desarrollo que itera sobre la lista de IPs. | Muy simple de implementar sin tocar daemons. | Requiere conexión directa SSH y ejecución manual estación por estación. |

> **Recomendación**: Implementar la **Opción A (OTA vía MQTT)** como estándar de la RSA, complementada con el protocolo de saneamiento manual para estaciones de desarrollo.

---

## 7. Mitigaciones Aplicadas

1. **Protocolo de Sincronización Selectiva**:
   Se definió y ejecutó el mecanismo de checkout selectivo en `main`:
   ```bash
   git checkout main
   git checkout develop -- configuration/ main-libraries/ menu.sh models/ README.md requirements.txt scripts/
   git commit -m "chore: sincronizar produccion desde develop excluyendo docs y agents"
   git push origin main
   ```
2. **Saneamiento Masivo de Ramas Locales en la Estación**:
   Se purgó el historial local en `ACEL-DEVP-UNIV-01` eliminando ramas huérfanas de trabajo:
   ```bash
   git fetch origin --prune
   git checkout main
   git reset --hard origin/main
   git branch | grep -v "main" | xargs git branch -D 2>/dev/null || true
   ```
3. **Documentación Operativa en `README.md`**:
   Se incorporó la guía de actualización para desarrollo y producción en el repositorio raíz.

---

## 8. Backlog de Mejoras

1. **[Mejora 1 - Handler OTA en `mqtt_coordinator.py`]**:
   Crear el manejador para el tópico `rsa/seismic/smart/{station_id}/cmd/update` con ejecución en sesión independiente (`start_new_session=True`) para evitar la terminación abrupta por Supervisor.
2. **[Mejora 2 - Robustez y Rollback en `update.sh`]**:
   Agregar chequeo de código de retorno (`$?`) tras la compilación de `registro_continuo_4.5.0.c`. Si la compilación falla, ejecutar `git reset --hard HEAD@{1}` y abortar sin reiniciar Supervisor.
3. **[Mejora 3 - Publicación de Telemetría Post-Actualización]**:
   Configurar a `mqtt_coordinator.py` para emitir el hash del commit activo en `.../cmd/update/res` al iniciar tras una actualización exitosa.
4. **[Mejora 4 - Configuración de ACLs en Broker MQTT]**:
   Restringir los permisos en el broker Mosquitto para que los usuarios de las estaciones únicamente puedan suscribirse a su propio tópico de comandos y nunca publicar en canales de control.
5. **Criterios de aplicación**:
   * Implementar Mejoras 1 y 2 cuando la flota operativa supere las 3 estaciones para reducir el tiempo de mantenimiento manual.

---

## 9. Dependencias y Prerrequisitos

| Prerrequisito | Estado | Acción Requerida |
|---|---|---|
| **Broker MQTT con autenticación y TLS** | ⚠️ Parcial (Auth activa, TLS pendiente) | Configurar certificado TLS (puerto 8883) en broker de producción. |
| **ACLs en Broker Mosquitto** | ⬜ Por configurar | Definir archivo `aclfile` separando roles de administrador y estaciones. |
| **Desacoplamiento de procesos en Python** | ⬜ Por implementar | Utilizar `subprocess.Popen(..., start_new_session=True)` en `mqtt_coordinator.py`. |
| **Conexión estable a GitHub desde estación** | ✅ Disponible | Validado acceso mediante SSH/HTTPS en `ACEL-DEVP-UNIV-01`. |

---

## 10. Plan de Validación

| # | Checkpoint | Criterio de Éxito |
|---|---|---|
| **CP-1** | Saneamiento de ramas en estación | `git branch` muestra únicamente `* main` y `git status` reporta árbol limpio. |
| **CP-2** | Aislamiento de `main` | `ls` en la raíz de `main` no contiene `docs/` ni `AGENTS.md`. |
| **CP-3** | Lanzamiento desacoplado de `update.sh` | Al ejecutar `update.sh` desde un script secundario, el reinicio de Supervisor completa la compilación y reinicia los 4 daemons sin abortos. |
| **CP-4** | Rollback ante error de compilación | Si se fuerza un error de sintaxis en `registro_continuo_4.5.0.c`, `update.sh` revierte automáticamente al commit previo y los servicios continúan operando. |

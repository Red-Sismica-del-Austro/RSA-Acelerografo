---
id: ADR-018
titulo: Resiliencia y Desacoplamiento del Pipeline de Adquisición Acelerográfica
estado: Aceptado
fecha: 2026-09-02
temas: [acelerografo, resiliencia, adquisicion, systemd, dspic, named_pipe, watchdog, mqtt, supervisor]
entorno: acelerografo-DEV00
---

# ADR-018: Resiliencia y Desacoplamiento del Pipeline de Adquisición Acelerográfica

## Estado

**Aceptado** | Fecha: 2026-09-02

---

## Contexto

El 2026-09-01 se diagnosticó un incidente crítico en la estación acelerográfica CHA01 ([`2026-09-01_diagnostico_parada_adquisicion_cha01.md`](../analysis/2026-09-01_diagnostico_parada_adquisicion_cha01.md)). La caída silenciosa del binario C (`registro_continuo`) provocó un fallo en cascada:
1. **Ausencia de Auto-recuperación en SO**: El servicio systemd no contaba con directivas de reinicio automático (`Restart=always`).
2. **Desfasaje de Hardware dsPIC-RPi**: Tras reiniciar la Raspberry Pi sin un pulso físico previo en el pin MCLR del microcontrolador dsPIC33, el bus SPI quedaba desfasado. Tareas asíncronas en `crontab` (`@reboot sleep 30 && resetmaster`) generaban colisiones destructivas si reseteaban el hardware mientras la adquisición ya estaba en marcha.
3. **Fallo en Cascada en Capa de Streaming**: `stream_processor.py` fallaba de inmediato con `FileNotFoundError` al no encontrar `/tmp/my_pipe`, provocando que Supervisor lo marcara en estado fatal (`FATAL`).
4. **Falta de Visibilidad en Red Central**: No existía telemetría de latencia que alertara si los datos en disco o memoria se encontraban estancados.

---

## Opciones Evaluadas

### Opción A: Supervisión y Recuperación Monolítica en C
Integrar la lógica de watchdog, reintentos y alertas directamente en `registro_continuo_4.5.0.c`.
- **Ventajas**: Control centralizado en el proceso principal.
- **Desventajas**: Mayor complejidad en código C que interactúa directamente con registros GPIO/SPI en bajo nivel (`/dev/mem`); riesgo de fallos de segmentación; viola el principio de responsabilidad única.

### Opción B: Supervisión Exclusiva en Python con Scripts de Rescate
Mover la gestión del ciclo de vida y reseteo de hardware a daemons de Python bajo Supervisor.
- **Ventajas**: Flexibilidad y facilidad de manejo de excepciones.
- **Desventajas**: Los daemons en Python corren como usuario sin privilegios `rsa` y no pueden manipular hardware GPIO/SPI de bajo nivel ni reiniciar servicios del sistema sin privilegios de `root`.

### Opción C: Arquitectura en 4 Capas de Defensa en Profundidad y Desacoplamiento (Elegida)
Separar responsabilidades por capas de privilegio y roles de ejecución:
1. **Capa 1 (Hardware / Systemd como root)**: Unidad `rsa-acelerografo.service` con `Restart=always`, `RestartSec=5`, purga de `/tmp/my_pipe` y ejecución de `reset_master` en `ExecStartPre` (pulso MCLR previo a SPI). Eliminación de tareas `@reboot` en crontab.
2. **Capa 2 (Named Pipe IPC)**: Permisos `0666` incondicionales (`chmod`) y apertura `O_RDWR | O_NONBLOCK` para evitar bloqueos EOF/SIGPIPE.
3. **Capa 3 (Consumo en Supervisor como usuario rsa)**: Reintentos con backoff exponencial (`0.5s` $\rightarrow$ `8.0s`, máx `120s`) en `stream_processor.py` para desacoplar caídas transitorias de `registro_continuo`.
4. **Capa 4 (Telemetría y Watchdog MQTT)**: Módulo `AcquisitionWatchdog` en `mqtt_coordinator.py` que audita cada 60 s la frescura del Ring Buffer y emite alertas estructuradas en el tópico `{org}/{app}/{cap}/{id}/status/acquisition`.

---

## Decisión

Se eligió la **Opción C** porque proporciona una arquitectura de resiliencia integral y desacoplada que respeta los límites de privilegios del sistema operativo (root para hardware/systemd, usuario sin privilegios para daemons Python) y garantiza auto-recuperación determinista en $\le 5$ segundos ante cualquier fallo de hardware o software.

---

## Consecuencias

### Positivas
- **Auto-recuperación Determinista**: Systemd reinicia la adquisición en 5 segundos ante caídas abruptas (`SIGKILL`), resincronizando el dsPIC33 por hardware antes de reabrir el bus SPI.
- **Inmunidad ante Arranques Asíncronos**: `stream_processor.py` sobrevive a reinicios o paradas temporales de `registro_continuo` gracias al backoff exponencial, sin crashear en Supervisor.
- **Defensa de Permisos**: `/tmp/my_pipe` se purga en `ExecStartPre` y `ExecStopPost`, y se recrea con permisos `0666`.
- **Monitoreo Continuo**: La red central recibe cada 60 segundos la métrica `age_seconds` y alertas automáticas `warning: stale_data` si los datos superan los 5 minutos de antigüedad.

### Negativas / Deuda Técnica
- Requiere mantener sincronizada la plantilla `rsa-acelerografo.service.template` mediante `scripts/setup/update.sh` en los despliegues de la flota.

---

## Referencias

- Diagnóstico de origen: [`2026-09-01_diagnostico_parada_adquisicion_cha01.md`](../analysis/2026-09-01_diagnostico_parada_adquisicion_cha01.md)
- Blueprint de implementación: [`2026-09-02_plan_resiliencia_pipeline_adquisicion.md`](../blueprints/2026-09-02_plan_resiliencia_pipeline_adquisicion.md)
- Contextos técnicos relacionados:
  - [`acquisition_watchdog_context.md`](../context/acquisition_watchdog_context.md)
  - [`stream_processor_context.md`](../context/stream_processor_context.md)
  - [`mqtt_coordinator_context.md`](../context/mqtt_coordinator_context.md)
  - [`registro_continuo_context.md`](../context/registro_continuo_context.md)

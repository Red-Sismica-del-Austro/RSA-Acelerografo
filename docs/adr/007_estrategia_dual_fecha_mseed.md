---
id: ADR-007
titulo: Estrategia Dual de Fechas en Conversión a miniSEED (USAR_FECHA_FILENAME)
estado: Aceptado
fecha: 2026-06-24
temas: [acelerografo, conversion, mseed, obspy, reloj]
entorno: [acelerografo]
---

# ADR-007: Estrategia Dual de Fechas en Conversión a miniSEED (USAR_FECHA_FILENAME)

## Estado

**Aceptado** | Fecha: 2026-06-24

## Contexto

El microcontrolador dsPIC33EP de la estación acelerográfica sincroniza su tiempo inicialmente con un GPS o el RTC integrado (DS3234). Sin embargo, se ha documentado un comportamiento anómalo en la transición del cruce de medianoche (cambio de día a las 00:00:00 UTC). En ese instante, el reloj del dsPIC reporta correctamente la hora (horas, minutos, segundos), pero el calendario lógico interno no avanza de forma inmediata la fecha (año, mes, día), manteniendo la del día anterior durante las primeras tramas del nuevo día.

Esto produce un salto temporal negativo o desfases graves en las tramas grabadas en los archivos binarios `.dat`. Al convertir estos archivos a MiniSEED mediante la biblioteca ObsPy, la incoherencia en las fechas de las cabeceras provoca:
1.  Errores en el orden cronológico de las muestras.
2.  Discontinuidades en las trazas sísmicas que rompen el procesamiento en SeisComP.
3.  Comportamientos indefinidos en la rotación automática de archivos en disco.

## Opciones Evaluadas

### Opción A: Confiar Únicamente en los Timestamps de la Trama Binaria
Utilizar estrictamente los 6 bytes de timestamp de la trama binaria (`año, mes, día, hora, minuto, segundo`) para establecer la fecha y hora de inicio de las muestras en miniSEED.
*   **Ventajas:** Proceso directo y simple, auto-contenido en la trama.
*   **Desventajas:** La anomalía del dsPIC contamina los datos miniSEED resultantes, rompiendo los análisis automáticos de eventos de medianoche.

### Opción B: Forzar la Fecha de la Raspberry Pi (Host) en Todas las Tramas
Ignorar el calendario del dsPIC y usar el reloj del sistema de la Raspberry Pi (sincronizada vía NTP) para asignar la fecha y hora a todas las tramas en caliente.
*   **Ventajas:** Evita por completo las anomalías del dsPIC.
*   **Desventajas:** Si la Raspberry Pi pierde sincronía NTP o su reloj se desvía, se introduce un error sistemático en los datos que invalida los registros sísmicos.

### Opción C: Estrategia Dual con Extracción por Regex (`USAR_FECHA_FILENAME`)
Introducir un parámetro configurable `USAR_FECHA_FILENAME` en `configuracion_mseed.json`.
*   Si es `false`, se usa el comportamiento tradicional (fecha y hora desde los bytes de la trama).
*   Si es `true`, la conversión a miniSEED extrae el año, mes y día a partir del nombre del archivo binario `.dat` (ej. `{STATION}_{YYMMDD}-{HHMMSS}.dat`), el cual es nombrado por la Raspberry Pi al rotar el archivo con base en su reloj de sistema estable. Los campos de hora, minuto y segundo se siguen extrayendo del timestamp de la trama binaria para conservar la precisión del ciclo de muestreo físico del hardware.
*   **Ventajas:**
    *   Sana de forma limpia los desfases de fecha en la transición de medianoche del dsPIC.
    *   Conserva la precisión del segundo del hardware del dsPIC.
    *   Configurable por estación para mayor flexibilidad en depuraciones.
*   **Desventajas:** Depende de que el nombre del archivo `.dat` sea coherente con la fecha real (se asume que la Raspberry Pi no tiene desviaciones de días completos).

## Decisión

Se seleccionó la **Opción C: Estrategia Dual con Extracción por Regex (`USAR_FECHA_FILENAME`)**.

Esta solución de compromiso corrige de forma elegante el bug del firmware del dsPIC en el cruce de medianoche sin requerir detener o actualizar el firmware crítico en caliente. El nombre del archivo `.dat` se convierte en el ancla del calendario lógico (año/mes/día), mientras que la trama conserva el control cronológico intra-horario (hora/min/seg).

## Consecuencias

*   **Mitigación de Gaps:** Los archivos convertidos de medianoche se unifican de forma continua sin generar saltos de tiempo artificiales en ObsPy.
*   **Configuración Maestra:** Se agregó la bandera `"USAR_FECHA_FILENAME": true` por defecto en la plantilla de configuración de miniSEED.
*   **Implementación en Python:** El script `binary_to_mseed.py` implementa `extraer_fecha_desde_nombre_archivo()` usando la expresión regular `^[A-Z0-9]+_(\d{2})(\d{2})(\d{2})-\d{6}\.dat$`.

## Referencias

*   Contexto técnico relacionado: [binary_to_mseed_context.md](file:///c:/Users/miltonrsa/Documents/git/rsa/RSA-Acelerografo/docs/context/binary_to_mseed_context.md)

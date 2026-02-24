# Contexto del Script registrocontinuo.sh

**Archivo**: [scripts/task/registrocontinuo.sh](../../../scripts/task/registrocontinuo.sh)

**Propósito**: Script de orquestación principal que controla el ciclo de vida completo del sistema de adquisición de datos sismológicos (inicio, detención y reinicio).

**Versión analizada**: Script actual en el repositorio

**Autor**: No especificado en el código

**Fecha de análisis**: 2025-11-25

---

## Tabla de Contenidos

1. [Arquitectura del Sistema](#arquitectura-del-sistema)
2. [Propósito y Casos de Uso](#propósito-y-casos-de-uso)
3. [Dependencias](#dependencias)
4. [Comandos Disponibles](#comandos-disponibles)
5. [Flujo de Ejecución Detallado](#flujo-de-ejecución-detallado)
6. [Secuencia de Operaciones](#secuencia-de-operaciones)
7. [Configuración del Crontab](#configuración-del-crontab)
8. [Modo de Uso](#modo-de-uso)
9. [Consideraciones Importantes](#consideraciones-importantes)
10. [Problemas Identificados](#problemas-identificados)
11. [Mejoras Potenciales](#mejoras-potenciales)

---

## Arquitectura del Sistema

### Posición en el Flujo de Datos

```
┌─────────────────────────────────────────────────────────────────┐
│                    CAPA DE ORQUESTACIÓN                         │
│                                                                 │
│  ┌──────────────────────────────────────────┐                   │
│  │  registrocontinuo.sh                     │◄─── Este script   │
│  │  (este script)                           │                   │
│  │                                          │                   │
│  │  Comandos:                               │                   │
│  │  • start   → Inicia sistema completo     │                   │
│  │  • stop    → Detiene adquisición         │                   │
│  │  • restart → Reinicio completo           │                   │
│  └──────────────────┬───────────────────────┘                   │
│                     │                                           │
└─────────────────────┼───────────────────────────────────────────┘
                      │
                      ↓
┌─────────────────────────────────────────────────────────────────┐
│              FLUJO DE INICIO (start)                            │
│                                                                 │
│  1. registro_continuo (background)                              │
│     └─ Adquisición desde dsPIC vía SPI                          │
│        └─ Escritura en archivos .dat                            │
│                                                                 │
│  2. sleep 5 (espera estabilización)                             │
│                                                                 │
│  3. binary_to_mseed.py 1 (background, wait)                     │
│     └─ Convierte .dat anterior a .mseed                         │
│                                                                 │
│  4. gestor_archivos_acq.py (foreground)                         │
│     └─ Gestiona espacio en disco y sube a Drive                │
└─────────────────────────────────────────────────────────────────┘
                      │
                      ↓
┌─────────────────────────────────────────────────────────────────┐
│                    SISTEMA EN OPERACIÓN                         │
│                                                                 │
│  registro_continuo → .dat → binary_to_mseed → .mseed → Drive    │
│         (continuo)         (cada hora/evento)         (online)  │
└─────────────────────────────────────────────────────────────────┘
```

### Rol en el Sistema

El script `registrocontinuo.sh` actúa como **controlador maestro** del sistema:

1. **Orquestador de procesos**: Coordina inicio secuencial de componentes
2. **Gestor de ciclo de vida**: Start/stop/restart del sistema completo
3. **Invocado por cron**: Ejecutado periódicamente por tareas programadas
4. **Sincronizador**: Asegura tiempos de espera entre procesos dependientes

---

## Propósito y Casos de Uso

### Propósito Principal

Proporcionar una interfaz unificada para controlar el sistema completo de adquisición de datos sismológicos, garantizando el orden correcto de inicio y la limpieza adecuada al detener.

### Casos de Uso

#### 1. Inicio del Sistema de Adquisición

**Contexto**: Arranque de estación sismológica (boot, mantenimiento, etc.).

**Comando**:
```bash
sudo registrocontinuo.sh start
```

**Secuencia**:
1. Inicia `registro_continuo` en background (adquisición continua)
2. Espera 5 segundos (estabilización)
3. Convierte archivo .dat previo a .mseed
4. Ejecuta gestor de archivos (limpieza y subida)

**Resultado**: Sistema completamente operativo y registrando datos.

#### 2. Detención del Sistema

**Contexto**: Mantenimiento programado, actualización de software, apagado.

**Comando**:
```bash
sudo registrocontinuo.sh stop
```

**Secuencia**:
1. Termina proceso `registro_continuo` (señal SIGTERM)
2. Ejecuta `reset_master` (reinicia dsPIC vía GPIO)

**Resultado**: Sistema detenido limpiamente, hardware reiniciado.

#### 3. Reinicio Completo

**Contexto**: Recuperación de errores, cambio de configuración, testing.

**Comando**:
```bash
sudo registrocontinuo.sh restart
```

**Secuencia**:
1. Ejecuta `stop` (detención limpia)
2. Ejecuta `start` (inicio completo)

**Resultado**: Sistema reiniciado sin necesidad de reboot del sistema operativo.

#### 4. Ejecución Automática con Cron

**Contexto**: El sistema se orquesta completamente mediante tareas programadas en crontab.

**Archivo de configuración**: [scripts/task/crontab.txt](../../../scripts/task/crontab.txt)

**Tareas programadas actuales**:

```bash
# Reinicio horario del sistema (mantiene sistema fresco y recupera de errores)
0 * * * * /usr/local/bin/registrocontinuo restart

# Al arranque del sistema:
# 1. Resetea el circuito dsPIC (30s después del boot)
@reboot sleep 30 && /usr/local/bin/resetmaster

# 2. Verifica y sube archivos pendientes a Drive (60s después del boot)
@reboot sleep 60 && /usr/local/bin/uploadpendingfiles

# 3. Inicia el registro continuo (180s después del boot)
@reboot sleep 180 && /usr/local/bin/registrocontinuo start
```

**Secuencia de arranque del sistema**:
```
T=0s     │ Sistema operativo inicia
         │
T=30s    │ @reboot → resetmaster
         │ └─ Reinicia dsPIC vía GPIO
         │    └─ Hardware en estado inicial limpio
         │
T=60s    │ @reboot → uploadpendingfiles
         │ └─ Sube archivos .mseed pendientes a Drive
         │    └─ Recupera datos de desconexiones previas
         │
T=180s   │ @reboot → registrocontinuo start
         │ └─ Inicia adquisición completa
         │    └─ registro_continuo + conversión + gestión
         │
Cada 1h  │ Cron → registrocontinuo restart
         │ └─ Reinicia sistema preventivamente
         │    └─ Evita acumulación de errores
```

**Instalación del crontab**:
```bash
# Editar crontab del usuario root
sudo crontab -e

# Copiar contenido de scripts/task/crontab.txt
# O cargar directamente:
sudo crontab /home/rsa/git/montajes/acelerografo/scripts/task/crontab.txt

# Verificar instalación
sudo crontab -l
```

**Logs de cron**:
```bash
# Ver log del sistema
sudo grep CRON /var/log/syslog | tail -20

# Ver ejecuciones de registrocontinuo
sudo grep registrocontinuo /var/log/syslog

# Verificar última ejecución
sudo journalctl -t CRON --since "1 hour ago"
```

---

## Dependencias

### 1. Variables de Entorno

**Archivo**: `/usr/local/bin/project_paths`

**Contenido esperado**:
```bash
#!/bin/bash
export PROJECT_LOCAL_ROOT=/home/rsa
export PROJECT_GIT_ROOT=/home/rsa/git/montajes/acelerografo
```

**Uso en el script** (línea 4):
```bash
source /usr/local/bin/project_paths
```

**Importancia**: Define rutas base para todos los componentes del sistema.

### 2. Ejecutables Requeridos

| Ejecutable | Ubicación | Propósito |
|------------|-----------|-----------|
| `registro_continuo` | `$PROJECT_LOCAL_ROOT/scripts/acelerografo/ejecutables/` | Adquisición continua de datos |
| `reset_master` | `$PROJECT_LOCAL_ROOT/scripts/acelerografo/ejecutables/` | Reset de dsPIC vía GPIO |
| `binary_to_mseed.py` | `$PROJECT_LOCAL_ROOT/scripts/mseed/` | Conversión a Mini-SEED |
| `gestor_archivos_acq.py` | `$PROJECT_LOCAL_ROOT/scripts/drive/` | Gestión de almacenamiento |

### 3. Permisos Requeridos

- **sudo**: Requerido para ejecutar el script (acceso a GPIO y kill de procesos)
- **Ejecución**: El script debe tener permisos de ejecución (`chmod +x`)
- **Usuario**: Típicamente ejecutado como root o con sudo

---

## Comandos Disponibles

### 1. start

**Sintaxis**:
```bash
sudo registrocontinuo.sh start
```

**Descripción**: Inicia el sistema completo de adquisición.

**Operaciones**:
1. Imprime mensaje: "Arrancando sistema de registro continuo..."
2. Inicia `registro_continuo` con sudo -E (preserva variables de entorno)
3. Ejecuta en background (&)
4. Espera 5 segundos
5. Ejecuta `binary_to_mseed.py 1` en background
6. Espera a que termine la conversión (wait)
7. Ejecuta `gestor_archivos_acq.py` en foreground

**Código** (líneas 8-16):
```bash
start)
  echo "Arrancando sistema de registro continuo..."
  sudo -E "$PROJECT_LOCAL_ROOT/scripts/acelerografo/ejecutables/registro_continuo" &
  sleep 5
  /usr/bin/python3 "$PROJECT_LOCAL_ROOT/scripts/mseed/binary_to_mseed.py" 1 &
  pid_mseed=$!
  wait $pid_mseed
  /usr/bin/python3 "$PROJECT_LOCAL_ROOT/scripts/drive/gestor_archivos_acq.py"
  ;;
```

**Salida esperada**:
```
Arrancando sistema de registro continuo...
[registro_continuo inicia en background]
[5 segundos de espera]
[Conversión de archivo .dat anterior]
[Gestión de archivos y subida a Drive]
```

**Importante**: El script NO se queda bloqueado después del `start`. Todos los procesos corren en background excepto el gestor.

---

### 2. stop

**Sintaxis**:
```bash
sudo registrocontinuo.sh stop
```

**Descripción**: Detiene el sistema de adquisición.

**Operaciones**:
1. Imprime mensaje: "Deteniendo sistema de registro continuo..."
2. Termina todos los procesos `registro_continuo` con `killall -q` (quiet, no error si no existe)
3. Ejecuta `reset_master` para reiniciar el dsPIC

**Código** (líneas 18-22):
```bash
stop)
  echo "Deteniendo sistema de registro continuo..."
  sudo killall -q registro_continuo
  sudo "$PROJECT_LOCAL_ROOT/scripts/acelerografo/ejecutables/reset_master"
  ;;
```

**Salida esperada**:
```
Deteniendo sistema de registro continuo...
[registro_continuo termina]
[dsPIC se reinicia]
```

**Importante**:
- `killall` envía SIGTERM (terminación limpia)
- `-q` suprime error si el proceso no existe
- `reset_master` reinicia el hardware (GPIO reset al dsPIC)

---

### 3. restart

**Sintaxis**:
```bash
sudo registrocontinuo.sh restart
```

**Descripción**: Reinicia el sistema completamente (stop + start).

**Operaciones**:
1. Imprime mensaje: "Reiniciando sistema de registro continuo..."
2. Ejecuta `$0 stop` (detiene sistema)
3. Si stop exitoso (&&), ejecuta `$0 start` (inicia sistema)

**Código** (líneas 24-27):
```bash
restart)
  echo "Reiniciando sistema de registro continuo..."
  $0 stop && $0 start
  ;;
```

**Salida esperada**:
```
Reiniciando sistema de registro continuo...
Deteniendo sistema de registro continuo...
[stop completa]
Arrancando sistema de registro continuo...
[start completa]
```

**Importante**:
- `$0` es la ruta del propio script
- `&&` asegura que start solo se ejecuta si stop fue exitoso
- No hay delay adicional entre stop y start (solo el incluido en start)

---

### 4. Uso incorrecto

**Descripción**: Cualquier argumento distinto de start/stop/restart.

**Código** (líneas 29-32):
```bash
*)
  echo "Modo de uso: registrocontinuo start|stop|restart"
  exit 1
  ;;
```

**Salida**:
```bash
$ ./registrocontinuo.sh invalid
Modo de uso: registrocontinuo start|stop|restart
$ echo $?
1
```

---

## Flujo de Ejecución Detallado

### Secuencia START en Timeline

```
T=0s    │ registrocontinuo.sh start
        │ └─ echo "Arrancando sistema..."
        │
T=0.1s  │ sudo -E registro_continuo &
        │ └─ Proceso PID 1234 inicia
        │    └─ Inicializa SPI con dsPIC
        │    └─ Crea archivo .dat nuevo
        │    └─ Entra en loop de adquisición (1 Hz)
        │
T=0.2s  │ sleep 5
        │ [script bloqueado esperando]
        │
        │ [Mientras tanto, registro_continuo está escribiendo tramas]
        │
T=5.2s  │ sleep completo
        │
T=5.2s  │ python3 binary_to_mseed.py 1 &
        │ └─ Proceso PID 1240 inicia
        │    └─ Lee $PROJECT_LOCAL_ROOT/tmp-files/NombreArchivoRegistroContinuo.tmp
        │    └─ Línea 2 contiene nombre del archivo .dat ANTERIOR (cerrado)
        │    └─ Convierte archivo anterior a .mseed
        │
T=5.2s  │ pid_mseed=1240
        │ wait 1240
        │ [script bloqueado esperando conversión]
        │
T=8.5s  │ binary_to_mseed.py termina (código exit 0)
        │
T=8.5s  │ wait completo
        │
T=8.5s  │ python3 gestor_archivos_acq.py
        │ └─ Proceso PID 1245 inicia (foreground)
        │    └─ Lee configuración (modo online/offline)
        │    └─ Escanea archivos .mseed y .dat
        │    └─ Si online: sube .mseed a Drive
        │    └─ Gestiona espacio en disco
        │
T=15.0s │ gestor_archivos_acq.py termina
        │
T=15.0s │ exit 0
        │ registrocontinuo.sh termina
        │
        │ [registro_continuo continúa en background]
```

### Procesos Resultantes Después de START

```bash
$ ps aux | grep registro
root      1234  1.5  0.2  registro_continuo
# Script registrocontinuo.sh ya terminó
# binary_to_mseed.py ya terminó
# gestor_archivos_acq.py ya terminó
```

**Importante**: Solo `registro_continuo` queda ejecutándose de forma permanente.

---

### Secuencia STOP en Timeline

```
T=0s    │ registrocontinuo.sh stop
        │ └─ echo "Deteniendo sistema..."
        │
T=0.1s  │ sudo killall -q registro_continuo
        │ └─ Envía SIGTERM al proceso PID 1234
        │
T=0.2s  │ registro_continuo recibe SIGTERM
        │ └─ Cierra archivo .dat actual
        │ └─ Cierra SPI
        │ └─ Libera recursos
        │ └─ Termina (exit)
        │
T=0.5s  │ sudo reset_master
        │ └─ Ejecuta programa reset_master
        │    └─ Configura GPIO para reset dsPIC
        │    └─ Pulso bajo en pin de reset
        │    └─ dsPIC reinicia firmware
        │
T=1.0s  │ reset_master termina
        │
T=1.0s  │ exit 0
        │ registrocontinuo.sh termina
```

### Procesos Resultantes Después de STOP

```bash
$ ps aux | grep registro
# (ningún resultado)
```

**Estado del hardware**: dsPIC reiniciado, esperando comandos SPI.

---

## Secuencia de Operaciones

### Diagrama de Flujo START

```
registrocontinuo.sh start
    ↓
┌────────────────────────────────────────┐
│ 1. Imprimir mensaje de inicio         │
└────────────────────────────────────────┘
    ↓
┌────────────────────────────────────────┐
│ 2. Iniciar registro_continuo           │
│    - sudo -E (preserva env vars)       │
│    - Background (&)                    │
│    - Adquisición continua 1 Hz         │
└────────────────────────────────────────┘
    ↓
┌────────────────────────────────────────┐
│ 3. sleep 5                             │
│    - Espera estabilización SPI         │
│    - Permite que se cree primer .dat   │
└────────────────────────────────────────┘
    ↓
┌────────────────────────────────────────┐
│ 4. Iniciar binary_to_mseed.py 1        │
│    - Background (&)                    │
│    - Modo "1" = registro continuo      │
│    - Convierte .dat ANTERIOR (cerrado) │
└────────────────────────────────────────┘
    ↓
┌────────────────────────────────────────┐
│ 5. Capturar PID y wait                 │
│    - pid_mseed=$!                      │
│    - wait $pid_mseed                   │
│    - Bloquea hasta conversión completa │
└────────────────────────────────────────┘
    ↓
┌────────────────────────────────────────┐
│ 6. Ejecutar gestor_archivos_acq.py     │
│    - Foreground (no &)                 │
│    - Gestiona espacio en disco         │
│    - Sube archivos a Drive (si online) │
└────────────────────────────────────────┘
    ↓
┌────────────────────────────────────────┐
│ 7. exit 0                              │
│    - Script termina                    │
│    - registro_continuo sigue activo    │
└────────────────────────────────────────┘
```

### Diagrama de Flujo STOP

```
registrocontinuo.sh stop
    ↓
┌────────────────────────────────────────┐
│ 1. Imprimir mensaje de detención      │
└────────────────────────────────────────┘
    ↓
┌────────────────────────────────────────┐
│ 2. sudo killall -q registro_continuo   │
│    - Envía SIGTERM a todos los procesos│
│    - -q: sin error si no existe        │
│    - Terminación limpia                │
└────────────────────────────────────────┘
    ↓
┌────────────────────────────────────────┐
│ 3. registro_continuo recibe SIGTERM    │
│    - Cierra archivo .dat actual        │
│    - Libera recursos SPI               │
│    - Sale limpiamente                  │
└────────────────────────────────────────┘
    ↓
┌────────────────────────────────────────┐
│ 4. sudo reset_master                   │
│    - Reinicia dsPIC vía GPIO           │
│    - Pulso de reset en hardware        │
│    - dsPIC vuelve a estado inicial     │
└────────────────────────────────────────┘
    ↓
┌────────────────────────────────────────┐
│ 5. exit 0                              │
│    - Script termina                    │
│    - Sistema detenido completamente    │
└────────────────────────────────────────┘
```

---

## Configuración del Crontab

### Archivo de Configuración

**Ubicación**: [scripts/task/crontab.txt](../../../scripts/task/crontab.txt)

**Contenido completo**:
```bash
# Reinicia el registro continuo cada hora:
0 * * * * /usr/local/bin/registrocontinuo restart

# Resetea el circuito al iniciar el sistema:
@reboot sleep 30 && /usr/local/bin/resetmaster

# Verifica si existen archivos pendientes de subir a Drive:
@reboot sleep 60 && /usr/local/bin/uploadpendingfiles

# Espera 180 segundos al arranque del sistema para ejecutar el registro continuo:
@reboot sleep 180 && /usr/local/bin/registrocontinuo start
```

### Análisis de Tareas Programadas

#### 1. Reinicio Horario del Sistema

```bash
0 * * * * /usr/local/bin/registrocontinuo restart
```

**Propósito**:
- Reinicia el sistema cada hora en punto (00:00, 01:00, 02:00, etc.)
- Previene acumulación de errores de memoria o estado
- Cierra archivos .dat anteriores y genera archivo .mseed
- Mantiene sistema "fresco" y estable

**Frecuencia alternativa comentada**:
```bash
# Cada 6 horas (comentada actualmente)
#0 */6 * * * /usr/local/bin/registrocontinuo restart
```

**Ventajas del reinicio horario**:
- Archivos .dat de tamaño predecible (~9 MB/hora)
- Archivos .mseed de tamaño manejable (~3 MB/hora)
- Facilita troubleshooting (timestamps alineados a horas)
- Limita pérdida de datos ante fallo (máximo 1 hora)

**Desventajas**:
- Breve interrupción de datos (~15 segundos cada hora)
- Mayor cantidad de archivos a gestionar

#### 2. Reset del Hardware al Arranque

```bash
@reboot sleep 30 && /usr/local/bin/resetmaster
```

**Propósito**:
- Reinicia el dsPIC vía GPIO al arrancar el sistema operativo
- Asegura que hardware esté en estado inicial conocido
- Previene estados inconsistentes tras apagados incorrectos

**Delay de 30 segundos**:
- Permite que sistema operativo estabilice GPIO
- Asegura que drivers estén cargados
- Evita condiciones de carrera con inicialización del sistema

#### 3. Subida de Archivos Pendientes

```bash
@reboot sleep 60 && /usr/local/bin/uploadpendingfiles
```

**Propósito**:
- Verifica y sube archivos .mseed que no se subieron antes del apagado
- Recupera datos de desconexiones de red previas
- Mantiene respaldo en Google Drive actualizado

**Delay de 60 segundos**:
- Permite que red esté completamente inicializada
- Asegura conectividad antes de intentar subida
- Evita fallos por red no disponible

**Nota**: El script `uploadpendingfiles` debe existir en `/usr/local/bin/`.

#### 4. Inicio del Registro Continuo

```bash
@reboot sleep 180 && /usr/local/bin/registrocontinuo start
```

**Propósito**:
- Inicia adquisición de datos automáticamente al arrancar
- Asegura operación continua tras reinicios o cortes de energía
- No requiere intervención manual

**Delay de 180 segundos (3 minutos)**:
- Espera que todos los servicios del sistema estén activos
- Asegura que reset del dsPIC (T=30s) ya ocurrió
- Asegura que subida de pendientes (T=60s) ya ocurrió
- Permite estabilización completa del sistema

**Secuencia temporal**:
```
T=0s   → Sistema arranca
T=30s  → Reset dsPIC
T=60s  → Sube archivos pendientes
T=180s → Inicia registro continuo
       → Sistema completamente operativo
```

### Instalación y Gestión

#### Instalar crontab

```bash
# Opción 1: Editar manualmente
sudo crontab -e
# Copiar contenido de scripts/task/crontab.txt

# Opción 2: Cargar desde archivo
sudo crontab /home/rsa/git/montajes/acelerografo/scripts/task/crontab.txt

# Verificar instalación
sudo crontab -l
```

#### Verificar ejecución

```bash
# Ver últimas 20 líneas del log de cron
sudo grep CRON /var/log/syslog | tail -20

# Ver ejecuciones específicas de registrocontinuo
sudo grep "registrocontinuo" /var/log/syslog

# Ver errores
sudo grep "registrocontinuo" /var/log/syslog | grep -i error

# Monitorear en tiempo real
sudo tail -f /var/log/syslog | grep CRON
```

#### Deshabilitar temporalmente

```bash
# Comentar tarea específica
sudo crontab -e
# Agregar # al inicio de la línea

# O remover completamente
sudo crontab -r  # ¡Cuidado! Elimina TODO el crontab
```

### Enlaces Simbólicos Requeridos

Para que cron encuentre los scripts, deben existir enlaces simbólicos en `/usr/local/bin/`:

```bash
# Crear enlaces simbólicos
sudo ln -s /home/rsa/scripts/task/registrocontinuo.sh /usr/local/bin/registrocontinuo
sudo ln -s /home/rsa/scripts/acelerografo/ejecutables/reset_master /usr/local/bin/resetmaster
sudo ln -s /home/rsa/scripts/drive/upload_pending_files.py /usr/local/bin/uploadpendingfiles

# Dar permisos de ejecución
sudo chmod +x /usr/local/bin/registrocontinuo
sudo chmod +x /usr/local/bin/resetmaster
sudo chmod +x /usr/local/bin/uploadpendingfiles

# Verificar enlaces
ls -l /usr/local/bin/ | grep -E "(registrocontinuo|resetmaster|uploadpendingfiles)"
```

### Consideraciones de Cron

**Variables de entorno**:
- Cron ejecuta con PATH limitado: `/usr/bin:/bin`
- Variables definidas en `project_paths` están disponibles por el `source` en registrocontinuo.sh
- Usar rutas absolutas siempre

**Usuario de ejecución**:
- Tareas se ejecutan como root (sudo crontab)
- Necesario para acceso a GPIO y SPI

**Logging**:
- Salida estándar/error no se captura por defecto
- Redirigir a archivo si se necesita: `>> /var/log/cron-registro.log 2>&1`

**Sincronización de tiempo**:
- Asegurarse que NTP esté configurado
- Reinicios horarios dependen de reloj preciso

---

## Modo de Uso

### Uso Manual

#### Inicio del Sistema

```bash
# Como root
sudo /home/rsa/scripts/task/registrocontinuo.sh start

# O si está en PATH
sudo registrocontinuo.sh start
```

**Salida esperada**:
```
Arrancando sistema de registro continuo...
[Pausa de 5 segundos]
Convirtiendo el archivo: RSA01_20251125_130000.dat
Primer elemento de tiempos_np: 46800
Último elemento de tiempos_np: 50399
...
Tiempo total de ejecución: 2.3456 segundos
Se encontraron 24 archivos mseed y 2 archivos binarios.
Modo online activado.
Conexión a internet verificada.
...
```

#### Verificación de Estado

```bash
# Ver procesos
ps aux | grep registro_continuo

# Salida esperada:
# root  1234  1.5  0.2  registro_continuo

# Ver último archivo .dat
ls -lht /home/rsa/resultados/registro-continuo/ | head -5

# Ver logs
tail -f /home/rsa/log-files/adquisicion.log
```

#### Detención del Sistema

```bash
sudo registrocontinuo.sh stop
```

**Salida esperada**:
```
Deteniendo sistema de registro continuo...
[Sistema se detiene limpiamente]
```

#### Reinicio del Sistema

```bash
sudo registrocontinuo.sh restart
```

**Salida esperada**:
```
Reiniciando sistema de registro continuo...
Deteniendo sistema de registro continuo...
Arrancando sistema de registro continuo...
[Sistema reinicia completamente]
```

---

### Verificación del Sistema con Cron

```bash
# Ver estado del crontab actual
sudo crontab -l

# Verificar última ejecución del reinicio horario
sudo grep "registrocontinuo restart" /var/log/syslog | tail -5

# Verificar proceso activo
ps aux | grep registro_continuo

# Ver estadísticas de uptime
ps -p $(pgrep registro_continuo) -o pid,etime,cmd

# Verificar próxima ejecución programada
# (cron no muestra próximas ejecuciones, pero se puede calcular)
date && echo "Próximo restart en: $(date -d 'next hour' '+%H:00')"
```

### Modificar Frecuencia de Reinicio

Si se desea cambiar la frecuencia del reinicio automático:

```bash
# Editar crontab
sudo crontab -e

# Opciones comunes:

# Cada 6 horas (a las 00:00, 06:00, 12:00, 18:00)
0 */6 * * * /usr/local/bin/registrocontinuo restart

# Cada 12 horas (a las 00:00 y 12:00)
0 */12 * * * /usr/local/bin/registrocontinuo restart

# Una vez al día (a las 03:00)
0 3 * * * /usr/local/bin/registrocontinuo restart

# Cada 30 minutos
*/30 * * * * /usr/local/bin/registrocontinuo restart
```

### Logging Extendido

Para capturar salida de cron en archivo dedicado:

```bash
# Modificar tarea en crontab
0 * * * * /usr/local/bin/registrocontinuo restart >> /var/log/registro-continuo-cron.log 2>&1

# Ver log
tail -f /var/log/registro-continuo-cron.log

# Rotar logs (crear /etc/logrotate.d/registro-continuo)
sudo nano /etc/logrotate.d/registro-continuo
```

Contenido de logrotate:
```
/var/log/registro-continuo-cron.log {
    daily
    rotate 7
    compress
    missingok
    notifempty
}
```

---

## Consideraciones Importantes

### 1. Permisos y Sudo

**Requisito**: El script debe ejecutarse con `sudo` para:
- Acceder a GPIO (reset del dsPIC)
- Acceder a SPI (`/dev/spidev0.0`)
- Matar procesos de otros usuarios (si aplica)

**Preservación de variables de entorno**:
```bash
sudo -E registro_continuo
#      └─ Preserva PROJECT_LOCAL_ROOT y otras variables
```

**Alternativa sin sudo** (no recomendada):
```bash
# Agregar usuario al grupo gpio y spi
sudo usermod -a -G gpio,spi rsa

# Configurar permisos
sudo chmod 666 /dev/spidev0.0
sudo chmod 666 /sys/class/gpio/export
```

---

### 2. Timing y Sincronización

#### Sleep de 5 Segundos (línea 11)

**Propósito**:
1. **Estabilización de SPI**: Permite que la comunicación con dsPIC se establezca
2. **Creación de archivo**: Asegura que el primer archivo .dat se haya creado
3. **Actualización de .tmp**: Garantiza que NombreArchivoRegistroContinuo.tmp tenga 2 líneas

**Por qué 5 segundos**:
- `registro_continuo` crea archivo inmediatamente (~0.5s)
- Escribe primera trama en 1 segundo (loop a 1 Hz)
- Actualiza archivo .tmp (~0.1s)
- Margen de seguridad: 3.4s adicionales

**Problema si es muy corto** (ej. 1 segundo):
```bash
# binary_to_mseed.py intenta leer archivo .tmp
# Línea 2 aún no existe o está vacía
# Error: IndexError: list index out of range
```

#### Wait del PID de binary_to_mseed (líneas 13-14)

**Propósito**:
- Asegura que conversión termine antes de ejecutar gestor
- Evita race condition (gestor intentando borrar archivo siendo convertido)
- Mantiene orden lógico: convertir → gestionar

**Sin wait** (problema):
```bash
# binary_to_mseed.py convirtiendo archivo X.dat (background)
# gestor_archivos_acq.py ejecuta inmediatamente
# gestor intenta borrar X.dat mientras se lee
# Error: OSError: [Errno 26] Text file busy
```

---

### 3. Procesos en Background vs Foreground

| Proceso | Modo | Razón |
|---------|------|-------|
| `registro_continuo` | Background (&) | Debe correr permanentemente |
| `binary_to_mseed.py` | Background (&) + wait | Permite capturar PID para espera sincronizada |
| `gestor_archivos_acq.py` | Foreground | Debe completar antes de que script termine |

**Comportamiento del script**:
- Script termina después de ejecutar gestor
- Solo `registro_continuo` queda activo
- Próximas conversiones/gestiones se hacen vía cron o eventos

---

### 4. Variables de Entorno

**Archivo de variables** (`/usr/local/bin/project_paths`):
```bash
#!/bin/bash
export PROJECT_LOCAL_ROOT=/home/rsa
export PROJECT_GIT_ROOT=/home/rsa/git/montajes/acelerografo
```

**Importancia**:
- Centraliza configuración de rutas
- Facilita cambios (solo editar un archivo)
- Permite multiple deployments (desarrollo/producción)

**Verificación**:
```bash
# Probar carga de variables
source /usr/local/bin/project_paths
echo $PROJECT_LOCAL_ROOT
# Debe imprimir: /home/rsa
```

**Creación del archivo** (si no existe):
```bash
sudo nano /usr/local/bin/project_paths
# Agregar contenido
sudo chmod +x /usr/local/bin/project_paths
```

---

### 5. Manejo de Señales y Terminación

**killall -q** (línea 20):
- `-q`: Quiet, no error si proceso no existe
- Sin `-q`: exit code 1 si no encuentra proceso
- Envía **SIGTERM** (15): terminación limpia

**Alternativas de señales**:
```bash
# SIGTERM (15) - Terminación limpia (usado actualmente)
killall -SIGTERM registro_continuo

# SIGINT (2) - Interrupción (Ctrl+C)
killall -SIGINT registro_continuo

# SIGKILL (9) - Forzar terminación (no recomendado)
killall -9 registro_continuo  # No permite cerrar archivos limpiamente
```

**Manejo en registro_continuo**:
```c
// registro_continuo.c debe tener handler de señales
signal(SIGTERM, cleanup_handler);

void cleanup_handler(int sig) {
    fclose(fileX);         // Cerrar archivo .dat
    bcm2835_spi_end();     // Cerrar SPI
    bcm2835_close();       // Liberar bcm2835
    exit(0);               // Salir limpiamente
}
```

---

## Problemas Identificados

### 1. No Hay Validación de Existencia de Ejecutables

**Líneas problemáticas**: 10, 12, 15, 21

**Problema**: El script asume que todos los ejecutables y scripts existen.

**Impacto**:
- Si falta un ejecutable: error críptico
- Dificulta diagnóstico de problemas

**Ejemplo de fallo**:
```bash
$ sudo registrocontinuo.sh start
Arrancando sistema de registro continuo...
bash: /home/rsa/scripts/acelerografo/ejecutables/registro_continuo: No such file or directory
[Script continúa ejecutando binary_to_mseed.py sin adquisición activa]
```

**Solución sugerida**:
```bash
start)
  # Validar existencia de ejecutables
  if [ ! -f "$PROJECT_LOCAL_ROOT/scripts/acelerografo/ejecutables/registro_continuo" ]; then
    echo "Error: registro_continuo no encontrado"
    exit 1
  fi

  if [ ! -f "$PROJECT_LOCAL_ROOT/scripts/mseed/binary_to_mseed.py" ]; then
    echo "Error: binary_to_mseed.py no encontrado"
    exit 1
  fi

  echo "Arrancando sistema de registro continuo..."
  # ... resto del código
  ;;
```

---

### 2. No Hay Verificación de Éxito de Procesos

**Problema**: No verifica que `registro_continuo` haya iniciado correctamente antes de continuar.

**Impacto**:
- Si `registro_continuo` falla al iniciar, el resto del script se ejecuta igual
- `binary_to_mseed.py` intenta convertir archivo que no está siendo generado

**Solución sugerida**:
```bash
start)
  echo "Arrancando sistema de registro continuo..."
  sudo -E "$PROJECT_LOCAL_ROOT/scripts/acelerografo/ejecutables/registro_continuo" &
  rc_pid=$!

  # Verificar que el proceso sigue activo después de 2 segundos
  sleep 2
  if ! kill -0 $rc_pid 2>/dev/null; then
    echo "Error: registro_continuo falló al iniciar"
    exit 1
  fi

  sleep 3  # Total 5 segundos de espera
  # ... resto del código
  ;;
```

---

### 3. Sleep Hardcoded Sin Configuración

**Línea**: 11

**Problema**: El delay de 5 segundos está hardcoded.

**Impacto**:
- Inflexible para diferentes hardware (Raspberry Pi 3 vs 4)
- En hardware más rápido: espera innecesaria
- En hardware más lento: posible race condition

**Solución sugerida**:
```bash
# Al inicio del script
STARTUP_DELAY=${STARTUP_DELAY:-5}  # Default 5, configurable vía env var

# En el comando start
sleep $STARTUP_DELAY
```

**Uso**:
```bash
# Delay personalizado
STARTUP_DELAY=3 sudo registrocontinuo.sh start
```

---

### 4. No Hay Logging de Errores

**Problema**: Errores van solo a stdout/stderr, no a archivo de log.

**Impacto**:
- Difícil troubleshooting en producción
- Logs de systemd son la única fuente (no siempre disponibles)

**Solución sugerida**:
```bash
#!/bin/bash

# Configurar logging
LOG_FILE="/var/log/registrocontinuo.log"
exec 1> >(tee -a "$LOG_FILE")
exec 2>&1

log() {
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1"
}

# Uso
case "$1" in
  start)
    log "Iniciando sistema de registro continuo..."
    # ... resto del código
    ;;
esac
```

---

### 5. restart No Tiene Delay Entre stop y start

**Línea**: 26

**Problema**: `$0 stop && $0 start` ejecuta start inmediatamente después de stop.

**Impacto**:
- dsPIC podría no haber terminado de reiniciarse
- SPI podría no estar disponible
- Posibles errores de "device busy"

**Solución sugerida**:
```bash
restart)
  echo "Reiniciando sistema de registro continuo..."
  $0 stop
  if [ $? -eq 0 ]; then
    echo "Esperando 3 segundos antes de reiniciar..."
    sleep 3
    $0 start
  else
    echo "Error en stop, abortando restart"
    exit 1
  fi
  ;;
```

---

### 6. killall Puede Afectar Múltiples Instancias

**Línea**: 20

**Problema**: `killall registro_continuo` termina TODAS las instancias.

**Impacto**:
- Si hay múltiples estaciones en mismo servidor (raro pero posible)
- Afecta todas las instancias, no solo la deseada

**Solución sugerida**:
```bash
# Guardar PID en start
start)
  sudo -E "$PROJECT_LOCAL_ROOT/scripts/acelerografo/ejecutables/registro_continuo" &
  echo $! > /var/run/registro_continuo.pid
  # ... resto
  ;;

# Usar PID específico en stop
stop)
  if [ -f /var/run/registro_continuo.pid ]; then
    PID=$(cat /var/run/registro_continuo.pid)
    sudo kill $PID
    rm /var/run/registro_continuo.pid
  else
    echo "Warning: PID file no encontrado, usando killall"
    sudo killall -q registro_continuo
  fi
  sudo "$PROJECT_LOCAL_ROOT/scripts/acelerografo/ejecutables/reset_master"
  ;;
```

---

### 7. No Hay Manejo de Fallo de reset_master

**Línea**: 21

**Problema**: Si `reset_master` falla, no hay indicación ni manejo.

**Impacto**:
- dsPIC podría quedar en estado inconsistente
- Próximo start podría fallar

**Solución sugerida**:
```bash
stop)
  echo "Deteniendo sistema de registro continuo..."
  sudo killall -q registro_continuo

  if sudo "$PROJECT_LOCAL_ROOT/scripts/acelerografo/ejecutables/reset_master"; then
    echo "dsPIC reiniciado correctamente"
  else
    echo "Warning: Fallo al reiniciar dsPIC (código: $?)"
    echo "Puede ser necesario reiniciar el hardware manualmente"
    exit 1
  fi
  ;;
```

---

## Mejoras Potenciales

### 1. Modo Daemon con PID File

**Propuesta**: Gestión completa de daemon con PID file.

```bash
#!/bin/bash

PID_FILE="/var/run/registro_continuo.pid"
LOG_FILE="/var/log/registrocontinuo.log"

is_running() {
  [ -f "$PID_FILE" ] && kill -0 $(cat "$PID_FILE") 2>/dev/null
}

start_daemon() {
  if is_running; then
    echo "Ya está ejecutándose (PID: $(cat $PID_FILE))"
    return 1
  fi

  echo "Iniciando daemon..."
  sudo -E "$PROJECT_LOCAL_ROOT/scripts/acelerografo/ejecutables/registro_continuo" &
  echo $! > "$PID_FILE"

  # Verificar inicio exitoso
  sleep 2
  if is_running; then
    echo "Daemon iniciado (PID: $(cat $PID_FILE))"
  else
    echo "Error: Daemon falló al iniciar"
    rm -f "$PID_FILE"
    return 1
  fi
}

stop_daemon() {
  if ! is_running; then
    echo "No está ejecutándose"
    rm -f "$PID_FILE"
    return 0
  fi

  PID=$(cat "$PID_FILE")
  echo "Deteniendo daemon (PID: $PID)..."

  sudo kill $PID

  # Esperar terminación (timeout 10s)
  for i in {1..10}; do
    if ! kill -0 $PID 2>/dev/null; then
      break
    fi
    sleep 1
  done

  # Forzar si no terminó
  if kill -0 $PID 2>/dev/null; then
    echo "Forzando terminación..."
    sudo kill -9 $PID
  fi

  rm -f "$PID_FILE"
  echo "Daemon detenido"
}

case "$1" in
  start)
    start_daemon || exit 1
    # ... resto de procesamiento
    ;;
  stop)
    stop_daemon
    ;;
  status)
    if is_running; then
      echo "Running (PID: $(cat $PID_FILE))"
      exit 0
    else
      echo "Stopped"
      exit 3
    fi
    ;;
esac
```

---

### 2. Health Check y Monitoreo

**Propuesta**: Comando `status` que verifica estado completo del sistema.

```bash
status)
  echo "Estado del Sistema de Registro Continuo:"
  echo "=========================================="

  # 1. Proceso principal
  if is_running; then
    PID=$(cat $PID_FILE)
    echo "✓ registro_continuo: ACTIVO (PID: $PID)"

    # CPU y memoria
    ps -p $PID -o %cpu,%mem,etime | tail -1 | \
      awk '{printf "  CPU: %s%% | RAM: %s%% | Uptime: %s\n", $1, $2, $3}'
  else
    echo "✗ registro_continuo: INACTIVO"
  fi

  # 2. Último archivo .dat
  LAST_DAT=$(ls -t $PROJECT_LOCAL_ROOT/resultados/registro-continuo/*.dat 2>/dev/null | head -1)
  if [ -n "$LAST_DAT" ]; then
    AGE=$(($(date +%s) - $(stat -c %Y "$LAST_DAT")))
    echo "✓ Último archivo .dat: $(basename $LAST_DAT) (${AGE}s)"

    if [ $AGE -gt 10 ]; then
      echo "  ⚠ Warning: Archivo no actualizado hace más de 10s"
    fi
  else
    echo "✗ No hay archivos .dat"
  fi

  # 3. Espacio en disco
  FREE=$(df -h $PROJECT_LOCAL_ROOT/resultados | tail -1 | awk '{print $4}')
  PERCENT=$(df -h $PROJECT_LOCAL_ROOT/resultados | tail -1 | awk '{print $5}')
  echo "✓ Espacio libre: $FREE (usado: $PERCENT)"

  # 4. Conexión a internet (para modo online)
  if ping -c 1 -W 1 8.8.8.8 >/dev/null 2>&1; then
    echo "✓ Conexión a internet: OK"
  else
    echo "✗ Conexión a internet: FALLO"
  fi

  # 5. Archivos .mseed pendientes
  MSEED_COUNT=$(ls $PROJECT_LOCAL_ROOT/resultados/mseed/*.mseed 2>/dev/null | wc -l)
  echo "ℹ Archivos .mseed pendientes: $MSEED_COUNT"

  ;;
```

**Salida ejemplo**:
```
Estado del Sistema de Registro Continuo:
==========================================
✓ registro_continuo: ACTIVO (PID: 1234)
  CPU: 1.5% | RAM: 0.2% | Uptime: 02:15:34
✓ Último archivo .dat: RSA01_20251125_143000.dat (3s)
✓ Espacio libre: 12.5G (usado: 35%)
✓ Conexión a internet: OK
ℹ Archivos .mseed pendientes: 5
```

---

### 3. Configuración Vía Archivo

**Propuesta**: Externalizar configuración a archivo JSON/YAML.

```bash
# /etc/registro-continuo/config.json
{
  "startup_delay": 5,
  "restart_delay": 3,
  "pid_file": "/var/run/registro_continuo.pid",
  "log_file": "/var/log/registrocontinuo.log",
  "max_startup_wait": 10
}
```

```bash
# En el script
CONFIG_FILE="/etc/registro-continuo/config.json"
STARTUP_DELAY=$(jq -r '.startup_delay' $CONFIG_FILE)
RESTART_DELAY=$(jq -r '.restart_delay' $CONFIG_FILE)
```

---

### 4. Integración con Watchdog

**Propuesta**: Detectar y reiniciar automáticamente si el proceso falla.

```bash
watchdog)
  while true; do
    if ! is_running; then
      echo "[$(date)] Watchdog: Proceso muerto, reiniciando..."
      $0 start
    fi
    sleep 60  # Verificar cada minuto
  done
  ;;
```

**Uso con systemd**:
```ini
[Service]
ExecStart=/home/rsa/scripts/task/registrocontinuo.sh watchdog
Restart=always
```

---

### 5. Modo Dry-Run

**Propuesta**: Simular ejecución sin afectar sistema.

```bash
start)
  if [ "$DRY_RUN" = "1" ]; then
    echo "[DRY-RUN] Ejecutaría: sudo -E registro_continuo &"
    echo "[DRY-RUN] Ejecutaría: sleep 5"
    echo "[DRY-RUN] Ejecutaría: python3 binary_to_mseed.py 1 &"
    echo "[DRY-RUN] Ejecutaría: python3 gestor_archivos_acq.py"
    exit 0
  fi

  # ... código real
  ;;
```

**Uso**:
```bash
DRY_RUN=1 sudo registrocontinuo.sh start
```

---

### 6. Migración a Systemd

**Propuesta**: Reemplazar cron por servicio systemd para gestión más robusta.

**Ventajas sobre cron**:
- Gestión nativa de servicios (start/stop/restart/status)
- Logging integrado con journald (filtrado, rotación automática)
- Reintentos automáticos configurables
- Dependencias explícitas (network, time-sync)
- Monitoreo de estado con systemctl
- Notificaciones de fallo

**Archivo de servicio propuesto**: `/etc/systemd/system/registro-continuo.service`

```ini
[Unit]
Description=Sistema de Registro Continuo de Datos Sismologicos
Documentation=file:///home/rsa/git/montajes/acelerografo/docs/
After=network-online.target time-sync.target
Wants=network-online.target

[Service]
Type=forking
ExecStart=/usr/local/bin/registrocontinuo start
ExecStop=/usr/local/bin/registrocontinuo stop
ExecReload=/usr/local/bin/registrocontinuo restart

# Reintentos automáticos
Restart=on-failure
RestartSec=30
StartLimitInterval=300
StartLimitBurst=5

# Usuario y permisos
User=root
Group=root

# Entorno
EnvironmentFile=-/usr/local/bin/project_paths

# Logging
StandardOutput=journal
StandardError=journal
SyslogIdentifier=registro-continuo

[Install]
WantedBy=multi-user.target
```

**Servicio de reinicio periódico**: `/etc/systemd/system/registro-continuo-restart.timer`

```ini
[Unit]
Description=Reinicio horario del registro continuo
Requires=registro-continuo-restart.service

[Timer]
# Ejecutar cada hora
OnCalendar=hourly
# Ejecutar 2 minutos después del arranque si se perdió
Persistent=true

[Install]
WantedBy=timers.target
```

**Servicio asociado**: `/etc/systemd/system/registro-continuo-restart.service`

```ini
[Unit]
Description=Reinicio del sistema de registro continuo
After=registro-continuo.service

[Service]
Type=oneshot
ExecStart=/usr/local/bin/registrocontinuo restart
```

**Comandos de gestión con systemd**:
```bash
# Habilitar arranque automático
sudo systemctl enable registro-continuo
sudo systemctl enable registro-continuo-restart.timer

# Iniciar servicio
sudo systemctl start registro-continuo

# Ver estado
sudo systemctl status registro-continuo
sudo systemctl list-timers --all | grep registro

# Logs en tiempo real
sudo journalctl -u registro-continuo -f

# Logs desde boot
sudo journalctl -u registro-continuo -b

# Logs de última hora
sudo journalctl -u registro-continuo --since "1 hour ago"

# Reiniciar manualmente
sudo systemctl restart registro-continuo

# Detener
sudo systemctl stop registro-continuo
```

**Transición desde cron**:
```bash
# 1. Deshabilitar cron
sudo crontab -e
# Comentar líneas de registro_continuo

# 2. Instalar servicios systemd
sudo cp registro-continuo.service /etc/systemd/system/
sudo cp registro-continuo-restart.timer /etc/systemd/system/
sudo cp registro-continuo-restart.service /etc/systemd/system/

# 3. Recargar systemd
sudo systemctl daemon-reload

# 4. Habilitar y arrancar
sudo systemctl enable registro-continuo registro-continuo-restart.timer
sudo systemctl start registro-continuo
sudo systemctl start registro-continuo-restart.timer

# 5. Verificar
sudo systemctl status registro-continuo
sudo systemctl list-timers
```

---

## Resumen de Archivos Relacionados

### Scripts de Adquisición (C)
- [registro_continuo_4.5.0.c](../../../scripts/operation/acelerografo/registro_continuo_4.5.0.c): Adquisición continua de datos
- [reset_master](../../../scripts/operation/acelerografo/ejecutables/reset_master): Reset de dsPIC vía GPIO

### Scripts de Procesamiento (Python)
- [binary_to_mseed.py](../../../scripts/operation/mseed/binary_to_mseed.py): Conversión a Mini-SEED
- [gestor_archivos_acq.py](../../../scripts/operation/drive/gestor_archivos_acq.py): Gestión de archivos

### Scripts de Orquestación (Bash)
- [registrocontinuo.sh](../../../scripts/task/registrocontinuo.sh): Este script

### Configuración
- `/usr/local/bin/project_paths`: Variables de entorno
- `configuracion_dispositivo.json`: Configuración del sistema
- [crontab.txt](../../../scripts/task/crontab.txt): Configuración de tareas programadas

---

## Documentos Relacionados

Para entender el contexto completo del sistema:

1. [firmware_context.md](firmware_context.md): Firmware del dsPIC
2. [registro_continuo_context.md](registro_continuo_context.md): Adquisición en RPi
3. [binary_to_mseed_context.md](binary_to_mseed_context.md): Conversión a Mini-SEED
4. [gestor_archivos_acq_context.md](gestor_archivos_acq_context.md): Gestión de archivos
5. [orquestador_rc_context.md](orquestador_rc_context.md): Este documento
6. [CLAUDE.md](../../../CLAUDE.md): Visión general del proyecto

---

**Última actualización**: 2025-11-25

**Estado**: Documentación completa de registrocontinuo.sh (38 líneas Bash) y crontab.txt (configuración de orquestación)

# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is an accelerograph (acelerógrafo) data acquisition and monitoring system for seismic stations. It runs on Raspberry Pi devices, continuously records acceleration data in binary format, converts it to Mini-SEED format, and can upload data to Google Drive. The system supports both online (with internet) and offline modes.

## Environment Setup

The project uses two key environment variables defined in `/etc/profile.d/project_paths.sh`:
- `PROJECT_GIT_ROOT`: Path to the Git repository (e.g., `/home/rsa/git/RSA-Acelerografo`)
- `PROJECT_LOCAL_ROOT`: Path to the deployed project (e.g., `/home/rsa/projects/acelerografo`)

**Important**: Paths in `configuracion_dispositivo.json` must match these environment variables.

## Initial Setup Commands

```bash
# For a new station:
bash menu.sh
# Then select: 0 (environment vars) → 1 (install libs) → 2 (deploy)

# To update existing installation:
git pull
bash menu.sh  # Select option 3
```

## Configuration Files

All configuration files are in JSON format in the `configuration/` directory:
- `configuracion_dispositivo.json`: Device ID, directories, operation mode (online/offline), Drive tokens
- `configuracion_mseed.json`: Station metadata (coordinates, sampling rate, network code, etc.)
- `configuracion_mqtt.json`: MQTT broker settings for event publishing

**Critical**: Always backup configuration files before updates.

## Architecture

### Data Flow
1. **C program** (`registro_continuo`) acquires data from accelerometer via SPI and writes binary files (`.dat`)
2. **Python converter** (`binary_to_mseed.py`) converts binary to Mini-SEED format (`.mseed`)
3. **File manager** (`gestor_archivos_acq.py`) handles uploads/cleanup based on mode:
   - **Online mode**: Uploads `.mseed` files to Google Drive, manages disk space
   - **Offline mode**: Keeps only most recent binary file, deletes old `.mseed` when disk < 10%

### Key Components

**C Programs** (in `scripts/operation/acelerografo/`):
- `registro_continuo_4.5.0.c`: Main data acquisition loop
- `reset_master.c`: Resets the ADC hardware
- `extraer_evento_binario_2.1.1.c`: Extracts event windows from continuous data
- Custom libraries: `detector_eventos.c`, `lector_json.c`

**Python Scripts**:
- `scripts/operation/mseed/binary_to_mseed_2.1.1.py`: Converts binary to Mini-SEED
  - Handles missing samples (gaps), invalid timestamps
  - Supports 3 modes: `--modo rc` (continuous), `--modo ee` (event), `--modo archivo --nombre <file>`
- `scripts/operation/drive/gestor_archivos_acq.py`: File lifecycle manager
- `scripts/operation/mqtt/cliente.py`: MQTT client for status/event publishing

**Task Scripts** (in `scripts/task/`):
- `registrocontinuo.sh`: Service control script (start/stop/restart)
- See `crontab.txt` for scheduled tasks

### Cron Jobs
- Every 5 minutes: Restart continuous recording
- `@reboot`: Reset hardware, upload pending files, start recording

## Build System

The project includes C programs that need compilation:
```bash
# Compile C programs (done automatically by deploy.sh/update.sh)
cd scripts/setup
make -f makefile
```

Executables are placed in `$PROJECT_LOCAL_ROOT/scripts/acelerografo/ejecutables/`.

## Common Operations

### Manual file conversion
```bash
python3 scripts/operation/mseed/binary_to_mseed_2.1.1.py --modo archivo --nombre <filename.dat>
```

### Control continuous recording
```bash
/usr/local/bin/registrocontinuo start|stop|restart
```

### Upload files to Drive
```bash
python3 scripts/operation/drive/subir_archivo.py <filename> <type> <delete_after>
# type: 1=binary, 2=event_mseed, 3=continuous_mseed
# delete_after: 0=keep, 1=delete
```

## Project Structure

- `configuration/`: JSON config files
- `main-libraries/`: bcm2835 and wiringPi for Raspberry Pi GPIO/SPI
- `scripts/`:
  - `env/`: Environment variable definitions
  - `setup/`: `deploy.sh`, `update.sh`, `makefile`
  - `operation/`: Core operational scripts (acelerografo C code, Python converters)
  - `task/`: Cron-scheduled task scripts
  - `dev-tests/`: Development/testing scripts
- `docs/`: README and CHANGELOG
- `menu.sh`: Interactive setup menu

## Logging

All logs are in `$PROJECT_LOCAL_ROOT/log-files/`:
- `drive.log`, `gestor_acq.log`, `mqtt.log`, `mseed.log`, `registro_continuo.log`

Each logger is identified by station ID from `configuracion_dispositivo.json`.

## Important Notes

- The system expects bcm2835 library for SPI communication with the ADC
- Binary data format: 2506-byte frames (2500 bytes data + 6 bytes timestamp)
- Sampling rate typically 250 Hz, 3 channels (X, Y, Z)
- Mini-SEED uses STEIM1 compression, record length 512 bytes

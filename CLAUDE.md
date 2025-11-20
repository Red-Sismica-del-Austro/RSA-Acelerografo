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
  - **New parameters** (optional, have defaults):
    - `umbral_espacio_minimo`: Minimum free disk space threshold for file cleanup
    - `max_reintentos`: Maximum retry attempts for Drive uploads (default: 5)
    - `tiempo_espera`: Wait time between retries in seconds (default: 2)
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
- `scripts/operation/mseed/binary_to_mseed.py` (formerly `binary_to_mseed_2.1.1.py`): Converts binary to Mini-SEED
  - Handles missing samples (gaps), invalid timestamps
  - Supports 3 modes: `--modo rc` (continuous), `--modo ee` (event), `--modo archivo --nombre <file>`
- `scripts/operation/mseed/extract_segment.py`: Extracts temporal segments from Mini-SEED files
  - CLI tool for extracting specific time windows from hourly Mini-SEED files organized by date
  - Uses UTC format exclusively (format: `YYYY-MM-DDZHH:MM:SS.fff`)
  - Automatic file search by date and time range
  - Maintains original filename format in output
  - Supports all available channels and FLOAT32/STEIM2 encodings
- `scripts/operation/drive/gestor_archivos_acq.py`: File lifecycle manager
  - Configurable disk space threshold via `umbral_espacio_minimo` in JSON (default behavior maintained)
  - Configurable retry parameters: `max_reintentos` and `tiempo_espera` in device configuration
  - Enhanced logging with exact free space percentages
  - Fixed socket closure in internet connectivity checks to prevent memory leaks
- `scripts/operation/mqtt/cliente.py`: MQTT client for status/event publishing

**Task Scripts** (in `scripts/task/`):
- `registrocontinuo.sh`: Service control script (start/stop/restart)
- See `crontab.txt` for scheduled tasks

### Cron Jobs
- Every 60 minutes: Restart continuous recording
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
python3 scripts/operation/mseed/binary_to_mseed.py --modo archivo --nombre <filename.dat>
```

### Extract temporal segments from Mini-SEED files
```bash
python3 scripts/operation/mseed/extract_segment.py --start "2024-01-15Z14:30:45.250" --duration 60
# Extracts 60 seconds starting from the specified UTC time
# Note: Time format must use UTC (Z) format: YYYY-MM-DDZHH:MM:SS.fff
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

## Recent Updates

### Security and Deployment Improvements (Nov 2025)
- `deploy.sh` now includes strict error handling (`set -euo pipefail`)
- Environment variable validation added to prevent partial installations
- Fixed critical permissions issue: log files now have correct ownership after deployment
- Removed wildcards in Python script copying for better precision
- `extract_segment.py` added to deployment process

### File Management Enhancements (Nov 2025)
- `gestor_archivos_acq.py` now supports configurable parameters via JSON
- Enhanced logging with detailed space usage information
- Memory leak fix: proper socket closure in connectivity checks
- Better error handling with stdout/stderr capture in subprocesses

### New Tool: extract_segment.py (Nov 2025)
- Added CLI tool for extracting temporal segments from Mini-SEED archives
- Uses UTC-only time format for consistency (no local time conversions)
- Automatically searches files by date and time range
- Supports PROJECT_LOCAL_ROOT environment variable for portability

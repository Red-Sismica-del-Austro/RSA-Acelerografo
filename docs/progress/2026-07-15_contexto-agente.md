# Resumen de Sesión: Corrección de autenticación MQTT y desajuste de tópicos jerárquicos en el Worker GPD

**Fecha**: 2026-07-15  
**Repositorio**: `acelerografo-DEV00`  
**Agente de IA**: Antigravity (Google DeepMind)  
**Usuario**: Milton / RSA  

---

## 🎯 Objetivo de la Sesión
Resolver el problema por el cual el worker de inferencia GPD en tiempo real (`gpd_stream_worker.py`) no publicaba detecciones en el broker MQTT en modo `online`. Se buscaba asegurar que el coordinador de eventos (`mqtt_coordinator.py`) interceptara las alertas y ejecutara el pipeline de extracción y carga asíncrona a Google Drive de forma automática.

---

## 📂 Archivos Modificados

```text
montajes/acelerografo-DEV00/
│
└── scripts/operation/streaming/
    └── gpd_stream_worker.py        [MODIFICADO] Carga de .env, autenticación MQTT, station_id y prefijo de tópicos RSA
```

---

## 🛠️ Diagnóstico y Modificaciones Realizadas

Se identificaron y corrigieron cuatro omisiones críticas en el diseño original del worker de GPD que impedían la comunicación:

### 1. Falta de Autenticación y Credenciales MQTT
* **Problema**: El broker MQTT institucional requiere usuario y contraseña. Sin embargo, `gpd_stream_worker.py` instanciaba y conectaba el cliente Paho-MQTT de forma anónima, lo que causaba un rechazo silencioso de la conexión (`self._mqtt = None`).
* **Solución**: Se actualizó `_conectar_mqtt()` para admitir credenciales mediante `self._mqtt.username_pw_set(username, password)`. Para asegurar la compatibilidad entre Paho-MQTT v1.x y v2.x, se implementó una instanciación robusta utilizando `CallbackAPIVersion.VERSION2` con fallback automático.

### 2. Ausencia de Carga de Variables del `.env`
* **Problema**: El worker no cargaba el archivo `.env` de red de la estación, por lo que hacía fallback por defecto al host `localhost` en el puerto `1883`, perdiendo de vista la IP externa del broker real.
* **Solución**: Se integró la librería `dotenv` en `main()`, localizando y cargando automáticamente el archivo de configuración `.env` del dispositivo local (`configuracion/.env`).

### 3. Resolución Incorrecta de `station_id` (UNKNOWN)
* **Problema**: Al arrancar, el script intentaba leer el ID del dispositivo del primer nivel del JSON (`full_config.get("id")`), pero en la estructura generada por el orquestador este campo se encuentra anidado. Esto dejaba la estación como `"UNKNOWN"`.
* **Solución**: Se corrigió el parsing apuntando a la ruta anidada:
  ```python
  station_id = args.station or full_config.get("dispositivo", {}).get("id", "UNKNOWN")
  ```

### 4. Desajuste en la Estructura de Tópicos (Topic Mismatch)
* **Problema**: El worker publicaba en el tópico simplificado `{station_id}/events/detected` (ej: `DEV0/events/detected`). En contraste, `mqtt_coordinator.py` se suscribía al tópico institucional estructurado de RSA (`rsa/seismic/smart/DEV0/events/detected`), lo que imposibilitaba que el coordinador recibiera los avisos y causaba un fallo por índice (`IndexError`) al procesar la ruta del canal.
* **Solución**: Se configuró a `main()` para leer dinámicamente el archivo `configuracion_mqtt.json` y extraer el prefijo institucional de RSA (`org`, `app` y `cap`). Con esto, el worker ahora compone y publica el tópico en el formato jerárquico reglamentario de la Red Sísmica del Austro:
  `{org}/{app}/{cap}/{station_id}/events/detected`

---

## 📊 Resultados de la Validación en Caliente

Tras aplicar los cambios y realizar el despliegue (`update.sh` y reinicio del servicio de Supervisor `gpd_worker`), se constató el correcto funcionamiento del pipeline:

1. **Conexión Exitosa**: El log de inicio del worker confirmó el enlace seguro con el broker remoto:
   `[GPD_MQTT] Conectado al broker 174.138.41.251:1883 (client_id=gpd_worker_DEV0_17427).`
2. **Publicación y Consumo**: Al detectarse una fase **S** con probabilidad `0.9706`, el mensaje se envió exitosamente a:
   `rsa/seismic/smart/DEV0/events/detected`
3. **Extracción y Carga**: `mqtt_coordinator` interceptó la alarma, calculó las ventanas de tiempo e invocó asíncronamente a `event_extractor.py`. El sismo fue recortado en el archivo miniSEED `DEV0_20260713_215813.mseed`, subido a Google Drive (`"uploaded": true`) y confirmado en el registro CSV local como `confirmado=True`.
4. **Respuesta en Red**: El flujo terminó notificando el estado `completed` con origen `gpd_auto` en el canal de control:
   `rsa/seismic/smart/DEV0/cmd/extract_event/res`

---

## 📋 Recomendaciones para la Siguiente Sesión
* Monitorear la estabilidad y consumo de memoria del proceso de Supervisor `gpd_worker` de forma rutinaria.
* Comprobar que no ocurran cuellos de botella en la subida a Drive en caso de sismos o detecciones múltiples muy consecutivas.

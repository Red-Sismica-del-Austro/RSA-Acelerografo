#!/usr/bin/env python
"""
GPD con procesamiento por chunks para manejar archivos grandes
Uso: time python gpd_chunked_tflite.py -I anza2016.in -O anza2016_tflite.out -V --hours 4
 
"""

import os

os.environ["OPENBLAS_NUM_THREADS"] = "1"
os.environ["OMP_NUM_THREADS"] = "1"
os.environ["NUMEXPR_NUM_THREADS"] = "1"
#os.environ["TF_LITE_DISABLE_XNNPACK"] = "1"

import numpy as np
import obspy.core as oc
import argparse
import gc
from tflite_runtime.interpreter import Interpreter
import time

# Configuración
min_proba = 0.95
freq_min = 3.0
freq_max = 20.0
filter_data = True
decimate_data = False
n_shift = 10
n_gpu = 0
batch_size = 100

half_dur = 2.00
only_dt = 0.01
n_win = int(half_dur/only_dt)
n_feat = 2*n_win

# Tamaño de chunk (muestras por chunk)
CHUNK_SIZE = 100000  # ~16.7 minutos a 100 Hz
OVERLAP_SIZE = 8000  # Overlap para evitar perder eventos en los bordes

# Acceso global desde process_chunk
interpreter = None
inp = None
out = None

# Métricas globales
inf_time_s = 0.0       # tiempo total de invoke()
set_time_s = 0.0       # tiempo total de set_tensor/copia al intérprete
pre_time_s = 0.0       # tiempo total de preprocesado (ventaneo+normalización)
windows_inf = 0        # nº total de ventanas inferidas (válidas)
batches_inf = 0        # nº de batches ejecutados

def sliding_window(data, size, stepsize=1, padded=False, axis=-1, copy=True):
    """Función sliding window original"""
    if axis >= data.ndim:
        raise ValueError("Axis value out of range")
    if stepsize < 1:
        raise ValueError("Stepsize may not be zero or negative")
    if size > data.shape[axis]:
        raise ValueError("Sliding window size may not exceed size of selected axis")

    shape = list(data.shape)
    shape[axis] = np.floor(data.shape[axis] / stepsize - size / stepsize + 1).astype(int)
    shape.append(size)

    strides = list(data.strides)
    strides[axis] *= stepsize
    strides.append(data.strides[axis])

    strided = np.lib.stride_tricks.as_strided(data, shape=shape, strides=strides)
    return strided.copy() if copy else strided

def process_chunk(chunk_data, chunk_start_time, dt, net, sta, output_file):
    """Procesar un chunk de datos y escribir picks (versión estable para TFLite en Pi)."""
    global interpreter, inp, out
    global inf_time_s, set_time_s, pre_time_s, windows_inf, batches_inf

    picks_found = {'P': 0, 'S': 0}

    try:

        # --- Toma de tiempo: PREPROCESADO ---
        t0_pre = time.perf_counter()

        # 1) Ventanas deslizantes (NEZ)
        tt = (np.arange(0, chunk_data[0].size, n_shift) + n_win) * dt

        sliding_N = sliding_window(chunk_data[0], n_feat, stepsize=n_shift)
        sliding_E = sliding_window(chunk_data[1], n_feat, stepsize=n_shift)
        sliding_Z = sliding_window(chunk_data[2], n_feat, stepsize=n_shift)

        # 2) Alinear número de ventanas
        min_windows = min(sliding_N.shape[0], sliding_E.shape[0], sliding_Z.shape[0])
        if min_windows == 0:
            return picks_found

        # 3) Apilar y normalizar por canal (por ventana)
        tr_win = np.zeros((min_windows, n_feat, 3), dtype=np.float32)
        tr_win[:, :, 0] = sliding_N[:min_windows]
        tr_win[:, :, 1] = sliding_E[:min_windows]
        tr_win[:, :, 2] = sliding_Z[:min_windows]

        max_vals = np.max(np.abs(tr_win), axis=1, keepdims=True) + 1e-9  # (B,1,3)
        tr_win = tr_win / max_vals

        tt = tt[:min_windows]  # tiempos alineados a min_windows

        # acumular tiempo de preprocesado
        pre_time_s += (time.perf_counter() - t0_pre)

        # 4) Inferencia por batches de tamaño fijo (sin redimensionar el intérprete)
        batch_size_fixed = int(inp["shape"][0])  # fijado previamente en main()
        pad_buf = np.zeros((batch_size_fixed, n_feat, 3), dtype=np.float32)

        ts_list = []
        i = 0
        while i < min_windows:
            k = min(batch_size_fixed, min_windows - i)

            # Rellenar el buffer de batch; resto queda en cero
            pad_buf.fill(0.0)
            # Asegurar float32 y contigüidad C para TFLite
            pad_buf[:k] = np.asarray(tr_win[i:i + k], dtype=np.float32, order="C")           

            # Ejecutar TFLite
            # --- Toma de tiempo: copia/set_tensor ---
            t0_set = time.perf_counter()
            interpreter.set_tensor(inp["index"], pad_buf)
            set_time_s += (time.perf_counter() - t0_set)

            # --- Toma de tiempo: INFERENCIA pura ---
            t0_inf = time.perf_counter()
            interpreter.invoke()
            inf_time_s += (time.perf_counter() - t0_inf)

            ts_full = interpreter.get_tensor(out["index"])  # (batch_size_fixed, 3)
            ts_list.append(ts_full[:k])  # recortar a k válidos

            windows_inf += k
            batches_inf += 1

            i += k

        # Unir todos los batches: shape (min_windows, 3)
        ts = np.concatenate(ts_list, axis=0)

        # 5) Detección por umbral con histeresis
        from obspy.signal.trigger import trigger_onset

        prob_P = ts[:, 0]
        prob_S = ts[:, 1]

        # Picks P
        trigs = trigger_onset(prob_P, min_proba, 0.1)
        for trig in trigs:
            if trig[1] == trig[0]:
                continue
            pick = np.argmax(prob_P[trig[0]:trig[1]]) + trig[0]
            stamp_pick = chunk_start_time + tt[pick]
            output_file.write(f"{net} {sta} P {stamp_pick.isoformat()}\n")
            picks_found['P'] += 1

        # Picks S
        trigs = trigger_onset(prob_S, min_proba, 0.1)
        for trig in trigs:
            if trig[1] == trig[0]:
                continue
            pick = np.argmax(prob_S[trig[0]:trig[1]]) + trig[0]
            stamp_pick = chunk_start_time + tt[pick]
            output_file.write(f"{net} {sta} S {stamp_pick.isoformat()}\n")
            picks_found['S'] += 1

        # 6) Limpieza
        del tr_win, ts, ts_list, sliding_N, sliding_E, sliding_Z
        gc.collect()

    except Exception as e:
        print(f"ERROR procesando chunk: {e}")

    return picks_found


def main():

    global interpreter, inp, out
    global inf_time_s, set_time_s, pre_time_s, windows_inf, batches_inf

    parser = argparse.ArgumentParser(description='GPD con procesamiento por chunks')
    parser.add_argument('-I', type=str, required=True, help='Input file')
    parser.add_argument('-O', type=str, required=True, help='Output file')
    parser.add_argument('-V', action='store_true', help='Verbose')
    parser.add_argument('--chunk-size', type=int, default=CHUNK_SIZE, 
                       help='Tamaño de chunk en muestras')
    parser.add_argument('--hours', type=float, default=None,
                       help='Horas a procesar desde el inicio sincronizado (por defecto: todo el archivo)')
    
    args = parser.parse_args()
    
    print("=== GPD Procesamiento por Chunks ===")
    
    # Leer archivo de entrada
    fdir = []
    with open(args.I) as f:
        for line in f:
            tmp = line.split()
            fdir.append([tmp[0], tmp[1], tmp[2]])
    
    print(f"Número de estaciones: {len(fdir)}")
    
    # Cargar modelo TFLite
    print("Cargando modelo TFLite...")
    interpreter = Interpreter(model_path="gpd_v2.tflite", num_threads=2)  
    # 1) Primera alloc para poder consultar detalles
    interpreter.allocate_tensors()
    inp = interpreter.get_input_details()[0]
    out = interpreter.get_output_details()[0]
    # 2) Ajustar el tensor de entrada al batch_size efectivo
    interpreter.resize_tensor_input(inp["index"], [batch_size, 400, 3])
    # 3) Re-alloc DESPUÉS del resize y refrescar detalles (a las MISMAS globales)
    interpreter.allocate_tensors()
    inp = interpreter.get_input_details()[0]
    out = interpreter.get_output_details()[0]

    print(f"input_shape={inp['shape']}, output_shape={out['shape']}")

    
    # Procesar cada estación
    total_picks = {'P': 0, 'S': 0}
    
    with open(args.O, 'w') as ofile:
        for i, files in enumerate(fdir):
            print(f"\n--- Estación {i+1}/{len(fdir)} ---")
            
            # Verificar archivos
            if not all(os.path.isfile(f) for f in files):
                print("ERROR: Archivos faltantes, saltando estación")
                continue
            
            try:
                # Cargar todas las trazas
                print("Cargando trazas completas...")
                st = oc.Stream()
                st += oc.read(files[0])
                st += oc.read(files[1])
                st += oc.read(files[2])
                
                # Sincronizar
                latest_start = np.max([x.stats.starttime for x in st])
                earliest_stop = np.min([x.stats.endtime for x in st])
                st.trim(latest_start, earliest_stop)

                # Opcional: Asegurar 100 Hz para el modelo
                #for tr in st:
                #    if abs(tr.stats.sampling_rate - 100.0) > 1e-3:
                #        tr.resample(100.0)

                # Limitar duracion si --hours fue indicado
                if args.hours is not None:
                    end_limit = latest_start + args.hours * 3600.0
                    # No pasar del fin real
                    stop_time = min(earliest_stop, end_limit)
                    st.trim(latest_start, stop_time)
                    dur_h = float(st[0].stats.endtime - st[0].stats.starttime) / 3600.0
                    print(f"Duracion analizada: {dur_h:.2f} h")
                
                total_samples = len(st[0].data)
                duration_hours = total_samples / st[0].stats.sampling_rate / 3600
                
                print(f"Muestras totales: {total_samples:,}")
                print(f"Duración: {duration_hours:.1f} horas")
                print(f"Chunks necesarios: {(total_samples + args.chunk_size - 1) // args.chunk_size}")
                
                # Preprocesamiento global
                st.detrend(type='linear')
                if filter_data:
                    st.filter(type='bandpass', freqmin=freq_min, freqmax=freq_max)
                if decimate_data:
                    st.interpolate(100.0)
                
                dt = st[0].stats.delta
                net = st[0].stats.network
                sta = st[0].stats.station
                start_time = st[0].stats.starttime
                
                # Procesar por chunks
                chunk_num = 0
                start_idx = 0
                station_picks = {'P': 0, 'S': 0}
                
                while start_idx < total_samples:
                    chunk_num += 1
                    end_idx = min(start_idx + args.chunk_size, total_samples)
                    
                    if args.V:
                        print(f"  Chunk {chunk_num}: muestras {start_idx}-{end_idx}")
                    
                    # Extraer chunk con overlap
                    chunk_data = []
                    for trace in st:
                        chunk_data.append(trace.data[start_idx:end_idx])
                    
                    # Tiempo de inicio del chunk
                    chunk_start_time = start_time + start_idx * dt
                    
                    # Procesar chunk
                    chunk_picks = process_chunk(chunk_data, chunk_start_time, dt, net, sta, ofile)
                    
                    station_picks['P'] += chunk_picks['P']
                    station_picks['S'] += chunk_picks['S']
                    
                    if args.V:
                        print(f"    Picks encontrados: P={chunk_picks['P']}, S={chunk_picks['S']}")
                    
                    # Siguiente chunk con overlap
                    start_idx += args.chunk_size - OVERLAP_SIZE
                    if start_idx >= total_samples - OVERLAP_SIZE:
                        break
                
                print(f"Total estación: P={station_picks['P']}, S={station_picks['S']}")
                total_picks['P'] += station_picks['P']
                total_picks['S'] += station_picks['S']
                
            except Exception as e:
                print(f"ERROR procesando estación: {e}")
                continue
    
    print(f"\n=== Procesamiento completado ===")
    print(f"Total de picks: P={total_picks['P']}, S={total_picks['S']}")
    print(f"Resultados en: {args.O}")

    # ... tras el loop principal ...
    print("\n=== Métricas de tiempo ===")
    if windows_inf > 0:
        ms_por_vent_inf = (inf_time_s / windows_inf) * 1000.0
        ms_por_vent_set = (set_time_s / windows_inf) * 1000.0
        vent_por_seg = windows_inf / max(inf_time_s, 1e-9)
        print(f"Inferencia (invoke): {inf_time_s:.3f}s  | {ms_por_vent_inf:.3f} ms/ventana  | {vent_por_seg:.1f} vent/s")
        print(f"Copia/set_tensor   : {set_time_s:.3f}s  | {ms_por_vent_set:.3f} ms/ventana")
        print(f"Batches ejecutados : {batches_inf}")
    else:
        print("No se infirieron ventanas (windows_inf=0).")
    print(f"Preprocesado total : {pre_time_s:.3f}s")

if __name__ == "__main__":
    main()
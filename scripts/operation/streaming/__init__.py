"""
Paquete streaming: sistema de buffering continuo en disco para el acelerógrafo RSA.

Módulos:
    ring_buffer_store: Almacén rotativo de tramas binarias con consulta por rango temporal.
    stream_processor:  Servicio daemon que lee el named pipe y alimenta el ring buffer.
"""

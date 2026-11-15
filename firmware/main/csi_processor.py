import socket
import numpy as np
import threading
import time
from scipy.signal import butter, filtfilt, find_peaks

UDP_PORT_RX = 5556
FS = 100
BUFFER_SEC = 5
BUFFER_SIZE = FS * BUFFER_SEC

# Dicionários para tratar as 3 placas de forma isolada
esp_buffers = {}
esp_pacotes = {}

def gerador_de_trafego_broadcast():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    payload = b'PING_CSI'
    print("\n[REDE] Injetando tráfego Broadcast (100Hz) para todos os ESP32 da rede...")
    while True:
        try:
            # Envia para a sub-rede inteira. Substitua se o IP do hotspot mudar.
            sock.sendto(payload, ('192.168.137.255', 5555))
            time.sleep(0.01)
        except:
            time.sleep(1)

def bandpass_filter(data, lowcut, highcut, fs, order=3):
    if fs <= 2 * highcut: return data
    nyq = 0.5 * fs
    b, a = butter(order, [lowcut/nyq, highcut/nyq], btype='band')
    return filtfilt(b, a, data)

def main():
    print("Iniciando Receptor CSI Multi-Sensores (UDP)...")
    threading.Thread(target=gerador_de_trafego_broadcast, daemon=True).start()
    
    sock_rx = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock_rx.bind(("0.0.0.0", UDP_PORT_RX))
    
    print(f"Escutando porta UDP {UDP_PORT_RX}. Aguardando dados das placas...\n")
    
    while True:
        data, addr = sock_rx.recvfrom(1024)
        ip = addr[0]
        
        try:
            amp = float(data.decode('utf-8').strip())
            
            # Se for uma placa nova, inicializa a onda matemática dela
            if ip not in esp_buffers:
                esp_buffers[ip] = []
                esp_pacotes[ip] = 0
                print(f"[NOVA PLACA] ESP32 conectado com o IP: {ip}")
                
            esp_buffers[ip].append(amp)
            esp_pacotes[ip] += 1
            
            if len(esp_buffers[ip]) > BUFFER_SIZE:
                esp_buffers[ip].pop(0)
                
                # Processa os filtros de cada placa no seu próprio tempo
                if esp_pacotes[ip] % 50 == 0: # Atualiza a tela a cada 0.5s por placa
                    data_array = np.array(esp_buffers[ip])
                    variance = np.var(data_array)
                    
                    if variance > 10.0:
                        print(f"[{ip}] MOVIMENTO DETECTADO (Var: {variance:.2f})")
                    else:
                        resp = bandpass_filter(data_array, 0.2, 0.5, FS)
                        rpks, _ = find_peaks(resp)
                        rpm = len(rpks) * (60 / BUFFER_SEC)
                        
                        hrt = bandpass_filter(data_array, 0.8, 2.0, FS)
                        hpks, _ = find_peaks(hrt)
                        bpm = len(hpks) * (60 / BUFFER_SEC)
                        
                        print(f"[{ip}] Pulmão: {rpm:.1f} RPM | Coração: {bpm:.1f} BPM (Var: {variance:.2f})")
                        
        except Exception:
            pass

if __name__ == '__main__':
    main()
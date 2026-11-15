import socket
import numpy as np
import threading
import time
from scipy.signal import butter, filtfilt, find_peaks

UDP_PORT_RX = 5556
FS = 100
BUFFER_SEC = 5
BUFFER_SIZE = FS * BUFFER_SEC

# Dicionários para tratar as placas de forma isolada
esp_buffers = {}
esp_pacotes = {}

# Novo dicionário para guardar o último estado de cada placa e fazer a média
ultima_leitura = {} 

def gerador_de_trafego_broadcast():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    payload = b'PING_CSI'
    print("\n[REDE] Injetando tráfego Broadcast (100Hz) para todos os ESP32 da rede...")
    while True:
        try:
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
    sock_rx.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock_rx.bind(("0.0.0.0", UDP_PORT_RX))
    
    print(f"Escutando porta UDP {UDP_PORT_RX}. Aguardando dados das placas...\n")
    
    while True:
        data, addr = sock_rx.recvfrom(1024)
        ip = addr[0]
        
        try:
            amp = float(data.decode('utf-8').strip())
            
            # Inicializa uma placa nova quando ela aparece na rede pela primeira vez
            if ip not in esp_buffers:
                esp_buffers[ip] = []
                esp_pacotes[ip] = 0
                ultima_leitura[ip] = {'rpm': 0, 'bpm': 0, 'valido': False}
                print(f"[NOVA PLACA] ESP32 conectado com o IP: {ip}")
                
            esp_buffers[ip].append(amp)
            esp_pacotes[ip] += 1
            
            # Quando a placa atinge 500 pacotes (5 segundos), começa o processamento contínuo
            if len(esp_buffers[ip]) > BUFFER_SIZE:
                esp_buffers[ip].pop(0)
                
                # A cada 50 pacotes (0.5 segundos) da placa atual, atualiza a tela
                if esp_pacotes[ip] % 50 == 0: 
                    data_array = np.array(esp_buffers[ip])
                    variance = np.var(data_array)
                    
                    # 1. Avalia o status INDIVIDUAL da placa
                    if variance > 10.0:
                        print(f"[{ip}] MOVIMENTO DETECTADO (Var: {variance:.2f})")
                        ultima_leitura[ip]['valido'] = False # Remove da média
                    else:
                        resp = bandpass_filter(data_array, 0.2, 0.5, FS)
                        rpks, _ = find_peaks(resp)
                        rpm = len(rpks) * (60 / BUFFER_SEC)
                        
                        hrt = bandpass_filter(data_array, 0.8, 2.0, FS)
                        hpks, _ = find_peaks(hrt)
                        bpm = len(hpks) * (60 / BUFFER_SEC)
                        
                        print(f"[{ip}] Pulmão: {rpm:.1f} RPM | Coração: {bpm:.1f} BPM (Var: {variance:.2f})")
                        
                        # Salva os dados para o cálculo da média
                        ultima_leitura[ip]['rpm'] = rpm
                        ultima_leitura[ip]['bpm'] = bpm
                        ultima_leitura[ip]['valido'] = True
                    
                    # 2. CALCULA A MÉDIA GERAL (Apenas com as placas Válidas)
                    rpms_validos = [info['rpm'] for info in ultima_leitura.values() if info['valido']]
                    bpms_validos = [info['bpm'] for info in ultima_leitura.values() if info['valido']]
                    
                    if len(rpms_validos) > 0:
                        media_rpm = sum(rpms_validos) / len(rpms_validos)
                        media_bpm = sum(bpms_validos) / len(bpms_validos)
                        print(f" => [MÉDIA GLOBAL] Pulmão: {media_rpm:.1f} RPM | Coração: {media_bpm:.1f} BPM (Baseado em {len(rpms_validos)}/{len(ultima_leitura)} sensores)\n")
                    else:
                        print(f" => [MÉDIA GLOBAL] Aguardando leitura estável (0/{len(ultima_leitura)} sensores)\n")
                        
        except Exception:
            pass

if __name__ == '__main__':
    main()
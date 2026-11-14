import serial
import numpy as np
import sys
from scipy.signal import butter, filtfilt, find_peaks

# --- CONFIGURAÇÕES ---
PORT = 'COM10'
BAUD = 921600
FS = 100             
BUFFER_SEC = 5       
BUFFER_SIZE = FS * BUFFER_SEC

def bandpass_filter(data, lowcut, highcut, fs, order=3):
    nyq = 0.5 * fs
    low = lowcut / nyq
    high = highcut / nyq
    b, a = butter(order, [low, high], btype='band')
    return filtfilt(b, a, data)

def main():
    print(f"Iniciando leitura CSI na porta {PORT} a {BAUD} bps...")
    amplitude_buffer = []
    pacotes_recebidos = 0

    try:
        # Configuração separada para evitar o travamento do ESP32 (DTR/RTS)
        ser = serial.Serial()
        ser.port = PORT
        ser.baudrate = BAUD
        ser.timeout = 1
        ser.setDTR(False) # Libera o ESP32 do modo de gravação
        ser.setRTS(False) # Libera o ESP32 do modo de reset
        ser.open()
        
        print("Porta aberta com sucesso. Aguardando dados...")

        while True:
            raw_bytes = ser.readline()
            if not raw_bytes:
                continue
                
            line = raw_bytes.decode('utf-8', errors='ignore').strip()
            
            if line.startswith("CSI_DATA"):
                pacotes_recebidos += 1
                parts = line.split(',"')
                if len(parts) == 2:
                    data_str = parts[1].strip(']"')
                    try:
                        csi_values = np.fromstring(data_str, sep=',', dtype=float)
                        I = csi_values[0::2]
                        Q = csi_values[1::2]
                        amp = np.mean(np.sqrt(I**2 + Q**2))
                        amplitude_buffer.append(amp)
                        
                        if len(amplitude_buffer) < BUFFER_SIZE:
                            sys.stdout.write(f"\rColetando dados iniciais: {len(amplitude_buffer)}/{BUFFER_SIZE} pacotes... ")
                            sys.stdout.flush()
                        else:
                            amplitude_buffer.pop(0)
                            if pacotes_recebidos % 20 == 0:
                                data_array = np.array(amplitude_buffer)
                                variance = np.var(data_array)
                                
                                if variance > 10.0:
                                    msg = f"[STATUS] MOVIMENTO DETECTADO (Variância: {variance:.2f})                    "
                                else:
                                    resp_signal = bandpass_filter(data_array, 0.2, 0.5, FS)
                                    resp_peaks, _ = find_peaks(resp_signal)
                                    rpm = len(resp_peaks) * (60 / BUFFER_SEC)
                                    
                                    heart_signal = bandpass_filter(data_array, 0.8, 2.0, FS)
                                    heart_peaks, _ = find_peaks(heart_signal)
                                    bpm = len(heart_peaks) * (60 / BUFFER_SEC)
                                    
                                    msg = f"[STATUS] PARADO | Pulmão: {rpm:.1f} RPM | Coração: {bpm:.1f} BPM (Var: {variance:.2f})  "
                                
                                sys.stdout.write(f"\r{msg}")
                                sys.stdout.flush()
                    except ValueError:
                        pass
            elif line:
                # Se não for dado CSI, imprime o log do ESP32 para diagnóstico
                # Isso vai sumir automaticamente quando os dados CSI começarem
                print(f"[ESP32 LOG] {line}")
                
    except serial.SerialException as e:
        print(f"\nErro na porta serial: {e}")
    except KeyboardInterrupt:
        print("\nLeitura encerrada pelo usuário.")
    finally:
        if 'ser' in locals() and ser.is_open:
            ser.close()

if __name__ == "__main__":
    main()
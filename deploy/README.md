# deploy/ — Configuração da Estação Orange Pi 4 Pro

**Responsável:** Leonardo (M4), com revisão de Selliny (M1), Nicolas (M2), Rafael (M3), Santiago/Leonardo (M5).

## Propósito
Arquivos de configuração do sistema operacional (`linux/arm64`) para transformar a Orange Pi 4 Pro em uma estação isolada 100% offline.

## Conteúdo esperado
| Item | Função |
| :--- | :--- |
| `hostapd/` | AP Wi-Fi local: rádio 2.4 GHz fixo no **canal 6 HT20** para o cluster ESP32-S3; rádio 5 GHz separado para tablet e câmera sob demanda |
| `dnsmasq/` | DHCP local estático (`10.42.0.1` Central; faixa para os 5 ESP32-S3 e tablet), sem upstream DNS |
| `nftables/` | Firewall: bloqueia qualquer tráfego WAN/internet; libera apenas `:5005/udp` e `:8000/tcp` na LAN; restringe `:5006/tcp` a `127.0.0.1` |
| `systemd/` | `edgespace-central.service` e `edgespace-ai.service` com restart automático, limites de recursos e ordem de boot |

## Regras
- Nenhuma dependência de NTP externo (usar RTC local da estação).
- Script de instalação idempotente e documentado.

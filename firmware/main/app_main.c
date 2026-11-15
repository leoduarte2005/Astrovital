#include <stdio.h>
#include <string.h>
#include <math.h>
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "freertos/queue.h"
#include "nvs_flash.h"
#include "esp_mac.h"
#include "esp_log.h"
#include "esp_wifi.h"
#include "esp_netif.h"
#include "lwip/sockets.h"
#include "protocol_examples_common.h"
#include "esp_csi_gain_ctrl.h"

#define CSI_QUEUE_SIZE 50
#define UDP_PORT 5556

typedef struct {
    wifi_pkt_rx_ctrl_t rx_ctrl;
    uint8_t mac[6];
    int len;
    int first_word_invalid;
    int8_t buf[384]; 
} csi_data_t;

static QueueHandle_t csi_queue;
static const char *TAG = "csi_udp_edge";

// =========================================================================
// TASK CORE 1: Transmissor UDP Sem Fio
// =========================================================================
void csi_udp_task(void *pvParameters) {
    csi_data_t data;
    
    // Configura o Socket UDP
    int sock = socket(AF_INET, SOCK_DGRAM, IPPROTO_IP);
    struct sockaddr_in dest_addr;
    dest_addr.sin_family = AF_INET;
    dest_addr.sin_port = htons(UDP_PORT);
    
    // Pega o IP do seu Computador (Gateway do Hotspot) automaticamente
    esp_netif_ip_info_t ip_info;
    esp_netif_get_ip_info(esp_netif_get_handle_from_ifkey("WIFI_STA_DEF"), &ip_info);
    dest_addr.sin_addr.s_addr = ip_info.gw.addr; 
    
    ESP_LOGI(TAG, "Task UDP Sem Fio iniciada! Enviando dados para o PC...");

    while (1) {
        if (xQueueReceive(csi_queue, &data, portMAX_DELAY)) {
            float compensate_gain = 1.0f;
            uint8_t agc_gain = 0;
            int8_t fft_gain = 0;
            
            esp_csi_gain_ctrl_get_rx_gain(&data.rx_ctrl, &agc_gain, &fft_gain);
            esp_csi_gain_ctrl_get_gain_compensation(&compensate_gain, agc_gain, fft_gain);

            float total_amp = 0;
            int subcarriers = 0;
            
            for (int i = 0; i < data.len - 1; i += 2) {
                float I = data.buf[i] * compensate_gain;
                float Q = data.buf[i+1] * compensate_gain;
                total_amp += sqrt((I * I) + (Q * Q));
                subcarriers++;
            }
            float amp_media = total_amp / subcarriers;

            // Envia a Amplitude formatada para o Python via Wi-Fi
            char payload[32];
            int len = snprintf(payload, sizeof(payload), "%.2f", amp_media);
            sendto(sock, payload, len, 0, (struct sockaddr *)&dest_addr, sizeof(dest_addr));
        }
    }
}

// =========================================================================
// CALLBACK DO CORE 0
// =========================================================================
static void wifi_csi_rx_cb(void *ctx, wifi_csi_info_t *info) {
    if (!info || !info->buf || !csi_queue) return;
    if (memcmp(info->mac, ctx, 6)) return;

    csi_data_t data;
    memcpy(&data.rx_ctrl, &info->rx_ctrl, sizeof(wifi_pkt_rx_ctrl_t));
    memcpy(data.mac, info->mac, 6);
    data.len = info->len > 384 ? 384 : info->len;
    data.first_word_invalid = info->first_word_invalid;
    memcpy(data.buf, info->buf, data.len);

    xQueueSendFromISR(csi_queue, &data, NULL);
}

static void wifi_csi_init() {
    wifi_csi_config_t csi_config = {
        .lltf_en           = true,
        .htltf_en          = false,
        .stbc_htltf2_en    = false,
        .ltf_merge_en      = true,
        .channel_filter_en = true,
        .manu_scale        = true,
        .shift             = true,
    };
    static wifi_ap_record_t s_ap_info = {0};
    ESP_ERROR_CHECK(esp_wifi_sta_get_ap_info(&s_ap_info));
    ESP_ERROR_CHECK(esp_wifi_set_csi_config(&csi_config));
    ESP_ERROR_CHECK(esp_wifi_set_csi_rx_cb(wifi_csi_rx_cb, s_ap_info.bssid));
    ESP_ERROR_CHECK(esp_wifi_set_csi(true));
}

void app_main() {
    ESP_ERROR_CHECK(nvs_flash_init());
    ESP_ERROR_CHECK(esp_netif_init());
    ESP_ERROR_CHECK(esp_event_loop_create_default());

    ESP_ERROR_CHECK(example_connect());
    ESP_ERROR_CHECK(esp_wifi_set_ps(WIFI_PS_NONE));

    csi_queue = xQueueCreate(CSI_QUEUE_SIZE, sizeof(csi_data_t));
    xTaskCreatePinnedToCore(csi_udp_task, "csi_udp", 8192, NULL, 5, NULL, 1);

    wifi_csi_init();
}
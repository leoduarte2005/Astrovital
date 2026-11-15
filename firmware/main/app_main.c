#include "edgespace_proto.h"

#include "esp_log.h"
#include "esp_mac.h"
#include "esp_netif.h"
#include "esp_wifi.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "nvs_flash.h"
#include "protocol_examples_common.h"

static const char *TAG = "es_main";

void app_main(void) {
    ESP_ERROR_CHECK(nvs_flash_init());
    ESP_ERROR_CHECK(esp_netif_init());
    ESP_ERROR_CHECK(esp_event_loop_create_default());

    ESP_ERROR_CHECK(example_connect());
    ESP_ERROR_CHECK(esp_wifi_set_ps(WIFI_PS_NONE));
    (void)esp_wifi_set_bandwidth(WIFI_IF_STA, WIFI_BW_HT20);

    uint8_t my_mac[6] = {0};
    ESP_ERROR_CHECK(esp_read_mac(my_mac, ESP_MAC_WIFI_STA));

    wifi_ap_record_t ap_info = {0};
    ESP_ERROR_CHECK(esp_wifi_sta_get_ap_info(&ap_info));

    es_state_init(my_mac, ap_info.bssid);
    ESP_ERROR_CHECK(es_i2c_init());
    ESP_ERROR_CHECK(es_udp_init());
    ESP_ERROR_CHECK(es_csi_init());

    /* Core 0 (PRO_CPU): Wi-Fi CSI callback + UDP RX from Central */
    xTaskCreatePinnedToCore(es_udp_rx_task, "es_udp_rx", 6144, NULL, 5, NULL, 0);

    /* Core 1 (APP_CPU): DSP/CSI TX, TDM slot scheduler, I2C sensors */
    xTaskCreatePinnedToCore(es_csi_process_task, "es_csi_proc", 6144, NULL, 6, NULL, 1);
    xTaskCreatePinnedToCore(es_tdm_task, "es_tdm", 6144, NULL, 5, NULL, 1);
    xTaskCreatePinnedToCore(es_i2c_task, "es_i2c", 4096, NULL, 3, NULL, 1);

    ESP_LOGI(TAG, "EdgeSpace ESP32-S3 firmware started (MAC=%02X:%02X:%02X:%02X:%02X:%02X, AP_CH=%d)",
             my_mac[0], my_mac[1], my_mac[2], my_mac[3], my_mac[4], my_mac[5], ap_info.primary);
}

#include "edgespace_proto.h"

#include <math.h>
#include <string.h>
#include "esp_csi_gain_ctrl.h"
#include "esp_log.h"
#include "esp_now.h"
#include "esp_wifi.h"
#include "freertos/FreeRTOS.h"
#include "freertos/queue.h"
#include "freertos/task.h"

static const char *TAG = "es_csi";
static const uint8_t s_espnow_bcast_mac[6] = {0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF};

static QueueHandle_t s_csi_queue = NULL;
static bool s_espnow_ready = false;

typedef struct __attribute__((packed)) {
    uint32_t magic;
    uint8_t tx_node_id;
    uint32_t cycle_seq;
} es_probe_pkt_t;

#define ES_PROBE_MAGIC 0x45534350u

static void wifi_csi_rx_cb(void *ctx, wifi_csi_info_t *info) {
    (void)ctx;
    if (!info || !info->buf || !s_csi_queue) {
        return;
    }
    es_csi_raw_pkt_t pkt;
    memcpy(&pkt.rx_ctrl, &info->rx_ctrl, sizeof(wifi_pkt_rx_ctrl_t));
    memcpy(pkt.src_mac, info->mac, 6);
    pkt.len = (info->len > EDGESPACE_CSI_BUF_MAX) ? EDGESPACE_CSI_BUF_MAX : (uint16_t)info->len;
    pkt.first_word_invalid = info->first_word_invalid;
    memcpy(pkt.buf, info->buf, pkt.len);

    /* The CSI callback runs in the Wi-Fi task (not an ISR): non-blocking enqueue, drop when full. */
    (void)xQueueSend(s_csi_queue, &pkt, 0);
}

static void espnow_recv_cb(const esp_now_recv_info_t *info, const uint8_t *data, int len) {
    (void)info;
    (void)data;
    (void)len;
}

static int resolve_tx_node_id(const uint8_t src_mac[6], const es_cluster_state_t *st) {
    for (int i = 0; i < EDGESPACE_MAX_NODES; i++) {
        if (st->peer_mac_valid[i] && memcmp(src_mac, st->peer_mac[i], 6) == 0) {
            if ((uint8_t)i != st->my_node_id) {
                return i;
            }
            return -1;
        }
    }
    /* Frames from any other transmitter (AP, unknown stations) are not cluster links. */
    return -1;
}

esp_err_t es_csi_init(void) {
    s_csi_queue = xQueueCreate(EDGESPACE_CSI_QUEUE_LEN, sizeof(es_csi_raw_pkt_t));
    if (!s_csi_queue) {
        return ESP_ERR_NO_MEM;
    }

    if (esp_now_init() == ESP_OK) {
        esp_now_register_recv_cb(espnow_recv_cb);
        esp_now_peer_info_t peer = {0};
        memcpy(peer.peer_addr, s_espnow_bcast_mac, 6);
        peer.channel = 0;
        peer.ifidx = WIFI_IF_STA;
        peer.encrypt = false;
        if (esp_now_add_peer(&peer) == ESP_OK) {
            esp_now_rate_config_t rate_cfg = {
                .phymode = WIFI_PHY_MODE_HT20,
                .rate = WIFI_PHY_RATE_MCS0_LGI,
                .ersu = false,
                .dcm = false,
            };
            (void)esp_now_set_peer_rate_config(peer.peer_addr, &rate_cfg);
            s_espnow_ready = true;
            ESP_LOGI(TAG, "ESP-NOW peer-to-peer CSI probes ready");
        }
    } else {
        ESP_LOGW(TAG, "esp_now_init failed; peer probes disabled");
    }

    wifi_csi_config_t csi_cfg = {
        .lltf_en           = true,
        .htltf_en          = false,
        .stbc_htltf2_en    = false,
        .ltf_merge_en      = true,
        .channel_filter_en = true,
        .manu_scale        = true,
        .shift             = true,
    };
    ESP_ERROR_CHECK(esp_wifi_set_csi_config(&csi_cfg));
    ESP_ERROR_CHECK(esp_wifi_set_csi_rx_cb(wifi_csi_rx_cb, NULL));
    ESP_ERROR_CHECK(esp_wifi_set_csi(true));
    ESP_LOGI(TAG, "Wi-Fi CSI capture enabled");
    return ESP_OK;
}

void es_csi_send_probe(uint8_t tx_node_id, uint32_t cycle_seq) {
    if (!s_espnow_ready) return;
    es_probe_pkt_t pkt = {
        .magic = ES_PROBE_MAGIC,
        .tx_node_id = tx_node_id,
        .cycle_seq = cycle_seq,
    };
    (void)esp_now_send(s_espnow_bcast_mac, (const uint8_t *)&pkt, sizeof(pkt));
}

void es_csi_process_task(void *arg) {
    (void)arg;
    es_csi_raw_pkt_t pkt;
    int16_t iq_scaled[EDGESPACE_MAX_SUBCARRIERS * 2];

    for (;;) {
        if (xQueueReceive(s_csi_queue, &pkt, portMAX_DELAY) != pdTRUE) {
            continue;
        }
        es_cluster_state_t st;
        es_state_get(&st);
        if (st.state != NODE_STATE_ACTIVE || st.my_node_id >= EDGESPACE_MAX_NODES) {
            continue;
        }

        int tx_id = resolve_tx_node_id(pkt.src_mac, &st);
        if (tx_id < 0 || tx_id >= EDGESPACE_MAX_NODES || (uint8_t)tx_id == st.my_node_id) {
            continue;
        }

        float comp_gain = 1.0f;
        uint8_t agc_gain = 0;
        int8_t fft_gain = 0;
        esp_csi_gain_ctrl_get_rx_gain(&pkt.rx_ctrl, &agc_gain, &fft_gain);
        esp_csi_gain_ctrl_get_gain_compensation(&comp_gain, agc_gain, fft_gain);

        int start = pkt.first_word_invalid ? 4 : 0;
        if (start >= pkt.len) continue;

        uint16_t count = (uint16_t)((pkt.len - start) / 2);
        if (count > EDGESPACE_MAX_SUBCARRIERS) {
            count = EDGESPACE_MAX_SUBCARRIERS;
        }
        if (count == 0) continue;

        for (uint16_t k = 0; k < count; k++) {
            int idx = start + (int)k * 2;
            float imag_f = ((float)pkt.buf[idx] * comp_gain) * (1000.0f / 32.0f);
            float real_f = ((float)pkt.buf[idx + 1] * comp_gain) * (1000.0f / 32.0f);
            if (real_f > 32767.0f) real_f = 32767.0f;
            if (real_f < -32768.0f) real_f = -32768.0f;
            if (imag_f > 32767.0f) imag_f = 32767.0f;
            if (imag_f < -32768.0f) imag_f = -32768.0f;
            iq_scaled[k * 2]     = (int16_t)lrintf(real_f);
            iq_scaled[k * 2 + 1] = (int16_t)lrintf(imag_f);
        }

        int16_t rssi = (int16_t)pkt.rx_ctrl.rssi;
        float noise_floor = (float)pkt.rx_ctrl.noise_floor;
        if (noise_floor == 0.0f) noise_floor = -92.0f;

        es_udp_send_csi_frame((uint8_t)tx_id, st.my_node_id, rssi, noise_floor, iq_scaled, count);
    }
}


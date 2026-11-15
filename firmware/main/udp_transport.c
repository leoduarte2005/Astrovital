#include "edgespace_proto.h"

#include <ctype.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include "cJSON.h"
#include "esp_log.h"
#include "esp_netif.h"
#include "freertos/FreeRTOS.h"
#include "freertos/semphr.h"
#include "freertos/task.h"
#include "lwip/inet.h"
#include "lwip/sockets.h"

static const char *TAG = "es_udp";

static int s_sock = -1;
static SemaphoreHandle_t s_tx_mu = NULL;
static struct sockaddr_in s_gw_addr;
static struct sockaddr_in s_bcast_addr;
static struct sockaddr_in s_central_addr;
static bool s_central_confirmed = false;

static void udp_sendto_central(const void *buf, size_t len) {
    if (s_sock < 0 || !buf || len == 0) return;
    xSemaphoreTake(s_tx_mu, portMAX_DELAY);
    if (s_central_confirmed) {
        sendto(s_sock, buf, len, 0, (struct sockaddr *)&s_central_addr, sizeof(s_central_addr));
    } else {
        sendto(s_sock, buf, len, 0, (struct sockaddr *)&s_gw_addr, sizeof(s_gw_addr));
        sendto(s_sock, buf, len, 0, (struct sockaddr *)&s_bcast_addr, sizeof(s_bcast_addr));
    }
    xSemaphoreGive(s_tx_mu);
}

static int format_periph_enum_list(uint8_t mask, char *out, size_t out_sz) {
    size_t pos = 0;
    const char *names[3] = {"MAX30102", "BME280", "SCD40"};
    uint8_t bits[3] = {PERIPH_BIT_MAX30102, PERIPH_BIT_BME280, PERIPH_BIT_SCD40};
    bool first = true;
    for (int i = 0; i < 3; i++) {
        if (mask & bits[i]) {
            int n = snprintf(out + pos, out_sz - pos, "%s\"%s\"", first ? "" : ",", names[i]);
            if (n > 0 && (size_t)n < out_sz - pos) {
                pos += (size_t)n;
                first = false;
            }
        }
    }
    out[pos] = '\0';
    return (int)pos;
}

esp_err_t es_udp_init(void) {
    s_tx_mu = xSemaphoreCreateMutex();
    s_sock = socket(AF_INET, SOCK_DGRAM, IPPROTO_IP);
    if (s_sock < 0) {
        return ESP_FAIL;
    }
    int yes = 1;
    setsockopt(s_sock, SOL_SOCKET, SO_BROADCAST, &yes, sizeof(yes));
    setsockopt(s_sock, SOL_SOCKET, SO_REUSEADDR, &yes, sizeof(yes));

    struct sockaddr_in local = {
        .sin_family = AF_INET,
        .sin_port = htons(EDGESPACE_UDP_PORT),
        .sin_addr.s_addr = htonl(INADDR_ANY),
    };
    if (bind(s_sock, (struct sockaddr *)&local, sizeof(local)) < 0) {
        close(s_sock);
        s_sock = -1;
        return ESP_FAIL;
    }

    esp_netif_ip_info_t ip_info = {0};
    esp_netif_get_ip_info(esp_netif_get_handle_from_ifkey("WIFI_STA_DEF"), &ip_info);

    memset(&s_gw_addr, 0, sizeof(s_gw_addr));
    s_gw_addr.sin_family = AF_INET;
    s_gw_addr.sin_port = htons(EDGESPACE_UDP_PORT);
    s_gw_addr.sin_addr.s_addr = ip_info.gw.addr;

    memset(&s_bcast_addr, 0, sizeof(s_bcast_addr));
    s_bcast_addr.sin_family = AF_INET;
    s_bcast_addr.sin_port = htons(EDGESPACE_UDP_PORT);
    s_bcast_addr.sin_addr.s_addr = ip_info.ip.addr | ~ip_info.netmask.addr;

    s_central_addr = s_gw_addr;
    s_central_confirmed = false;

    esp_ip4_addr_t bcast_ip = { .addr = s_bcast_addr.sin_addr.s_addr };
    ESP_LOGI(TAG, "UDP :%d ready (IP=" IPSTR " GW=" IPSTR " BCAST=" IPSTR ")",
             EDGESPACE_UDP_PORT, IP2STR(&ip_info.ip),
             IP2STR(&ip_info.gw), IP2STR(&bcast_ip));
    return ESP_OK;
}

void es_udp_send_node_hello(uint8_t periph_mask) {
    es_cluster_state_t st;
    es_state_get(&st);
    char plist[96] = {0};
    format_periph_enum_list(periph_mask, plist, sizeof(plist));
    uint8_t nid = (st.my_node_id < EDGESPACE_MAX_NODES) ? st.my_node_id : 0;
    int64_t ts = es_synced_now_us();

    char buf[384];
    int len = snprintf(buf, sizeof(buf),
        "{\"v\":1,\"type\":\"NODE_HELLO\",\"mac\":\"%s\",\"node_id\":%u,"
        "\"fw_version\":\"%s\",\"peripherals\":[%s],\"timestamp_us\":%lld}",
        st.my_mac_str, nid, EDGESPACE_FW_VERSION, plist, (long long)ts);
    if (len > 0 && len < (int)sizeof(buf)) {
        udp_sendto_central(buf, (size_t)len);
    }
}

void es_udp_send_heartbeat(uint8_t periph_mask, int rssi_dbm) {
    es_cluster_state_t st;
    es_state_get(&st);
    if (st.my_node_id >= EDGESPACE_MAX_NODES) return;
    char plist[96] = {0};
    format_periph_enum_list(periph_mask, plist, sizeof(plist));
    int64_t ts = es_synced_now_us();

    char buf[384];
    int len = snprintf(buf, sizeof(buf),
        "{\"v\":1,\"type\":\"HEARTBEAT\",\"mac\":\"%s\",\"node_id\":%u,"
        "\"cycle_seq\":%u,\"rssi_dbm\":%d,\"peripherals\":[%s],\"timestamp_us\":%lld}",
        st.my_mac_str, st.my_node_id, (unsigned)st.cycle_seq, rssi_dbm, plist, (long long)ts);
    if (len > 0 && len < (int)sizeof(buf)) {
        udp_sendto_central(buf, (size_t)len);
    }
}

void es_udp_send_csi_frame(uint8_t tx_node_id, uint8_t rx_node_id, int16_t rssi_dbm,
                           float noise_floor, const int16_t *iq_scaled, uint16_t sample_count) {
    if (!iq_scaled || sample_count == 0 || sample_count > EDGESPACE_MAX_SUBCARRIERS) return;
    es_cluster_state_t st;
    es_state_get(&st);
    uint8_t slot_id = (st.my_slot_id >= 0) ? (uint8_t)st.my_slot_id : 0;
    int64_t ts = es_synced_now_us();

    uint8_t pkt[256 + 10 + EDGESPACE_MAX_SUBCARRIERS * 4];
    int hdr_len = snprintf((char *)pkt, 256,
        "{\"v\":1,\"type\":\"CSI_FRAME\",\"node_id\":%u,\"slot_id\":%u,"
        "\"mode\":\"%s\",\"timestamp_us\":%lld,\"cycle_seq\":%u,\"rssi_dbm\":%d}\n",
        rx_node_id, slot_id, es_mode_to_str(st.mode),
        (long long)ts, (unsigned)st.cycle_seq, (int)rssi_dbm);
    if (hdr_len <= 0 || hdr_len >= 256) return;

    uint8_t *bin = pkt + hdr_len;
    bin[0] = tx_node_id;
    bin[1] = rx_node_id;
    uint16_t rssi_u = (uint16_t)rssi_dbm;
    bin[2] = (uint8_t)(rssi_u & 0xFF);
    bin[3] = (uint8_t)((rssi_u >> 8) & 0xFF);
    uint32_t nf_bits = 0;
    memcpy(&nf_bits, &noise_floor, 4);
    bin[4] = (uint8_t)(nf_bits & 0xFF);
    bin[5] = (uint8_t)((nf_bits >> 8) & 0xFF);
    bin[6] = (uint8_t)((nf_bits >> 16) & 0xFF);
    bin[7] = (uint8_t)((nf_bits >> 24) & 0xFF);
    bin[8] = (uint8_t)(sample_count & 0xFF);
    bin[9] = (uint8_t)((sample_count >> 8) & 0xFF);

    size_t off = 10;
    for (uint16_t i = 0; i < sample_count; i++) {
        uint16_t iv = (uint16_t)iq_scaled[i * 2];
        uint16_t qv = (uint16_t)iq_scaled[i * 2 + 1];
        bin[off++] = (uint8_t)(iv & 0xFF);
        bin[off++] = (uint8_t)((iv >> 8) & 0xFF);
        bin[off++] = (uint8_t)(qv & 0xFF);
        bin[off++] = (uint8_t)((qv >> 8) & 0xFF);
    }

    udp_sendto_central(pkt, (size_t)hdr_len + off);
}

void es_udp_send_peripheral_data(const es_sensor_snapshot_t *snap) {
    if (!snap || snap->detected_mask == 0) return;
    es_cluster_state_t st;
    es_state_get(&st);
    if (st.my_node_id >= EDGESPACE_MAX_NODES) return;

    int64_t ts = es_synced_now_us();
    char items[512] = {0};
    size_t pos = 0;
    bool first = true;

    if (snap->has_bme280) {
        int n = snprintf(items + pos, sizeof(items) - pos,
            "%s{\"type\":\"BME280\",\"value\":%.2f,\"unit\":\"C\",\"timestamp_us\":%lld},"
            "{\"type\":\"BME280\",\"value\":%.2f,\"unit\":\"hPa\",\"timestamp_us\":%lld}",
            first ? "" : ",", snap->temp_c, (long long)ts, snap->pressure_hpa, (long long)ts);
        if (n > 0 && (size_t)n < sizeof(items) - pos) { pos += (size_t)n; first = false; }
        if (snap->bme_has_humidity) {
            n = snprintf(items + pos, sizeof(items) - pos,
                ",{\"type\":\"BME280\",\"value\":%.2f,\"unit\":\"%%RH\",\"timestamp_us\":%lld}",
                snap->humidity_pct, (long long)ts);
            if (n > 0 && (size_t)n < sizeof(items) - pos) pos += (size_t)n;
        }
    }
    if (snap->has_scd40 && snap->scd40_valid) {
        int n = snprintf(items + pos, sizeof(items) - pos,
            "%s{\"type\":\"SCD40\",\"value\":%.1f,\"unit\":\"ppm\",\"timestamp_us\":%lld}",
            first ? "" : ",", snap->co2_ppm, (long long)ts);
        if (n > 0 && (size_t)n < sizeof(items) - pos) { pos += (size_t)n; first = false; }
    }
    if (snap->has_max30102 && snap->max30102_finger) {
        int n = snprintf(items + pos, sizeof(items) - pos,
            "%s{\"type\":\"MAX30102\",\"value\":%.1f,\"unit\":\"bpm\",\"timestamp_us\":%lld},"
            "{\"type\":\"MAX30102\",\"value\":%.1f,\"unit\":\"%%\",\"timestamp_us\":%lld}",
            first ? "" : ",", snap->heart_rate_bpm, (long long)ts, snap->spo2_pct, (long long)ts);
        if (n > 0 && (size_t)n < sizeof(items) - pos) { pos += (size_t)n; first = false; }
    }
    if (first) return;

    char buf[768];
    uint8_t slot_id = (st.my_slot_id >= 0) ? (uint8_t)st.my_slot_id : 0;
    int len = snprintf(buf, sizeof(buf),
        "{\"v\":1,\"type\":\"PERIPHERAL_DATA\",\"node_id\":%u,\"slot_id\":%u,"
        "\"mode\":\"%s\",\"timestamp_us\":%lld,\"cycle_seq\":%u,\"mac\":\"%s\","
        "\"peripherals\":[%s]}",
        st.my_node_id, slot_id, es_mode_to_str(st.mode),
        (long long)ts, (unsigned)st.cycle_seq, st.my_mac_str, items);
    if (len > 0 && len < (int)sizeof(buf)) {
        udp_sendto_central(buf, (size_t)len);
    }
}

static bool parse_mac_str(const char *s, uint8_t mac[6]) {
    if (!s) return false;
    unsigned int b[6];
    if (sscanf(s, "%02x:%02x:%02x:%02x:%02x:%02x",
               &b[0], &b[1], &b[2], &b[3], &b[4], &b[5]) != 6) {
        return false;
    }
    for (int i = 0; i < 6; i++) mac[i] = (uint8_t)b[i];
    return true;
}

static void handle_rx_json(const char *json_str, const struct sockaddr_in *src) {
    cJSON *root = cJSON_Parse(json_str);
    if (!root) return;

    cJSON *jtype = cJSON_GetObjectItemCaseSensitive(root, "type");
    if (!cJSON_IsString(jtype) || !jtype->valuestring) {
        cJSON_Delete(root);
        return;
    }
    const char *mtype = jtype->valuestring;

    if (strcmp(mtype, "NODE_ASSIGN") == 0 || strcmp(mtype, "CLUSTER_SYNC") == 0 || strcmp(mtype, "MODE_CMD") == 0) {
        xSemaphoreTake(s_tx_mu, portMAX_DELAY);
        if (!s_central_confirmed || s_central_addr.sin_addr.s_addr != src->sin_addr.s_addr) {
            s_central_addr = *src;
            s_central_addr.sin_port = htons(EDGESPACE_UDP_PORT);
            s_central_confirmed = true;
            ESP_LOGI(TAG, "Central locked at %s:%d", inet_ntoa(src->sin_addr), EDGESPACE_UDP_PORT);
        }
        xSemaphoreGive(s_tx_mu);
    }

    if (strcmp(mtype, "NODE_ASSIGN") == 0) {
        cJSON *jnid = cJSON_GetObjectItemCaseSensitive(root, "node_id");
        cJSON *jslot = cJSON_GetObjectItemCaseSensitive(root, "slot_id");
        cJSON *jseq = cJSON_GetObjectItemCaseSensitive(root, "cycle_seq");
        cJSON *jts = cJSON_GetObjectItemCaseSensitive(root, "timestamp_us");
        cJSON *jpeers = cJSON_GetObjectItemCaseSensitive(root, "peers");

        uint8_t nid = cJSON_IsNumber(jnid) ? (uint8_t)jnid->valueint : 0xFF;
        int8_t slot = cJSON_IsNumber(jslot) ? (int8_t)jslot->valueint : -1;
        uint32_t seq = cJSON_IsNumber(jseq) ? (uint32_t)jseq->valuedouble : 0;
        int64_t ts_us = cJSON_IsNumber(jts) ? (int64_t)jts->valuedouble : 0;

        uint8_t p_valid[EDGESPACE_MAX_NODES] = {0};
        uint8_t p_macs[EDGESPACE_MAX_NODES][6] = {{0}};
        if (cJSON_IsArray(jpeers)) {
            cJSON *item = NULL;
            cJSON_ArrayForEach(item, jpeers) {
                cJSON *pid = cJSON_GetObjectItemCaseSensitive(item, "node_id");
                cJSON *pmac = cJSON_GetObjectItemCaseSensitive(item, "mac");
                if (cJSON_IsNumber(pid) && cJSON_IsString(pmac)) {
                    int idx = pid->valueint;
                    if (idx >= 0 && idx < EDGESPACE_MAX_NODES && parse_mac_str(pmac->valuestring, p_macs[idx])) {
                        p_valid[idx] = 1;
                    }
                }
            }
        }
        es_state_apply_node_assign(nid, slot, seq, ts_us, p_valid, p_macs);
    } else if (strcmp(mtype, "CLUSTER_SYNC") == 0) {
        cJSON *jseq = cJSON_GetObjectItemCaseSensitive(root, "cycle_seq");
        cJSON *jts = cJSON_GetObjectItemCaseSensitive(root, "timestamp_us");
        cJSON *jmode = cJSON_GetObjectItemCaseSensitive(root, "mode");
        cJSON *jslotms = cJSON_GetObjectItemCaseSensitive(root, "slot_ms");
        cJSON *jmask = cJSON_GetObjectItemCaseSensitive(root, "active_node_mask");
        cJSON *jslots = cJSON_GetObjectItemCaseSensitive(root, "slots");

        uint32_t seq = cJSON_IsNumber(jseq) ? (uint32_t)jseq->valuedouble : 0;
        int64_t ts_us = cJSON_IsNumber(jts) ? (int64_t)jts->valuedouble : 0;
        es_mission_mode_t mode = cJSON_IsString(jmode) ? es_str_to_mode(jmode->valuestring) : MODE_CABIN_TOMOGRAPHY;
        uint16_t slot_ms = cJSON_IsNumber(jslotms) ? (uint16_t)jslotms->valueint : 20;
        uint8_t mask = cJSON_IsNumber(jmask) ? (uint8_t)jmask->valueint : 0;

        es_slot_entry_t slots[EDGESPACE_MAX_NODES] = {{0}};
        uint8_t scount = 0;
        if (cJSON_IsArray(jslots)) {
            cJSON *item = NULL;
            cJSON_ArrayForEach(item, jslots) {
                if (scount >= EDGESPACE_MAX_NODES) break;
                cJSON *jn = cJSON_GetObjectItemCaseSensitive(item, "node_id");
                cJSON *js = cJSON_GetObjectItemCaseSensitive(item, "slot_id");
                if (cJSON_IsNumber(jn) && cJSON_IsNumber(js)) {
                    slots[scount].node_id = (uint8_t)jn->valueint;
                    slots[scount].slot_id = (uint8_t)js->valueint;
                    scount++;
                }
            }
        }
        es_state_apply_cluster_sync(seq, ts_us, mode, slot_ms, mask, slots, scount);
    } else if (strcmp(mtype, "MODE_CMD") == 0) {
        cJSON *jmode = cJSON_GetObjectItemCaseSensitive(root, "mode");
        cJSON *jseq = cJSON_GetObjectItemCaseSensitive(root, "cycle_seq");
        cJSON *jts = cJSON_GetObjectItemCaseSensitive(root, "timestamp_us");
        es_mission_mode_t mode = cJSON_IsString(jmode) ? es_str_to_mode(jmode->valuestring) : MODE_CABIN_TOMOGRAPHY;
        uint32_t seq = cJSON_IsNumber(jseq) ? (uint32_t)jseq->valuedouble : 0;
        int64_t ts_us = cJSON_IsNumber(jts) ? (int64_t)jts->valuedouble : 0;
        es_state_apply_mode_cmd(mode, seq, ts_us);
    }

    cJSON_Delete(root);
}

void es_udp_rx_task(void *arg) {
    (void)arg;
    char rx_buf[1536];
    struct sockaddr_in src;

    for (;;) {
        socklen_t srclen = sizeof(src);
        int n = recvfrom(s_sock, rx_buf, sizeof(rx_buf) - 1, 0, (struct sockaddr *)&src, &srclen);
        if (n <= 0) {
            vTaskDelay(pdMS_TO_TICKS(10));
            continue;
        }
        rx_buf[n] = '\0';
        handle_rx_json(rx_buf, &src);
    }
}

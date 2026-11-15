#include "edgespace_proto.h"

#include <stdio.h>
#include <string.h>
#include "esp_log.h"
#include "esp_timer.h"
#include "esp_wifi.h"
#include "freertos/FreeRTOS.h"
#include "freertos/semphr.h"
#include "freertos/task.h"

static const char *TAG = "es_tdm";

static SemaphoreHandle_t s_state_mu = NULL;
static es_cluster_state_t s_state = {
    .my_node_id = 0xFF,
    .my_slot_id = -1,
    .state = NODE_STATE_DISCOVERED,
    .mode = MODE_CABIN_TOMOGRAPHY,
    .slot_ms = 20,
};

const char *es_mode_to_str(es_mission_mode_t mode) {
    switch (mode) {
    case MODE_REST_VITALS: return "MODE_REST_VITALS";
    case MODE_COUNTERMEASURE_EXERCISE: return "MODE_COUNTERMEASURE_EXERCISE";
    case MODE_RADIATION_ALERT: return "MODE_RADIATION_ALERT";
    case MODE_CABIN_TOMOGRAPHY:
    default:
        return "MODE_CABIN_TOMOGRAPHY";
    }
}

es_mission_mode_t es_str_to_mode(const char *s) {
    if (!s) return MODE_CABIN_TOMOGRAPHY;
    if (strcmp(s, "MODE_REST_VITALS") == 0) return MODE_REST_VITALS;
    if (strcmp(s, "MODE_COUNTERMEASURE_EXERCISE") == 0) return MODE_COUNTERMEASURE_EXERCISE;
    if (strcmp(s, "MODE_RADIATION_ALERT") == 0) return MODE_RADIATION_ALERT;
    return MODE_CABIN_TOMOGRAPHY;
}

void es_state_init(const uint8_t my_mac[6], const uint8_t ap_bssid[6]) {
    s_state_mu = xSemaphoreCreateMutex();
    xSemaphoreTake(s_state_mu, portMAX_DELAY);
    memset(&s_state, 0, sizeof(s_state));
    s_state.my_node_id = 0xFF;
    s_state.my_slot_id = -1;
    s_state.state = NODE_STATE_DISCOVERED;
    s_state.mode = MODE_CABIN_TOMOGRAPHY;
    s_state.slot_ms = 20;
    memcpy(s_state.my_mac, my_mac, 6);
    memcpy(s_state.ap_bssid, ap_bssid, 6);
    snprintf(s_state.my_mac_str, sizeof(s_state.my_mac_str),
             "%02X:%02X:%02X:%02X:%02X:%02X",
             my_mac[0], my_mac[1], my_mac[2], my_mac[3], my_mac[4], my_mac[5]);
    xSemaphoreGive(s_state_mu);
}

void es_state_get(es_cluster_state_t *out) {
    if (!out) return;
    xSemaphoreTake(s_state_mu, portMAX_DELAY);
    *out = s_state;
    xSemaphoreGive(s_state_mu);
}

int64_t es_synced_now_us(void) {
    int64_t local_us = esp_timer_get_time();
    if (!s_state_mu) return local_us;
    xSemaphoreTake(s_state_mu, portMAX_DELAY);
    int64_t res = s_state.ts_synced ? (s_state.ts_offset_us + local_us) : 0;
    xSemaphoreGive(s_state_mu);
    return res;
}

void es_state_apply_node_assign(uint8_t node_id, int8_t slot_id, uint32_t cycle_seq,
                                int64_t central_ts_us, const uint8_t peer_valid[EDGESPACE_MAX_NODES],
                                uint8_t peer_macs[EDGESPACE_MAX_NODES][6]) {
    int64_t now_local = esp_timer_get_time();
    xSemaphoreTake(s_state_mu, portMAX_DELAY);
    if (node_id < EDGESPACE_MAX_NODES) {
        if (s_state.my_node_id != node_id) {
            ESP_LOGI(TAG, "Assigned node_id=%u (MAC=%s)", node_id, s_state.my_mac_str);
        }
        s_state.my_node_id = node_id;
        if (slot_id >= 0) {
            s_state.my_slot_id = slot_id;
            s_state.state = NODE_STATE_ACTIVE;
        } else if (s_state.state == NODE_STATE_DISCOVERED) {
            s_state.state = NODE_STATE_SYNCING;
        }
    }
    if (cycle_seq > s_state.cycle_seq) {
        s_state.cycle_seq = cycle_seq;
    }
    if (central_ts_us > 0) {
        s_state.ts_offset_us = central_ts_us - now_local;
        s_state.ts_synced = true;
    }
    s_state.last_sync_local_us = now_local;
    for (int i = 0; i < EDGESPACE_MAX_NODES; i++) {
        if (peer_valid[i]) {
            s_state.peer_mac_valid[i] = true;
            memcpy(s_state.peer_mac[i], peer_macs[i], 6);
        }
    }
    xSemaphoreGive(s_state_mu);
}

void es_state_apply_cluster_sync(uint32_t cycle_seq, int64_t central_ts_us, es_mission_mode_t mode,
                                 uint16_t slot_ms, uint8_t active_mask,
                                 const es_slot_entry_t *slots, uint8_t slot_count) {
    int64_t now_local = esp_timer_get_time();
    xSemaphoreTake(s_state_mu, portMAX_DELAY);
    s_state.cycle_seq = cycle_seq;
    s_state.mode = mode;
    s_state.active_node_mask = active_mask;
    if (slot_ms > 0) {
        s_state.slot_ms = slot_ms;
    }
    if (slot_count > EDGESPACE_MAX_NODES) {
        slot_count = EDGESPACE_MAX_NODES;
    }
    s_state.slot_count = slot_count;
    int8_t found_slot = -1;
    for (uint8_t i = 0; i < slot_count; i++) {
        s_state.slots[i] = slots[i];
        if (s_state.my_node_id < EDGESPACE_MAX_NODES && slots[i].node_id == s_state.my_node_id) {
            found_slot = (int8_t)slots[i].slot_id;
        }
    }
    s_state.my_slot_id = found_slot;
    if (found_slot >= 0) {
        if (s_state.state != NODE_STATE_ACTIVE) {
            ESP_LOGI(TAG, "Node %u ACTIVE in slot %d (slot_ms=%u, mask=0x%02X)",
                     s_state.my_node_id, found_slot, s_state.slot_ms, active_mask);
        }
        s_state.state = NODE_STATE_ACTIVE;
    } else if (s_state.my_node_id < EDGESPACE_MAX_NODES) {
        s_state.state = NODE_STATE_SYNCING;
    }
    if (central_ts_us > 0) {
        s_state.ts_offset_us = central_ts_us - now_local;
        s_state.ts_synced = true;
    }
    s_state.last_sync_local_us = now_local;
    s_state.cycle_start_local_us = now_local;
    xSemaphoreGive(s_state_mu);
}

void es_state_apply_mode_cmd(es_mission_mode_t mode, uint32_t cycle_seq, int64_t central_ts_us) {
    int64_t now_local = esp_timer_get_time();
    xSemaphoreTake(s_state_mu, portMAX_DELAY);
    if (s_state.mode != mode) {
        ESP_LOGI(TAG, "Mission mode -> %s", es_mode_to_str(mode));
    }
    s_state.mode = mode;
    if (cycle_seq > s_state.cycle_seq) {
        s_state.cycle_seq = cycle_seq;
    }
    if (central_ts_us > 0) {
        s_state.ts_offset_us = central_ts_us - now_local;
        s_state.ts_synced = true;
    }
    xSemaphoreGive(s_state_mu);
}

bool es_state_check_sync_timeout(int64_t timeout_us) {
    int64_t now_local = esp_timer_get_time();
    bool timed_out = false;
    xSemaphoreTake(s_state_mu, portMAX_DELAY);
    if (s_state.last_sync_local_us > 0 && (now_local - s_state.last_sync_local_us) > timeout_us) {
        if (s_state.state == NODE_STATE_ACTIVE) {
            s_state.state = NODE_STATE_SYNCING;
            s_state.my_slot_id = -1;
            timed_out = true;
        }
    }
    xSemaphoreGive(s_state_mu);
    return timed_out;
}

void es_tdm_task(void *arg) {
    (void)arg;
    uint32_t last_tx_cycle = UINT32_MAX;
    int rssi = -50;
    int64_t last_hello_us = 0;
    int64_t last_hb_us = 0;
    int64_t last_periph_us = 0;

    for (;;) {
        int64_t now_us = esp_timer_get_time();
        es_cluster_state_t st;
        es_state_get(&st);

        es_sensor_snapshot_t snap;
        es_i2c_get_snapshot(&snap);

        if (st.my_node_id >= EDGESPACE_MAX_NODES) {
            if (last_hello_us == 0 || (now_us - last_hello_us) >= 500000LL) {
                es_udp_send_node_hello(snap.detected_mask);
                last_hello_us = now_us;
            }
            vTaskDelay(pdMS_TO_TICKS(20));
            continue;
        }

        if (es_state_check_sync_timeout(1500000LL)) {
            ESP_LOGW(TAG, "CLUSTER_SYNC timeout; re-sending NODE_HELLO");
            es_udp_send_node_hello(snap.detected_mask);
            last_hello_us = now_us;
        }

        /* Keep Central FSM liveness (<200ms SuspectAfter): heartbeat every 80ms */
        if (last_hb_us == 0 || (now_us - last_hb_us) >= 80000LL) {
            wifi_ap_record_t ap_info;
            if (esp_wifi_sta_get_ap_info(&ap_info) == ESP_OK) {
                rssi = ap_info.rssi;
            }
            es_udp_send_heartbeat(snap.detected_mask, rssi);
            last_hb_us = now_us;
        }

        uint16_t slot_ms = (st.slot_ms >= 10 && st.slot_ms <= 100) ? st.slot_ms : 20;

        /* TDM: transmit once per cycle, inside our slot measured from CLUSTER_SYNC arrival. */
        if (st.state == NODE_STATE_ACTIVE && st.my_slot_id >= 0 &&
            st.cycle_start_local_us > 0 && st.cycle_seq != last_tx_cycle) {
            int64_t since_us = now_us - st.cycle_start_local_us;
            int64_t slot_begin_us = (int64_t)st.my_slot_id * (int64_t)slot_ms * 1000LL;
            int64_t slot_end_us = slot_begin_us + (int64_t)slot_ms * 1000LL;
            if (since_us >= slot_begin_us && since_us < slot_end_us) {
                last_tx_cycle = st.cycle_seq;
                es_csi_send_probe(st.my_node_id, st.cycle_seq);
                if (slot_ms >= 20) {
                    vTaskDelay(pdMS_TO_TICKS(2));
                    es_csi_send_probe(st.my_node_id, st.cycle_seq);
                }
            }
        }

        if ((now_us - last_periph_us) >= 1000000LL && snap.detected_mask != 0) {
            es_udp_send_peripheral_data(&snap);
            last_periph_us = now_us;
        }

        vTaskDelay(pdMS_TO_TICKS(2));
    }
}

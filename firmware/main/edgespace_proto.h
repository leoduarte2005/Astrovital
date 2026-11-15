#pragma once

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include "esp_err.h"
#include "esp_wifi_types.h"

#ifdef __cplusplus
extern "C" {
#endif

#define EDGESPACE_UDP_PORT          5005
#define EDGESPACE_MAX_NODES         5
#define EDGESPACE_MAX_SUBCARRIERS   56
#define EDGESPACE_CSI_BUF_MAX       384
#define EDGESPACE_CSI_QUEUE_LEN     32
#define EDGESPACE_FW_VERSION        "1.0.0"

#define PERIPH_BIT_MAX30102         (1u << 0)
#define PERIPH_BIT_BME280           (1u << 1)
#define PERIPH_BIT_SCD40            (1u << 2)

typedef enum {
    MODE_CABIN_TOMOGRAPHY = 0,
    MODE_REST_VITALS = 1,
    MODE_COUNTERMEASURE_EXERCISE = 2,
    MODE_RADIATION_ALERT = 3,
} es_mission_mode_t;

typedef enum {
    NODE_STATE_DISCOVERED = 0,
    NODE_STATE_SYNCING = 1,
    NODE_STATE_ACTIVE = 2,
} es_node_state_t;

typedef struct {
    wifi_pkt_rx_ctrl_t rx_ctrl;
    uint8_t src_mac[6];
    uint16_t len;
    bool first_word_invalid;
    int8_t buf[EDGESPACE_CSI_BUF_MAX];
} es_csi_raw_pkt_t;

typedef struct {
    uint8_t detected_mask;      /* PERIPH_BIT_* physically present on I2C bus */
    bool has_bme280;
    bool bme_has_humidity;
    float temp_c;
    float humidity_pct;
    float pressure_hpa;

    bool has_scd40;
    bool scd40_valid;
    float co2_ppm;

    bool has_max30102;
    bool max30102_finger;
    float heart_rate_bpm;
    float spo2_pct;
} es_sensor_snapshot_t;

typedef struct {
    uint8_t node_id;
    uint8_t slot_id;
} es_slot_entry_t;

typedef struct {
    uint8_t my_node_id;         /* 0..4, or 0xFF before NODE_ASSIGN */
    int8_t my_slot_id;          /* 0..4, or -1 if not scheduled */
    es_node_state_t state;
    es_mission_mode_t mode;
    uint32_t cycle_seq;
    uint8_t active_node_mask;
    uint16_t slot_ms;
    uint8_t slot_count;
    es_slot_entry_t slots[EDGESPACE_MAX_NODES];
    uint8_t my_mac[6];
    char my_mac_str[18];
    uint8_t ap_bssid[6];
    bool peer_mac_valid[EDGESPACE_MAX_NODES];
    uint8_t peer_mac[EDGESPACE_MAX_NODES][6];
    int64_t last_sync_local_us;
    int64_t cycle_start_local_us; /* esp_timer_get_time() when the last CLUSTER_SYNC arrived */
    int64_t ts_offset_us;       /* central_unix_us - esp_timer_get_time() */
    bool ts_synced;
} es_cluster_state_t;

/* Shared global state accessors (implemented in tdm_sync.c) */
void es_state_init(const uint8_t my_mac[6], const uint8_t ap_bssid[6]);
void es_state_get(es_cluster_state_t *out);
int64_t es_synced_now_us(void);
void es_state_apply_node_assign(uint8_t node_id, int8_t slot_id, uint32_t cycle_seq,
                                int64_t central_ts_us, const uint8_t peer_valid[EDGESPACE_MAX_NODES],
                                uint8_t peer_macs[EDGESPACE_MAX_NODES][6]);
void es_state_apply_cluster_sync(uint32_t cycle_seq, int64_t central_ts_us, es_mission_mode_t mode,
                                 uint16_t slot_ms, uint8_t active_mask,
                                 const es_slot_entry_t *slots, uint8_t slot_count);
void es_state_apply_mode_cmd(es_mission_mode_t mode, uint32_t cycle_seq, int64_t central_ts_us);
void es_state_mark_heartbeat_sent(void);
bool es_state_check_sync_timeout(int64_t timeout_us);

const char *es_mode_to_str(es_mission_mode_t mode);
es_mission_mode_t es_str_to_mode(const char *s);

/* UDP transport (udp_transport.c) */
esp_err_t es_udp_init(void);
void es_udp_send_node_hello(uint8_t periph_mask);
void es_udp_send_heartbeat(uint8_t periph_mask, int rssi_dbm);
void es_udp_send_csi_frame(uint8_t tx_node_id, uint8_t rx_node_id, int16_t rssi_dbm,
                           float noise_floor, const int16_t *iq_scaled, uint16_t sample_count);
void es_udp_send_peripheral_data(const es_sensor_snapshot_t *snap);
void es_udp_rx_task(void *arg);

/* CSI + ESP-NOW capture (csi_capture.c) */
esp_err_t es_csi_init(void);
void es_csi_send_probe(uint8_t tx_node_id, uint32_t cycle_seq);
void es_csi_process_task(void *arg);

/* I2C real sensors (i2c_sensors.c) */
esp_err_t es_i2c_init(void);
void es_i2c_get_snapshot(es_sensor_snapshot_t *out);
void es_i2c_task(void *arg);

/* TDM coordinator (tdm_sync.c) */
void es_tdm_task(void *arg);

#ifdef __cplusplus
}
#endif

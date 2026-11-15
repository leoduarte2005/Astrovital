#include "edgespace_proto.h"

#include <math.h>
#include <string.h>
#include "driver/gpio.h"
#include "driver/i2c_master.h"
#include "esp_log.h"
#include "freertos/FreeRTOS.h"
#include "freertos/semphr.h"
#include "freertos/task.h"

#ifndef EDGESPACE_I2C_SDA
#define EDGESPACE_I2C_SDA GPIO_NUM_8
#endif
#ifndef EDGESPACE_I2C_SCL
#define EDGESPACE_I2C_SCL GPIO_NUM_9
#endif

#define I2C_FREQ_HZ       100000
#define I2C_XFER_MS       50
#define MAX30102_ADDR     0x57
#define SCD40_ADDR        0x62
#define BME280_ADDR_LOW   0x76
#define BME280_ADDR_HIGH  0x77

static const char *TAG = "es_i2c";

static i2c_master_bus_handle_t s_bus = NULL;
static i2c_master_dev_handle_t s_dev_bme = NULL;
static i2c_master_dev_handle_t s_dev_scd = NULL;
static i2c_master_dev_handle_t s_dev_max = NULL;
static uint8_t s_bme_addr = 0;

static SemaphoreHandle_t s_snap_mu = NULL;
static es_sensor_snapshot_t s_snap = {0};

typedef struct {
    uint16_t dig_T1;
    int16_t  dig_T2, dig_T3;
    uint16_t dig_P1;
    int16_t  dig_P2, dig_P3, dig_P4, dig_P5, dig_P6, dig_P7, dig_P8, dig_P9;
    uint8_t  dig_H1, dig_H3;
    int16_t  dig_H2, dig_H4, dig_H5;
    int8_t   dig_H6;
    int32_t  t_fine;
} bme280_calib_t;

static bme280_calib_t s_bme_cal = {0};

#define PPG_WIN 100
static uint32_t s_ir_buf[PPG_WIN];
static uint32_t s_red_buf[PPG_WIN];
static int s_ppg_idx = 0;
static int s_ppg_count = 0;

static esp_err_t reg_read(i2c_master_dev_handle_t dev, uint8_t reg, uint8_t *out, size_t len) {
    return i2c_master_transmit_receive(dev, &reg, 1, out, len, I2C_XFER_MS);
}

static esp_err_t reg_write(i2c_master_dev_handle_t dev, uint8_t reg, uint8_t val) {
    uint8_t buf[2] = {reg, val};
    return i2c_master_transmit(dev, buf, 2, I2C_XFER_MS);
}

static uint8_t sensirion_crc8(const uint8_t *data, size_t len) {
    uint8_t crc = 0xFF;
    for (size_t i = 0; i < len; i++) {
        crc ^= data[i];
        for (int b = 0; b < 8; b++) {
            crc = (crc & 0x80) ? (uint8_t)((crc << 1) ^ 0x31) : (uint8_t)(crc << 1);
        }
    }
    return crc;
}

static bool init_bme280(uint8_t addr, bool *has_hum) {
    i2c_device_config_t cfg = {
        .dev_addr_length = I2C_ADDR_BIT_LEN_7,
        .device_address = addr,
        .scl_speed_hz = I2C_FREQ_HZ,
    };
    if (i2c_master_bus_add_device(s_bus, &cfg, &s_dev_bme) != ESP_OK) return false;

    uint8_t id = 0;
    if (reg_read(s_dev_bme, 0xD0, &id, 1) != ESP_OK || (id != 0x60 && id != 0x58)) {
        i2c_master_bus_rm_device(s_dev_bme);
        s_dev_bme = NULL;
        return false;
    }
    *has_hum = (id == 0x60);
    s_bme_addr = addr;

    uint8_t c1[26] = {0};
    if (reg_read(s_dev_bme, 0x88, c1, 26) != ESP_OK) {
        i2c_master_bus_rm_device(s_dev_bme);
        s_dev_bme = NULL;
        return false;
    }
    s_bme_cal.dig_T1 = (uint16_t)(c1[1] << 8 | c1[0]);
    s_bme_cal.dig_T2 = (int16_t)(c1[3] << 8 | c1[2]);
    s_bme_cal.dig_T3 = (int16_t)(c1[5] << 8 | c1[4]);
    s_bme_cal.dig_P1 = (uint16_t)(c1[7] << 8 | c1[6]);
    s_bme_cal.dig_P2 = (int16_t)(c1[9] << 8 | c1[8]);
    s_bme_cal.dig_P3 = (int16_t)(c1[11] << 8 | c1[10]);
    s_bme_cal.dig_P4 = (int16_t)(c1[13] << 8 | c1[12]);
    s_bme_cal.dig_P5 = (int16_t)(c1[15] << 8 | c1[14]);
    s_bme_cal.dig_P6 = (int16_t)(c1[17] << 8 | c1[16]);
    s_bme_cal.dig_P7 = (int16_t)(c1[19] << 8 | c1[18]);
    s_bme_cal.dig_P8 = (int16_t)(c1[21] << 8 | c1[20]);
    s_bme_cal.dig_P9 = (int16_t)(c1[23] << 8 | c1[22]);
    s_bme_cal.dig_H1 = c1[25];

    if (*has_hum) {
        uint8_t c2[7] = {0};
        if (reg_read(s_dev_bme, 0xE1, c2, 7) == ESP_OK) {
            s_bme_cal.dig_H2 = (int16_t)(c2[1] << 8 | c2[0]);
            s_bme_cal.dig_H3 = c2[2];
            s_bme_cal.dig_H4 = (int16_t)((c2[3] << 4) | (c2[4] & 0x0F));
            s_bme_cal.dig_H5 = (int16_t)((c2[5] << 4) | (c2[4] >> 4));
            s_bme_cal.dig_H6 = (int8_t)c2[6];
        }
        reg_write(s_dev_bme, 0xF2, 0x01);
    }
    reg_write(s_dev_bme, 0xF5, 0xA0);
    reg_write(s_dev_bme, 0xF4, 0x27);
    ESP_LOGI(TAG, "BME/BMP280 detected at 0x%02X (id=0x%02X)", addr, id);
    return true;
}
static bool read_bme280(bool has_hum, float *temp_c, float *press_hpa, float *hum_pct) {
    if (!s_dev_bme) return false;
    uint8_t raw[8] = {0};
    if (reg_read(s_dev_bme, 0xF7, raw, 8) != ESP_OK) return false;

    int32_t adc_P = ((int32_t)raw[0] << 12) | ((int32_t)raw[1] << 4) | (raw[2] >> 4);
    int32_t adc_T = ((int32_t)raw[3] << 12) | ((int32_t)raw[4] << 4) | (raw[5] >> 4);
    int32_t adc_H = ((int32_t)raw[6] << 8) | raw[7];

    int32_t var1 = ((((adc_T >> 3) - ((int32_t)s_bme_cal.dig_T1 << 1))) * ((int32_t)s_bme_cal.dig_T2)) >> 11;
    int32_t var2 = (((((adc_T >> 4) - ((int32_t)s_bme_cal.dig_T1)) * ((adc_T >> 4) - ((int32_t)s_bme_cal.dig_T1))) >> 12) *
                    ((int32_t)s_bme_cal.dig_T3)) >> 14;
    s_bme_cal.t_fine = var1 + var2;
    *temp_c = ((s_bme_cal.t_fine * 5 + 128) >> 8) / 100.0f;

    int64_t p1 = ((int64_t)s_bme_cal.t_fine) - 128000;
    int64_t p2 = p1 * p1 * (int64_t)s_bme_cal.dig_P6;
    p2 = p2 + ((p1 * (int64_t)s_bme_cal.dig_P5) << 17);
    p2 = p2 + (((int64_t)s_bme_cal.dig_P4) << 35);
    p1 = ((p1 * p1 * (int64_t)s_bme_cal.dig_P3) >> 8) + ((p1 * (int64_t)s_bme_cal.dig_P2) << 12);
    p1 = (((((int64_t)1) << 47) + p1) * ((int64_t)s_bme_cal.dig_P1)) >> 33;
    if (p1 != 0) {
        int64_t p = 1048576 - adc_P;
        p = (((p << 31) - p2) * 3125) / p1;
        p1 = (((int64_t)s_bme_cal.dig_P9) * (p >> 13) * (p >> 13)) >> 25;
        p2 = (((int64_t)s_bme_cal.dig_P8) * p) >> 19;
        p = ((p + p1 + p2) >> 8) + (((int64_t)s_bme_cal.dig_P7) << 4);
        *press_hpa = (float)p / 25600.0f;
    }

    if (has_hum) {
        int32_t h = s_bme_cal.t_fine - 76800;
        h = (((((adc_H << 14) - (((int32_t)s_bme_cal.dig_H4) << 20) - (((int32_t)s_bme_cal.dig_H5) * h)) + 16384) >> 15) *
             (((((((h * ((int32_t)s_bme_cal.dig_H6)) >> 10) * (((h * ((int32_t)s_bme_cal.dig_H3)) >> 11) + 32768)) >> 10) +
                2097152) * ((int32_t)s_bme_cal.dig_H2) + 8192) >> 14));
        h = h - (((((h >> 15) * (h >> 15)) >> 7) * ((int32_t)s_bme_cal.dig_H1)) >> 4);
        if (h < 0) h = 0;
        if (h > 419430400) h = 419430400;
        *hum_pct = (float)(h >> 12) / 1024.0f;
    }
    return true;
}

static bool init_scd40(void) {
    i2c_device_config_t cfg = {
        .dev_addr_length = I2C_ADDR_BIT_LEN_7,
        .device_address = SCD40_ADDR,
        .scl_speed_hz = I2C_FREQ_HZ,
    };
    if (i2c_master_bus_add_device(s_bus, &cfg, &s_dev_scd) != ESP_OK) return false;
    /* A warm ESP32 reset leaves the SCD40 in periodic mode, where it rejects a new start:
     * stop first (500 ms execution time), then start. */
    uint8_t cmd_stop[2] = {0x3F, 0x86};
    (void)i2c_master_transmit(s_dev_scd, cmd_stop, 2, I2C_XFER_MS);
    vTaskDelay(pdMS_TO_TICKS(500));
    uint8_t cmd_start[2] = {0x21, 0xB1};
    if (i2c_master_transmit(s_dev_scd, cmd_start, 2, I2C_XFER_MS) != ESP_OK) {
        i2c_master_bus_rm_device(s_dev_scd);
        s_dev_scd = NULL;
        return false;
    }
    ESP_LOGI(TAG, "SCD40 detected at 0x%02X", SCD40_ADDR);
    return true;
}

static bool read_scd40(float *co2_ppm, float *temp_c, float *hum_pct) {
    if (!s_dev_scd) return false;
    uint8_t cmd_rdy[2] = {0xE4, 0xB8};
    uint8_t rdy[3] = {0};
    /* SCD4x needs a STOP plus 1 ms execution time between command and read (no repeated start). */
    if (i2c_master_transmit(s_dev_scd, cmd_rdy, 2, I2C_XFER_MS) != ESP_OK) return false;
    vTaskDelay(pdMS_TO_TICKS(2));
    if (i2c_master_receive(s_dev_scd, rdy, 3, I2C_XFER_MS) != ESP_OK) return false;
    if (sensirion_crc8(rdy, 2) != rdy[2]) return false;
    if (((((uint16_t)rdy[0] << 8) | rdy[1]) & 0x07FFu) == 0) return false;

    uint8_t cmd_read[2] = {0xEC, 0x05};
    uint8_t data[9] = {0};
    if (i2c_master_transmit(s_dev_scd, cmd_read, 2, I2C_XFER_MS) != ESP_OK) return false;
    vTaskDelay(pdMS_TO_TICKS(2));
    if (i2c_master_receive(s_dev_scd, data, 9, I2C_XFER_MS) != ESP_OK) return false;
    if (sensirion_crc8(&data[0], 2) != data[2] ||
        sensirion_crc8(&data[3], 2) != data[5] ||
        sensirion_crc8(&data[6], 2) != data[8]) {
        return false;
    }
    uint16_t raw_co2 = ((uint16_t)data[0] << 8) | data[1];
    uint16_t raw_t   = ((uint16_t)data[3] << 8) | data[4];
    uint16_t raw_rh  = ((uint16_t)data[6] << 8) | data[7];
    *co2_ppm = (float)raw_co2;
    *temp_c  = -45.0f + 175.0f * ((float)raw_t / 65535.0f);
    *hum_pct = 100.0f * ((float)raw_rh / 65535.0f);
    return raw_co2 > 0;
}

static bool init_max30102(void) {
    i2c_device_config_t cfg = {
        .dev_addr_length = I2C_ADDR_BIT_LEN_7,
        .device_address = MAX30102_ADDR,
        .scl_speed_hz = I2C_FREQ_HZ,
    };
    if (i2c_master_bus_add_device(s_bus, &cfg, &s_dev_max) != ESP_OK) return false;
    uint8_t part_id = 0;
    if (reg_read(s_dev_max, 0xFF, &part_id, 1) != ESP_OK || part_id != 0x15) {
        i2c_master_bus_rm_device(s_dev_max);
        s_dev_max = NULL;
        return false;
    }
    reg_write(s_dev_max, 0x09, 0x40);
    vTaskDelay(pdMS_TO_TICKS(10));
    reg_write(s_dev_max, 0x08, 0x4F);
    reg_write(s_dev_max, 0x09, 0x03);
    reg_write(s_dev_max, 0x0A, 0x27);
    reg_write(s_dev_max, 0x0C, 0x24);
    reg_write(s_dev_max, 0x0D, 0x24);
    s_ppg_idx = 0;
    s_ppg_count = 0;
    ESP_LOGI(TAG, "MAX30102 detected at 0x%02X", MAX30102_ADDR);
    return true;
}

static bool poll_max30102(bool *finger_ok, float *hr_bpm, float *spo2_pct) {
    if (!s_dev_max) return false;
    uint8_t wr = 0, rd = 0;
    if (reg_read(s_dev_max, 0x04, &wr, 1) != ESP_OK) return false;
    if (reg_read(s_dev_max, 0x06, &rd, 1) != ESP_OK) return false;

    int avail = (int)((wr - rd) & 0x1F);
    if (avail > 8) avail = 8;
    for (int i = 0; i < avail; i++) {
        uint8_t raw[6] = {0};
        if (reg_read(s_dev_max, 0x07, raw, 6) != ESP_OK) return false;
        uint32_t red = (((uint32_t)raw[0] << 16) | ((uint32_t)raw[1] << 8) | raw[2]) & 0x3FFFFu;
        uint32_t ir  = (((uint32_t)raw[3] << 16) | ((uint32_t)raw[4] << 8) | raw[5]) & 0x3FFFFu;
        s_red_buf[s_ppg_idx] = red;
        s_ir_buf[s_ppg_idx]  = ir;
        s_ppg_idx = (s_ppg_idx + 1) % PPG_WIN;
        if (s_ppg_count < PPG_WIN) s_ppg_count++;
    }

    if (s_ppg_count < 30) {
        *finger_ok = false;
        return true;
    }

    double ir_sum = 0.0, red_sum = 0.0;
    uint32_t ir_min = UINT32_MAX, ir_max = 0, red_min = UINT32_MAX, red_max = 0;
    for (int i = 0; i < s_ppg_count; i++) {
        uint32_t ir = s_ir_buf[i];
        uint32_t rd_v = s_red_buf[i];
        ir_sum += ir;
        red_sum += rd_v;
        if (ir < ir_min) ir_min = ir;
        if (ir > ir_max) ir_max = ir;
        if (rd_v < red_min) red_min = rd_v;
        if (rd_v > red_max) red_max = rd_v;
    }
    double ir_dc = ir_sum / s_ppg_count;
    double red_dc = red_sum / s_ppg_count;
    if (ir_dc < 50000.0) {
        *finger_ok = false;
        return true;
    }

    int peaks = 0;
    double thresh = ir_dc + (double)(ir_max - ir_min) * 0.2;
    bool above = false;
    int last_peak = -10;
    for (int i = 0; i < s_ppg_count; i++) {
        int idx = (s_ppg_idx - s_ppg_count + i + PPG_WIN) % PPG_WIN;
        double v = (double)s_ir_buf[idx];
        if (!above && v > thresh && (i - last_peak) >= 8) {
            peaks++;
            last_peak = i;
            above = true;
        } else if (above && v < ir_dc) {
            above = false;
        }
    }

    double win_sec = (double)s_ppg_count / 25.0;
    float bpm = (float)((peaks / win_sec) * 60.0);
    double r_num = ((double)(red_max - red_min)) / (red_dc > 1.0 ? red_dc : 1.0);
    double r_den = ((double)(ir_max - ir_min)) / (ir_dc > 1.0 ? ir_dc : 1.0);
    float spo2 = 98.0f;
    if (r_den > 1e-6) {
        double r = r_num / r_den;
        spo2 = (float)(110.0 - 25.0 * r);
    }
    if (spo2 > 100.0f) spo2 = 100.0f;
    if (spo2 < 70.0f) spo2 = 70.0f;

    if (bpm >= 40.0f && bpm <= 200.0f) {
        *finger_ok = true;
        *hr_bpm = bpm;
        *spo2_pct = spo2;
    } else {
        *finger_ok = false;
    }
    return true;
}

esp_err_t es_i2c_init(void) {
    s_snap_mu = xSemaphoreCreateMutex();
    i2c_master_bus_config_t bus_cfg = {
        .clk_source = I2C_CLK_SRC_DEFAULT,
        .i2c_port = I2C_NUM_0,
        .scl_io_num = EDGESPACE_I2C_SCL,
        .sda_io_num = EDGESPACE_I2C_SDA,
        .glitch_ignore_cnt = 7,
        .flags.enable_internal_pullup = true,
    };
    esp_err_t err = i2c_new_master_bus(&bus_cfg, &s_bus);
    if (err != ESP_OK) {
        ESP_LOGW(TAG, "i2c_new_master_bus failed (%s); continuing without I2C", esp_err_to_name(err));
        s_bus = NULL;
    }
    return ESP_OK;
}

void es_i2c_get_snapshot(es_sensor_snapshot_t *out) {
    if (!out) return;
    if (s_snap_mu) xSemaphoreTake(s_snap_mu, portMAX_DELAY);
    *out = s_snap;
    if (s_snap_mu) xSemaphoreGive(s_snap_mu);
}

void es_i2c_task(void *arg) {
    (void)arg;
    TickType_t last_probe = 0;

    for (;;) {
        if (!s_bus) {
            vTaskDelay(pdMS_TO_TICKS(5000));
            continue;
        }

        TickType_t now_tick = xTaskGetTickCount();
        if (last_probe == 0 || (now_tick - last_probe) >= pdMS_TO_TICKS(5000)) {
            last_probe = now_tick;
            if (!s_dev_bme) {
                bool hum = false;
                if ((i2c_master_probe(s_bus, BME280_ADDR_LOW, 20) == ESP_OK && init_bme280(BME280_ADDR_LOW, &hum)) ||
                    (i2c_master_probe(s_bus, BME280_ADDR_HIGH, 20) == ESP_OK && init_bme280(BME280_ADDR_HIGH, &hum))) {
                    xSemaphoreTake(s_snap_mu, portMAX_DELAY);
                    s_snap.has_bme280 = true;
                    s_snap.bme_has_humidity = hum;
                    s_snap.detected_mask |= PERIPH_BIT_BME280;
                    xSemaphoreGive(s_snap_mu);
                }
            }
            if (!s_dev_scd && i2c_master_probe(s_bus, SCD40_ADDR, 20) == ESP_OK && init_scd40()) {
                xSemaphoreTake(s_snap_mu, portMAX_DELAY);
                s_snap.has_scd40 = true;
                s_snap.detected_mask |= PERIPH_BIT_SCD40;
                xSemaphoreGive(s_snap_mu);
            }
            if (!s_dev_max && i2c_master_probe(s_bus, MAX30102_ADDR, 20) == ESP_OK && init_max30102()) {
                xSemaphoreTake(s_snap_mu, portMAX_DELAY);
                s_snap.has_max30102 = true;
                s_snap.detected_mask |= PERIPH_BIT_MAX30102;
                xSemaphoreGive(s_snap_mu);
            }
        }

        if (s_dev_bme) {
            float t = 0, p = 0, h = 0;
            bool has_hum = s_snap.bme_has_humidity;
            if (read_bme280(has_hum, &t, &p, &h)) {
                xSemaphoreTake(s_snap_mu, portMAX_DELAY);
                s_snap.temp_c = t;
                s_snap.pressure_hpa = p;
                if (has_hum) s_snap.humidity_pct = h;
                xSemaphoreGive(s_snap_mu);
            } else {
                ESP_LOGW(TAG, "BME280 unplugged at 0x%02X", s_bme_addr);
                i2c_master_bus_rm_device(s_dev_bme);
                s_dev_bme = NULL;
                xSemaphoreTake(s_snap_mu, portMAX_DELAY);
                s_snap.has_bme280 = false;
                s_snap.detected_mask &= (uint8_t)~PERIPH_BIT_BME280;
                xSemaphoreGive(s_snap_mu);
            }
        }

        if (s_dev_scd) {
            float co2 = 0, st = 0, sh = 0;
            if (read_scd40(&co2, &st, &sh)) {
                xSemaphoreTake(s_snap_mu, portMAX_DELAY);
                s_snap.co2_ppm = co2;
                s_snap.scd40_valid = true;
                if (!s_snap.has_bme280) {
                    s_snap.temp_c = st;
                    s_snap.humidity_pct = sh;
                }
                xSemaphoreGive(s_snap_mu);
            } else if (i2c_master_probe(s_bus, SCD40_ADDR, 20) != ESP_OK) {
                ESP_LOGW(TAG, "SCD40 unplugged");
                i2c_master_bus_rm_device(s_dev_scd);
                s_dev_scd = NULL;
                xSemaphoreTake(s_snap_mu, portMAX_DELAY);
                s_snap.has_scd40 = false;
                s_snap.scd40_valid = false;
                s_snap.detected_mask &= (uint8_t)~PERIPH_BIT_SCD40;
                xSemaphoreGive(s_snap_mu);
            }
        }

        if (s_dev_max) {
            bool finger = false;
            float bpm = 0, spo2 = 0;
            if (poll_max30102(&finger, &bpm, &spo2)) {
                xSemaphoreTake(s_snap_mu, portMAX_DELAY);
                s_snap.max30102_finger = finger;
                if (finger) {
                    s_snap.heart_rate_bpm = bpm;
                    s_snap.spo2_pct = spo2;
                }
                xSemaphoreGive(s_snap_mu);
            } else {
                ESP_LOGW(TAG, "MAX30102 unplugged");
                i2c_master_bus_rm_device(s_dev_max);
                s_dev_max = NULL;
                xSemaphoreTake(s_snap_mu, portMAX_DELAY);
                s_snap.has_max30102 = false;
                s_snap.max30102_finger = false;
                s_snap.detected_mask &= (uint8_t)~PERIPH_BIT_MAX30102;
                xSemaphoreGive(s_snap_mu);
            }
        }

        vTaskDelay(pdMS_TO_TICKS(100));
    }
}

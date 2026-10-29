/**
  ******************************************************************************
  * @file    rtt_logger.h
  * @author  YJSOFT
  * @brief   RTT Ultra-Fast Binary Logging Engine Core Macros & API.
  ******************************************************************************
  * @attention
  *
  * Copyright (c) YJSOFT. All rights reserved.
  * Contact: ansimple2000@naver.com
  *
  * This software is proprietary and confidential to YJSOFT.
  * Unauthorized copying, distribution, modification, or commercial use
  * of this software, in whole or in part, is strictly prohibited without
  * prior written permission from YJSOFT.
  *
  ******************************************************************************
  */

#ifndef _RTT_LOGGER_H_
#define _RTT_LOGGER_H_

/* Includes ------------------------------------------------------------------*/

#include <stdint.h>
#include <stddef.h>
#include <string.h>
#include "SEGGER_RTT.h"

#if __has_include("generated_rtt_keys.h")
#include "generated_rtt_keys.h"
#endif

#if defined(STM32H7RSxx) || defined(STM32H7S3xx)
  #include "stm32h7rsxx.h"
  #define GET_DWT_CYCCNT() (DWT->CYCCNT)
#elif defined(ARM_CM7) || defined(ARM_CM4) || defined(ARM_CM3)
  #include "core_cm7.h"
  #define GET_DWT_CYCCNT() (DWT->CYCCNT)
#else
  extern volatile uint32_t g_mock_dwt_cyccnt;
  #define GET_DWT_CYCCNT() (g_mock_dwt_cyccnt)
#endif


/* Exported constants --------------------------------------------------------*/

#define RTT_LOG_SYNC_BYTE           0xA5U         /**< @brief Frame sync byte marker. */
#define RTT_LOG_CHANNEL             1U            /**< @brief Dedicated RTT up-buffer channel. */

#ifndef RTT_CFG_ENABLE
  #define RTT_CFG_ENABLE            1U            /**< @brief Master enable switch (1: Enabled, 0: Disabled). */
#endif


/* Exported types ------------------------------------------------------------*/

/**
  * @brief 4-bit Type Code Definitions (0x0 ~ 0xF).
  */
typedef enum {
    TYPE_U32       = 0x0,                         /**< @brief 32-bit unsigned integer. */
    TYPE_I32       = 0x1,                         /**< @brief 32-bit signed integer. */
    TYPE_FLOAT     = 0x2,                         /**< @brief 32-bit IEEE-754 float. */
    TYPE_HEX8      = 0x3,                         /**< @brief 8-bit hex scalar. */
    TYPE_HEX16     = 0x4,                         /**< @brief 16-bit hex scalar. */
    TYPE_HEX32     = 0x5,                         /**< @brief 32-bit hex scalar. */
    TYPE_STR       = 0x6,                         /**< @brief Trailing string payload (literal and dynamic). */
    TYPE_HEX_ARR   = 0x7,                         /**< @brief Trailing raw byte array payload. */
    TYPE_CYC       = 0x8                          /**< @brief Hardware cycle counter scalar. */
} RttLogType_t;

#pragma pack(push, 1)
/**
  * @brief Packed 8-byte event frame header.
  */
typedef struct {
    uint8_t  sync;                                /**< @brief Frame sync marker (0xA5). */
    uint16_t event_id;                            /**< @brief Event identifier. */
    uint32_t timestamp;                           /**< @brief DWT CYCCNT hardware timestamp. */
    uint8_t  item_count;                          /**< @brief Number of KV slots in frame. */
} RttEventHeader_t;

/**
  * @brief Packed 6-byte KV wire slot item.
  */
typedef struct {
    uint16_t tag;                                 /**< @brief [15:12] Type Code | [11:0] Key ID. */
    union {
        uint32_t    u32;                          /**< @brief 32-bit scalar value. */
        int32_t     i32;                          /**< @brief 32-bit signed integer. */
        float       f32;                          /**< @brief 32-bit float value. */
        struct {
            uint16_t len;                         /**< @brief Trailing payload byte length. */
            uint16_t reserved;                    /**< @brief Reserved padding (0x0000). */
        } var;
    } val;
} RttLogItem_t;

/**
  * @brief Parameter descriptor used during log macro expansion.
  */
typedef struct {
    uint16_t    tag;                              /**< @brief Tag combining type code and key id. */
    uint16_t    len;                              /**< @brief Trailing byte count. */
    uint32_t    val;                              /**< @brief Direct 32-bit scalar value. */
    const void *buf_ptr;                          /**< @brief Pointer to trailing payload data. */
} RttLogParam_t;

/**
  * @brief Buffer reference descriptor for raw memory payloads.
  */
typedef struct {
    const void *ptr;                              /**< @brief Buffer memory address. */
    uint16_t    len;                              /**< @brief Buffer byte length. */
} RttRawBufRef_t;
#pragma pack(pop)


/* Exported macro ------------------------------------------------------------*/

#if (RTT_CFG_ENABLE == 1U)

/* C11 _Generic Type Dispatch Macro */
#define KV(k, v) _Generic((v), \
    float:              _rtt_slot_flt, \
    double:             _rtt_slot_dbl, \
    char:               _rtt_slot_i32, \
    signed char:        _rtt_slot_i32, \
    short:              _rtt_slot_i32, \
    int:                _rtt_slot_i32, \
    long:               _rtt_slot_i32, \
    long long:          _rtt_slot_i32, \
    unsigned char:      _rtt_slot_u32, \
    unsigned short:     _rtt_slot_u32, \
    unsigned int:       _rtt_slot_u32, \
    unsigned long:      _rtt_slot_u32, \
    unsigned long long: _rtt_slot_u32, \
    const char*:        _rtt_slot_str, \
    char*:              _rtt_slot_str, \
    default:            _rtt_slot_u32 \
)(KEY_ID_##k, (v))

/* Explicit Format Enforcers */
#define KV_HEX8(k, v)           _rtt_param_hex8(KEY_ID_##k, (uint32_t)(v))
#define KV_HEX16(k, v)          _rtt_param_hex16(KEY_ID_##k, (uint32_t)(v))
#define KV_HEX32(k, v)          _rtt_param_hex32(KEY_ID_##k, (uint32_t)(v))
#define KV_CYC(k, v)            _rtt_param_cyc(KEY_ID_##k, (uint32_t)(v))
#define KV_STR(k, v)            _rtt_param_str(KEY_ID_##k, (const char*)(v))
#define KV_FLASH_STR(k, v)      _rtt_param_str(KEY_ID_##k, (const char*)(v))
#define KV_DYN_STR(k, v)        _rtt_param_str(KEY_ID_##k, (const char*)(v))
#define KV_HEX_ARR(k, buf, len) _rtt_param_hex_arr(KEY_ID_##k, (const void*)(buf), (uint16_t)(len))

#define BUF_REF(buf, len)       _rtt_make_buf_ref((buf), (uint16_t)(len))

/* Logging Macro: All Variables & Unified Strings */
#define EVENT_LOG(evt_id, ...) do { \
    const RttLogParam_t _params[] = { __VA_ARGS__ }; \
    const uint8_t _cnt = (uint8_t)(sizeof(_params) / sizeof(_params[0])); \
    _rtt_log_send_params((uint16_t)(evt_id), _cnt, _params); \
} while(0)

/* Compatibility Wrapper */
#define EVENT_LOG_BUFS(evt_id, buf_array, ...) EVENT_LOG(evt_id, __VA_ARGS__)

#else

/* Zero-Byte Stub Definitions when RTT is disabled (RTT_CFG_ENABLE == 0) */
#define EVENT_LOG(...)                          ((void)0)
#define EVENT_LOG_BUFS(...)                     ((void)0)
#define KV(k, v)                                0
#define KV_HEX8(k, v)                           0
#define KV_HEX16(k, v)                          0
#define KV_HEX32(k, v)                          0
#define KV_CYC(k, v)                            0
#define KV_STR(k, v)                            0
#define KV_FLASH_STR(k, v)                      0
#define KV_HEX_ARR(k, len)                      0
#define KV_DYN_STR(k, len)                      0
#define BUF_REF(buf, len)                       { 0, 0 }

#endif /* RTT_CFG_ENABLE == 1U */


/* Exported functions --------------------------------------------------------*/

static inline RttLogParam_t _rtt_param_u32(uint16_t key_id, uint32_t v) {
    RttLogParam_t p;
    p.tag = (uint16_t)(((uint16_t)TYPE_U32 << 12) | (key_id & 0x0FFF));
    p.len = 0;
    p.val = v;
    p.buf_ptr = (void*)0;
    return p;
}

static inline RttLogParam_t _rtt_param_i32(uint16_t key_id, int32_t v) {
    RttLogParam_t p;
    p.tag = (uint16_t)(((uint16_t)TYPE_I32 << 12) | (key_id & 0x0FFF));
    p.len = 0;
    p.val = (uint32_t)v;
    p.buf_ptr = (void*)0;
    return p;
}

static inline RttLogParam_t _rtt_param_flt(uint16_t key_id, float v) {
    union { float f; uint32_t u; } cvt;
    cvt.f = v;
    RttLogParam_t p;
    p.tag = (uint16_t)(((uint16_t)TYPE_FLOAT << 12) | (key_id & 0x0FFF));
    p.len = 0;
    p.val = cvt.u;
    p.buf_ptr = (void*)0;
    return p;
}

static inline RttLogParam_t _rtt_param_hex8(uint16_t key_id, uint32_t v) {
    RttLogParam_t p;
    p.tag = (uint16_t)(((uint16_t)TYPE_HEX8 << 12) | (key_id & 0x0FFF));
    p.len = 0;
    p.val = v & 0xFFU;
    p.buf_ptr = (void*)0;
    return p;
}

static inline RttLogParam_t _rtt_param_hex16(uint16_t key_id, uint32_t v) {
    RttLogParam_t p;
    p.tag = (uint16_t)(((uint16_t)TYPE_HEX16 << 12) | (key_id & 0x0FFF));
    p.len = 0;
    p.val = v & 0xFFFFU;
    p.buf_ptr = (void*)0;
    return p;
}

static inline RttLogParam_t _rtt_param_hex32(uint16_t key_id, uint32_t v) {
    RttLogParam_t p;
    p.tag = (uint16_t)(((uint16_t)TYPE_HEX32 << 12) | (key_id & 0x0FFF));
    p.len = 0;
    p.val = v;
    p.buf_ptr = (void*)0;
    return p;
}

static inline RttLogParam_t _rtt_param_cyc(uint16_t key_id, uint32_t cyc) {
    RttLogParam_t p;
    p.tag = (uint16_t)(((uint16_t)TYPE_CYC << 12) | (key_id & 0x0FFF));
    p.len = 0;
    p.val = cyc;
    p.buf_ptr = (void*)0;
    return p;
}

static inline RttLogParam_t _rtt_param_str(uint16_t key_id, const char *s) {
    uint16_t len = 0;
    if (s != (void*)0) {
        while (s[len] != '\0') {
            len++;
        }
    }
    RttLogParam_t p;
    p.tag = (uint16_t)(((uint16_t)TYPE_STR << 12) | (key_id & 0x0FFF));
    p.len = len;
    p.val = 0;
    p.buf_ptr = (const void*)s;
    return p;
}

static inline RttLogParam_t _rtt_param_hex_arr(uint16_t key_id, const void *buf, uint16_t len) {
    RttLogParam_t p;
    p.tag = (uint16_t)(((uint16_t)TYPE_HEX_ARR << 12) | (key_id & 0x0FFF));
    p.len = len;
    p.val = 0;
    p.buf_ptr = buf;
    return p;
}

static inline RttRawBufRef_t _rtt_make_buf_ref(const void *buf, uint16_t len) {
    RttRawBufRef_t ref;
    ref.ptr = buf;
    ref.len = len;
    return ref;
}

/* Dispatch target functions for C11 _Generic */
static inline RttLogParam_t _rtt_slot_flt(uint16_t k, float v)        { return _rtt_param_flt(k, v); }
static inline RttLogParam_t _rtt_slot_dbl(uint16_t k, double v)       { return _rtt_param_flt(k, (float)v); }
static inline RttLogParam_t _rtt_slot_i32(uint16_t k, int32_t v)      { return _rtt_param_i32(k, v); }
static inline RttLogParam_t _rtt_slot_u32(uint16_t k, uint32_t v)     { return _rtt_param_u32(k, v); }
static inline RttLogParam_t _rtt_slot_str(uint16_t k, const char *v)  { return _rtt_param_str(k, v); }

/* Internal Stream Transmission Driver */
static inline void _rtt_log_send_params(uint16_t evt_id, uint8_t count, const RttLogParam_t *params) {
    RttEventHeader_t header;
    header.sync = (uint8_t)RTT_LOG_SYNC_BYTE;
    header.event_id = evt_id;
    header.timestamp = GET_DWT_CYCCNT();
    header.item_count = count;

    SEGGER_RTT_Write(RTT_LOG_CHANNEL, &header, sizeof(RttEventHeader_t));
    if (count > 0U) {
        RttLogItem_t wire_items[count];
        for (uint8_t i = 0; i < count; i++) {
            wire_items[i].tag = params[i].tag;
            if (params[i].buf_ptr != (void*)0) {
                wire_items[i].val.var.len = params[i].len;
                wire_items[i].val.var.reserved = 0;
            } else {
                wire_items[i].val.u32 = params[i].val;
            }
        }
        SEGGER_RTT_Write(RTT_LOG_CHANNEL, wire_items, (unsigned)(sizeof(RttLogItem_t) * count));

        for (uint8_t i = 0; i < count; i++) {
            if ((params[i].buf_ptr != (void*)0) && (params[i].len > 0U)) {
                SEGGER_RTT_Write(RTT_LOG_CHANNEL, params[i].buf_ptr, (unsigned)params[i].len);
            }
        }
    }
}

#endif /* _RTT_LOGGER_H_ */

/************************** (C) COPYRIGHT YJSOFT ****************END OF FILE****/

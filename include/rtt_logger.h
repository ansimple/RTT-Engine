#ifndef RTT_LOGGER_H_
#define RTT_LOGGER_H_

#include <stdint.h>
#include <stddef.h>
#include <string.h>
#include "SEGGER_RTT.h"

#if __has_include("generated_rtt_keys.h")
#include "generated_rtt_keys.h"
#endif

#if defined(STM32H7RSxx)
  #include "stm32h7rsxx.h"
  #define GET_DWT_CYCCNT() (DWT->CYCCNT)
#elif defined(ARM_CM7) || defined(ARM_CM4) || defined(ARM_CM3)
  #include "core_cm7.h"
  #define GET_DWT_CYCCNT() (DWT->CYCCNT)
#else
  /* Host / simulated environment mock */
  extern volatile uint32_t g_mock_dwt_cyccnt;
  #define GET_DWT_CYCCNT() (g_mock_dwt_cyccnt)
#endif

#define RTT_LOG_SYNC_BYTE 0xA5
#define RTT_LOG_CHANNEL   1

/* 4-bit Type Code Definitions (0x0 ~ 0xF) */
typedef enum {
    TYPE_U32       = 0x0,
    TYPE_I32       = 0x1,
    TYPE_FLOAT     = 0x2,
    TYPE_HEX8      = 0x3,
    TYPE_HEX16     = 0x4,
    TYPE_HEX32     = 0x5,
    TYPE_FLASH_STR = 0x6,
    TYPE_HEX_ARR   = 0x7,
    TYPE_DYN_STR   = 0x8,
    TYPE_CYC       = 0x9
} RttLogType_t;

#pragma pack(push, 1)
typedef struct {
    uint8_t  sync;
    uint16_t event_id;
    uint32_t timestamp;
    uint8_t  item_count;
} RttEventHeader_t;

typedef struct {
    uint16_t tag; /* [15:12] Type Code | [11:0] Key ID */
    union {
        uint32_t    u32;
        int32_t     i32;
        float       f32;
        uint32_t    str_addr; /* 32-bit Flash/ROM address */
        struct {
            uint16_t len;
            uint16_t reserved;
        } var;
    } val;
} RttLogItem_t;

typedef struct {
    const uint8_t *ptr;
    uint16_t len;
} RttRawBufRef_t;
#pragma pack(pop)

/* Inline Slot Construction Helpers (Zero-overhead when inlined) */
static inline RttLogItem_t _rtt_make_u32(uint16_t k, uint32_t v) {
    RttLogItem_t item;
    item.tag = (uint16_t)((TYPE_U32 << 12) | (k & 0x0FFF));
    item.val.u32 = v;
    return item;
}

static inline RttLogItem_t _rtt_make_i32(uint16_t k, int32_t v) {
    RttLogItem_t item;
    item.tag = (uint16_t)((TYPE_I32 << 12) | (k & 0x0FFF));
    item.val.i32 = v;
    return item;
}

static inline RttLogItem_t _rtt_make_flt(uint16_t k, float v) {
    RttLogItem_t item;
    item.tag = (uint16_t)((TYPE_FLOAT << 12) | (k & 0x0FFF));
    item.val.f32 = v;
    return item;
}

static inline RttLogItem_t _rtt_make_flash_str(uint16_t k, const char *v) {
    RttLogItem_t item;
    item.tag = (uint16_t)((TYPE_FLASH_STR << 12) | (k & 0x0FFF));
    item.val.str_addr = (uint32_t)(uintptr_t)v;
    return item;
}

static inline RttLogItem_t _rtt_make_hex8(uint16_t k, uint32_t v) {
    RttLogItem_t item;
    item.tag = (uint16_t)((TYPE_HEX8 << 12) | (k & 0x0FFF));
    item.val.u32 = (uint32_t)(v & 0xFF);
    return item;
}

static inline RttLogItem_t _rtt_make_hex16(uint16_t k, uint32_t v) {
    RttLogItem_t item;
    item.tag = (uint16_t)((TYPE_HEX16 << 12) | (k & 0x0FFF));
    item.val.u32 = (uint32_t)(v & 0xFFFF);
    return item;
}

static inline RttLogItem_t _rtt_make_hex32(uint16_t k, uint32_t v) {
    RttLogItem_t item;
    item.tag = (uint16_t)((TYPE_HEX32 << 12) | (k & 0x0FFF));
    item.val.u32 = v;
    return item;
}

static inline RttLogItem_t _rtt_make_cyc(uint16_t k, uint32_t v) {
    RttLogItem_t item;
    item.tag = (uint16_t)((TYPE_CYC << 12) | (k & 0x0FFF));
    item.val.u32 = v;
    return item;
}

static inline RttLogItem_t _rtt_make_hex_arr(uint16_t k, uint16_t len) {
    RttLogItem_t item;
    item.tag = (uint16_t)((TYPE_HEX_ARR << 12) | (k & 0x0FFF));
    item.val.var.len = len;
    item.val.var.reserved = 0;
    return item;
}

static inline RttLogItem_t _rtt_make_dyn_str(uint16_t k, uint16_t len) {
    RttLogItem_t item;
    item.tag = (uint16_t)((TYPE_DYN_STR << 12) | (k & 0x0FFF));
    item.val.var.len = len;
    item.val.var.reserved = 0;
    return item;
}

static inline RttRawBufRef_t _rtt_make_buf_ref(const void *buf, uint16_t len) {
    RttRawBufRef_t ref;
    ref.ptr = (const uint8_t*)buf;
    ref.len = len;
    return ref;
}

/* Dispatch target functions for C11 _Generic */
static inline RttLogItem_t _rtt_slot_flt(uint16_t k, float v)        { return _rtt_make_flt(k, v); }
static inline RttLogItem_t _rtt_slot_dbl(uint16_t k, double v)       { return _rtt_make_flt(k, (float)v); }
static inline RttLogItem_t _rtt_slot_i32(uint16_t k, int32_t v)      { return _rtt_make_i32(k, v); }
static inline RttLogItem_t _rtt_slot_u32(uint16_t k, uint32_t v)     { return _rtt_make_u32(k, v); }
static inline RttLogItem_t _rtt_slot_str(uint16_t k, const char *v)  { return _rtt_make_flash_str(k, v); }

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
#define KV_HEX8(k, v)      _rtt_make_hex8(KEY_ID_##k, (uint32_t)(v))
#define KV_HEX16(k, v)     _rtt_make_hex16(KEY_ID_##k, (uint32_t)(v))
#define KV_HEX32(k, v)     _rtt_make_hex32(KEY_ID_##k, (uint32_t)(v))
#define KV_CYC(k, v)       _rtt_make_cyc(KEY_ID_##k, (uint32_t)(v))
#define KV_STR(k, v)       _rtt_make_flash_str(KEY_ID_##k, (const char*)(v))
#define KV_FLASH_STR(k, v) _rtt_make_flash_str(KEY_ID_##k, (const char*)(v))

/* Variable Length Payloads (Hex Array, Dynamic String) */
#define KV_HEX_ARR(k, len) _rtt_make_hex_arr(KEY_ID_##k, (uint16_t)(len))
#define KV_DYN_STR(k, len) _rtt_make_dyn_str(KEY_ID_##k, (uint16_t)(len))

#define BUF_REF(buf, len)  _rtt_make_buf_ref((buf), (uint16_t)(len))

/* Internal Stream Transmission Driver */
static inline void _rtt_log_send_stream(uint16_t evt_id, uint8_t item_cnt, const RttLogItem_t *items,
                                        uint8_t buf_cnt, const RttRawBufRef_t *buffers) {
    RttEventHeader_t header = {
        .sync = RTT_LOG_SYNC_BYTE,
        .event_id = evt_id,
        .timestamp = GET_DWT_CYCCNT(),
        .item_count = item_cnt
    };

    SEGGER_RTT_Write(RTT_LOG_CHANNEL, &header, sizeof(RttEventHeader_t));
    if (item_cnt > 0) {
        SEGGER_RTT_Write(RTT_LOG_CHANNEL, items, sizeof(RttLogItem_t) * item_cnt);
    }
    for (uint8_t i = 0; i < buf_cnt; i++) {
        if (buffers[i].ptr && buffers[i].len > 0) {
            SEGGER_RTT_Write(RTT_LOG_CHANNEL, buffers[i].ptr, buffers[i].len);
        }
    }
}

/* Logging Macro 1: Scalar Variables */
#define EVENT_LOG(evt_id, ...) do { \
    const RttLogItem_t _items[] = { __VA_ARGS__ }; \
    const uint8_t _icnt = (uint8_t)(sizeof(_items) / sizeof(_items[0])); \
    _rtt_log_send_stream((uint16_t)(evt_id), _icnt, _items, 0, NULL); \
} while(0)

/* Logging Macro 2: Variable Array / String Trailing Buffers */
#define EVENT_LOG_BUFS(evt_id, buf_array, ...) do { \
    const RttLogItem_t _items[] = { __VA_ARGS__ }; \
    const uint8_t _icnt = (uint8_t)(sizeof(_items) / sizeof(_items[0])); \
    const RttRawBufRef_t _bufs[] = buf_array; \
    const uint8_t _bcnt = (uint8_t)(sizeof(_bufs) / sizeof(_bufs[0])); \
    _rtt_log_send_stream((uint16_t)(evt_id), _icnt, _items, _bcnt, _bufs); \
} while(0)

#endif /* RTT_LOGGER_H_ */

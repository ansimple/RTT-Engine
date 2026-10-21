#include "SEGGER_RTT.h"
#include <string.h>

#define RTT_MOCK_BUF_SIZE 65536

static uint8_t  s_channel1_buf[RTT_MOCK_BUF_SIZE];
static size_t   s_channel1_len = 0;

volatile uint32_t g_mock_dwt_cyccnt = 1000;

void SEGGER_RTT_Init(void) {
    s_channel1_len = 0;
}

unsigned SEGGER_RTT_Write(unsigned BufferIndex, const void* pBuffer, unsigned NumBytes) {
    if (BufferIndex != 1 || !pBuffer || NumBytes == 0) {
        return 0;
    }
    if (s_channel1_len + NumBytes > RTT_MOCK_BUF_SIZE) {
        /* Buffer full: simulate NO_BLOCK_SKIP */
        return 0;
    }
    memcpy(&s_channel1_buf[s_channel1_len], pBuffer, NumBytes);
    s_channel1_len += NumBytes;
    return NumBytes;
}

unsigned SEGGER_RTT_Read(unsigned BufferIndex, void* pBuffer, unsigned BufferSize) {
    (void)BufferIndex;
    (void)pBuffer;
    (void)BufferSize;
    return 0;
}

unsigned SEGGER_RTT_GetBytesInBuffer(unsigned BufferIndex) {
    if (BufferIndex == 1) {
        return (unsigned)s_channel1_len;
    }
    return 0;
}

int SEGGER_RTT_ConfigUpBuffer(unsigned BufferIndex, const char* sName, void* pBuffer, unsigned BufferSize, unsigned Flags) {
    (void)BufferIndex;
    (void)sName;
    (void)pBuffer;
    (void)BufferSize;
    (void)Flags;
    return 0;
}

const uint8_t* SEGGER_RTT_GetChannelBuffer(unsigned BufferIndex, size_t *out_len) {
    if (BufferIndex == 1) {
        if (out_len) *out_len = s_channel1_len;
        return s_channel1_buf;
    }
    if (out_len) *out_len = 0;
    return NULL;
}

void SEGGER_RTT_ClearChannelBuffer(unsigned BufferIndex) {
    if (BufferIndex == 1) {
        s_channel1_len = 0;
    }
}

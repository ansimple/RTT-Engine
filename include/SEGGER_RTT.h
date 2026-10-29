#ifndef SEGGER_RTT_H_
#define SEGGER_RTT_H_

#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

#define SEGGER_RTT_MODE_NO_BLOCK_SKIP         (0)
#define SEGGER_RTT_MODE_NO_BLOCK_TRIM         (1)
#define SEGGER_RTT_MODE_BLOCK_IF_FIFO_FULL    (2)

void     SEGGER_RTT_Init(void);
unsigned SEGGER_RTT_Write(unsigned BufferIndex, const void* pBuffer, unsigned NumBytes);
unsigned SEGGER_RTT_Read(unsigned BufferIndex, void* pBuffer, unsigned BufferSize);
unsigned SEGGER_RTT_GetBytesInBuffer(unsigned BufferIndex);
int      SEGGER_RTT_ConfigUpBuffer(unsigned BufferIndex, const char* sName, void* pBuffer, unsigned BufferSize, unsigned Flags);

/* Test / Inspection Helpers for Simulated Environment */
const uint8_t* SEGGER_RTT_GetChannelBuffer(unsigned BufferIndex, size_t *out_len);
void           SEGGER_RTT_ClearChannelBuffer(unsigned BufferIndex);

#ifdef __cplusplus
}
#endif

#endif /* SEGGER_RTT_H_ */

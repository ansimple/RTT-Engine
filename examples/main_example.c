#include <stdio.h>
#include <stdint.h>
#include <string.h>
#include "rtt_logger.h"

/* Module Event IDs */
// Pre-defined or will be assigned by pre-build scanner

static const char g_str_ready[] = "SYSTEM_READY";

void Process_System_State(void) {
    /* Example 3: Constant Flash/ROM String Logging (Zero-Copy 4-byte address)
     * Target transmits 32-bit Flash pointer address;
     * Host resolves to "STANDBY" and "SYSTEM_READY" solely via mapping.json without needing the binary!
     */
    EVENT_LOG(EVT_SYS_STATE,
        KV(state, "STANDBY"),
        KV_FLASH_STR(desc, g_str_ready)
    );
}

void Process_CAN_Message(void) {
    uint8_t payload[8] = { 0x11, 0x22, 0x33, 0x44, 0xAA, 0xBB, 0xCC, 0xDD };
    uint32_t start_cyc = GET_DWT_CYCCNT();

    /* Simulated CAN message processing algorithm */
    g_mock_dwt_cyccnt += 184;

    uint32_t elapsed_cyc = GET_DWT_CYCCNT() - start_cyc;

    /* Example 1: Logging with payload buffer and scalars (~1.0 us) */
    EVENT_LOG_BUFS(EVT_CAN_RX,
        { BUF_REF(payload, sizeof(payload)) },
        KV(channel, 1),
        KV_HEX16(std_id, 0x07E8),
        KV_HEX_ARR(data, sizeof(payload)),
        KV_CYC(exec_cyc, elapsed_cyc)
    );
}

void Process_Temperature_Loop(float current_temp) {
    char alert_msg[16] = "OVERHEAT";

    /* Example 2: C11 _Generic float deduction and dynamic string buffer */
    EVENT_LOG_BUFS(EVT_TEMP_CTRL,
        { BUF_REF(alert_msg, strlen(alert_msg)) },
        KV(temp, current_temp),       /* float deduction -> TYPE_FLOAT */
        KV(limit, 85),                /* int deduction -> TYPE_I32 */
        KV_DYN_STR(msg, strlen(alert_msg))
    );
}

int main(void) {
    SEGGER_RTT_Init();

    /* Set mock timestamp */
    g_mock_dwt_cyccnt = 5000000;

    Process_CAN_Message();
    Process_Temperature_Loop(87.420f);
    Process_System_State();

    size_t captured_len = 0;
    const uint8_t *captured_data = SEGGER_RTT_GetChannelBuffer(1, &captured_len);

    printf("RTT Channel 1 captured %zu bytes.\n", captured_len);

    /* Output binary dump to stdout if needed */
    FILE *fp = fopen("rtt_output.bin", "wb");
    if (fp) {
        fwrite(captured_data, 1, captured_len, fp);
        fclose(fp);
        printf("Saved binary stream to rtt_output.bin\n");
    }

    return 0;
}

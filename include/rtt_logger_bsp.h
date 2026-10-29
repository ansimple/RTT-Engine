/**
  ******************************************************************************
  * @file    rtt_logger_bsp.h
  * @author  YJSOFT
  * @brief   Board Support Package header for RTT binary logging hardware setup.
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

#ifndef _RTT_LOGGER_BSP_H_
#define _RTT_LOGGER_BSP_H_

/* Includes ------------------------------------------------------------------*/

#include <stdint.h>
#include <stdbool.h>


/* Exported constants --------------------------------------------------------*/

#ifndef RTT_CFG_ENABLE
  #define RTT_CFG_ENABLE            1U            /**< @brief Master enable flag (1: Enable, 0: Disable). */
#endif

#define RTT_BUFFER_BASE_ADDR        0x2407E000UL  /**< @brief RTT RAM base address in AXI SRAM. */
#define RTT_BUFFER_SIZE_BYTES       8192U         /**< @brief RTT RAM size (8KB). */


/* Exported types ------------------------------------------------------------*/


/* Exported macro ------------------------------------------------------------*/

#if (RTT_CFG_ENABLE == 0U)
/* =============================================================================
 * Zero-Byte Stub Macros when RTT logging is compiled out
 * ============================================================================= */
#define rtt_bsp_config_mpu()        ((uint32_t)0) /* FW_SUCCESS */
#define rtt_bsp_enable_dwt()        ((uint32_t)0) /* FW_SUCCESS */
#define rtt_bsp_is_initialized(out) (*(out) = false, (uint32_t)0)
#define rtt_logger_init()           ((uint32_t)0) /* FW_SUCCESS */
#endif


/* Exported functions --------------------------------------------------------*/

#if (RTT_CFG_ENABLE == 1U)
uint32_t rtt_bsp_config_mpu(void);
uint32_t rtt_bsp_enable_dwt(void);
uint32_t rtt_bsp_is_initialized(bool * const initialized);
uint32_t rtt_logger_init(void);
#endif

#endif /* _RTT_LOGGER_BSP_H_ */

/************************** (C) COPYRIGHT YJSOFT ****************END OF FILE****/

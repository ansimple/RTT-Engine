/**
  ******************************************************************************
  * @file    rtt_logger_bsp.c
  * @author  YJSOFT
  * @brief   Board Support Package implementation for RTT binary logging.
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

/* Includes ------------------------------------------------------------------*/

#include "rtt_logger_bsp.h"
#include "fw_error.h"
#include "SEGGER_RTT.h"
#include "stm32h7rsxx_ll_cortex.h"


#if (RTT_CFG_ENABLE == 1U)

/* Private constants ---------------------------------------------------------*/

#define RTT_MAGIC_COOKIE_LEN        10U  /**< @brief "SEGGER RTT" length including null terminator. */


/* Private types -------------------------------------------------------------*/


/* Private macro -------------------------------------------------------------*/


/* Private variables ---------------------------------------------------------*/


/* Private function prototypes -----------------------------------------------*/


/* Exported functions --------------------------------------------------------*/

/**
  * @brief  Configure MPU Region 9 for RTT buffer as Normal, Non-Cacheable.
  *
  * @note   Prevents L1 D-Cache incoherency during J-Link SWD direct RAM reads.
  *
  * @retval FW_SUCCESS  MPU region configured successfully.
  */
uint32_t rtt_bsp_config_mpu(void)
{
    LL_MPU_Disable();

    LL_MPU_ConfigRegion(
        LL_MPU_REGION_NUMBER9,
        0x00U,
        RTT_BUFFER_BASE_ADDR,
        LL_MPU_REGION_SIZE_8KB | LL_MPU_REGION_FULL_ACCESS |
        LL_MPU_TEX_LEVEL1 | LL_MPU_INSTRUCTION_ACCESS_DISABLE |
        LL_MPU_ACCESS_NOT_SHAREABLE | LL_MPU_ACCESS_NOT_CACHEABLE |
        LL_MPU_ACCESS_NOT_BUFFERABLE
    );

    LL_MPU_Enable(LL_MPU_CTRL_PRIVILEGED_DEFAULT);

    return FW_SUCCESS;
}


/**
  * @brief  Enable Cortex-M7 DWT Cycle Counter (CYCCNT) for hardware timestamps.
  *
  * @retval FW_SUCCESS  DWT cycle counter enabled.
  */
uint32_t rtt_bsp_enable_dwt(void)
{
    CoreDebug->DEMCR |= CoreDebug_DEMCR_TRCENA_Msk;
    DWT->CTRL |= DWT_CTRL_CYCCNTENA_Msk;

    return FW_SUCCESS;
}


/**
  * @brief  Check whether SEGGER RTT control block is already active in RAM.
  *
  * @param[out]  initialized  Pointer to boolean receiving check result.
  *
  * @retval FW_SUCCESS             Check completed.
  * @retval FW_ERROR_INVALID_PARAM initialized pointer is NULL.
  */
uint32_t rtt_bsp_is_initialized(bool * const initialized)
{
    if (initialized == NULL) {
        return FW_ERROR_INVALID_PARAM;
    }

    if ((_SEGGER_RTT.acID[0] == 'S') &&
        (_SEGGER_RTT.acID[1] == 'E') &&
        (_SEGGER_RTT.acID[2] == 'G') &&
        (_SEGGER_RTT.acID[3] == 'G') &&
        (_SEGGER_RTT.acID[4] == 'E') &&
        (_SEGGER_RTT.acID[5] == 'R')) {
        *initialized = true;
    } else {
        *initialized = false;
    }

    return FW_SUCCESS;
}


/**
  * @brief  Smart initialization of RTT logger across multi-stage boot jumps.
  *
  * @note   If RTT is already active (SS-BL or APP entry), preserves buffer pointers.
  *
  * @retval FW_SUCCESS  Initialization completed.
  */
uint32_t rtt_logger_init(void)
{
    bool is_active = false;
    uint32_t err;

    err = rtt_bsp_is_initialized(&is_active);
    if (err != FW_SUCCESS) {
        return err;
    }

    if (!is_active) {
        /* Cold reset (FS-BL): perform fresh initialization */
        SEGGER_RTT_Init();
    }

    return FW_SUCCESS;
}

#endif /* RTT_CFG_ENABLE == 1U */


/* Private functions ---------------------------------------------------------*/

/************************** (C) COPYRIGHT YJSOFT ****************END OF FILE****/

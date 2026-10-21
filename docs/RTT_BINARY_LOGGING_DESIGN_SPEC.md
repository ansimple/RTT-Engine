# RTT 기반 고속 바이너리 로깅 및 펌웨어 테스트 프레임워크 설계서

| 문서 버전 | 작성 일자 | 대상 타깃 | 상태 |
| :---: | :---: | :---: | :---: |
| v1.0.0 | 2026-10-21 | ARM Cortex-M7 (STM32H7RS 시리즈 및 범용 Cortex-M) | 확정 (Approved) |

---

## 목차
1. [개요 및 설계 목적](#1-개요-및-설계-목적)
   - 1.1 배경 및 기존 방식의 한계
   - 1.2 핵심 설계 목표
   - 1.3 주요 성능 지표 요약
2. [전체 시스템 아키텍처](#2-전체-시스템-아키텍처)
   - 2.1 엔드투엔드 데이터 파이프라인
   - 2.2 계층별 역할 및 상호작용
3. [통신 패킷 프로토콜 명세](#3-통신-패킷-프로토콜-명세)
   - 3.1 패킷 프레임 레이아웃
   - 3.2 패킷 필드 정의
   - 3.3 Key-Value 슬롯 비트 구조 (6 Bytes)
   - 3.4 데이터 타입(Type Code) 정의 및 포맷 힌트
   - 3.5 가변 길이 트레일링 페이로드 (Trailing Payload) 배치 규칙
4. [타깃 펌웨어 구현 명세 (C11 / STM32H7RS)](#4-타깃-펌웨어-구현-명세-c11--stm32h7rs)
   - 4.1 핵심 헤더 (`rtt_logger.h`) 설계
   - 4.2 C11 `_Generic` 타입 디스패치 매크로
   - 4.3 Cortex-M7 하드웨어 최적화 및 D-Cache 코히런시
   - 4.4 MPU Non-Cacheable 영역 구성 가이드
   - 4.5 재진입성(Reentrancy) 및 ISR 안전성
5. [프리 컴파일(Pre-build) 자동화 파이프라인](#5-프리-컴파일pre-build-자동화-파이프라인)
   - 5.1 소스 스캐너 (`gen_rtt_framework.py`) 구조
   - 5.2 키 식별자 헤더 (`generated_rtt_keys.h`) 생성 규칙
   - 5.3 디코딩 메타데이터 (`mapping.json`) 스키마
   - 5.4 CMake 및 Makefile 빌드 시스템 통합
6. [호스트 UI 프레임워크 연동 및 디코딩 명세](#6-호스트-ui-프레임워크-연동-및-디코딩-명세)
   - 6.1 프레임 동기화 및 패킷 파싱 파이프라인
   - 6.2 호스트 어댑터 (`host_rtt_adapter.py`) 구현
   - 6.3 텍스트 합성기 (Text Synthesizer) 및 하위 호환성 보장
7. [실무 코드 작성 및 검증 예시](#7-실무-코드-작성-및-검증-예시)
   - 7.1 기본 변수 및 단일 이벤트 로깅
   - 7.2 가변 헥사 버퍼 및 동적 문자열 로깅
   - 7.3 DWT 사이클 프로파일링 연계
   - 7.4 호스트 UI 출력 복원 결과 비교
8. [기대 효과 및 결론](#8-기대-효과-및-결론)
9. [부록: 확장 및 신뢰성 고려사항](#9-부록-확장-및-신뢰성-고려사항)

---

## 1. 개요 및 설계 목적

### 1.1 배경 및 기존 방식의 한계
임베디드 펌웨어 및 실시간 시스템 디버깅/검증 환경에서는 이벤트 추적 및 상태 모니터링을 위해 `[모듈:이벤트] key=value ...` 형태의 텍스트 기반 로깅 방식이 널리 채택되어 왔습니다. 이 형식은 사람이 읽기 쉽고(Human-readable), 기구축된 호스트 UI 테스트 자동화 엔진(시간차 측정, 정규식 기반 판정, Key-Value 범위 판정)과의 연동이 직관적이라는 장점을 지닙니다.

그러나 MCU 타깃 환경에서 텍스트 기반 포맷팅 로깅은 심각한 실시간성 저하를 유발합니다:
1. **타깃 연산 오버헤드 (`vsnprintf` 병목)**: 타깃 MCU 내부에서 가변 인자 구문 분석, 10진수/16진수 문자열 변환 나눗셈/나머지 연산, 버퍼 복사 등이 발생하여 단일 로그 호출당 **$50 \sim 150\,\mu\text{s}$**의 지연이 발생합니다.
2. **타이밍 왜곡 및 하이젠버그 (Heisenbug)**: 수십 $\mu\text{s}$ 이상의 지연 시간은 실시간 제어 루프(FOC, PID 제어 등)와 고주파 인터럽트 서비스 루틴(ISR)의 데드라인을 침범하며, DWT(Data Watchpoint and Trace) 기반 실행 사이클 벤치마크의 정확도를 왜곡합니다. 로깅 코드를 삽입하면 버그가 사라지거나 반대로 비정상 동작이 유발되는 현상이 발생합니다.
3. **대역폭 낭비 및 버퍼 오버플로우**: 반복되는 ASCII 키 이름(예: `channel=`, `temperature=`), 공백 문자, 브래킷 등으로 인해 1개 이벤트당 $60 \sim 100$ 바이트의 대역폭이 소모되며, SEGGER RTT 링 버퍼의 조기 포화 및 패킷 드롭을 유발합니다.

### 1.2 핵심 설계 목표
본 프레임워크는 **컴파일 타임 정적 분석**, **C11 `_Generic` 기반 타입 디스패치**, 그리고 **SEGGER RTT 초경량 바이너리 스트리밍**을 결합하여 다음 세 가지 핵심 목표를 달성합니다:

- **타깃 연산 극소화 (Zero-Formatting)**: MCU 내부의 문자열 포맷팅 및 변환 연산을 완전히 배제하고, 고정 슬롯과 원시 바이트 메모리 복사($0.2 \sim 1.5\,\mu\text{s}$, STM32H7RS 600MHz 기준 약 $120 \sim 900$ 사이클) 수준으로 단축합니다.
- **개발 생산성 유지 (Zero-Registration)**: 펌웨어 엔지니어는 소스 코드 작성 시 별도의 ID 수동 등록 없이 직관적인 Key 이름과 변수를 자유롭게 작성할 수 있으며, C11 `_Generic` 매크로를 통해 컴파일 타임에 타입이 자동 추론됩니다.
- **호스트 UI 하위 호환성 100% 보장 (Drop-in Replacement)**: 호스트 수신 어댑터가 바이너리 패킷을 파싱하여 기존 규격인 `[모듈:이벤트] key=value ...` 포맷의 텍스트로 즉각 복원하므로, 기구축된 UI 자동화 엔진을 수정 없이 그대로 운용할 수 있습니다.

### 1.3 주요 성능 지표 요약

| 비교 항목 | 기존 텍스트 로깅 (`vsnprintf` 기반) | 본 고속 바이너리 로깅 프레임워크 | 개선 효과 |
| :--- | :---: | :---: | :---: |
| **호출당 실행 지연** | $50 \sim 150\,\mu\text{s}$ | **$0.2 \sim 1.5\,\mu\text{s}$** | **약 98% 지연 시간 단축** |
| **타깃 MCU CPU 사이클 (600MHz)** | $30,000 \sim 90,000$ Cycles | **$120 \sim 900$ Cycles** | 초정밀 실시간 제어 루프 영향 배제 |
| **단일 이벤트 전송 크기** | $60 \sim 100$ Bytes (ASCII) | **$14 \sim 26$ Bytes (Binary)** | **대역폭 소모 약 75% 절감** |
| **D-Cache 일관성 보장** | 미보장 (소프트웨어 플러시 필요) | **MPU Non-Cacheable + D2 SRAM 전용 배치** | SWD Background Direct Read 무결성 확보 |
| **호스트 UI 파서 호환성** | 기준 포맷 | **100% 동일 텍스트 합성 지원** | 기존 UI 테스트 스크립트 무수정 재사용 |

---

## 2. 전체 시스템 아키텍처

### 2.1 엔드투엔드 데이터 파이프라인

```
┌────────────────────────────────────────────────────────────────────────┐
│ [1. Pre-build / 빌드 파이프라인]                                      │
│                                                                        │
│   펌웨어 C 소스 코드 (*.c, *.h)                                        │
│          │                                                             │
│          ▼ Python 스캐너 (gen_rtt_framework.py)                        │
│          ├───────────────────────────────┐                             │
│          ▼                               ▼                             │
│   generated_rtt_keys.h            mapping.json                         │
│   (컴파일용 Key ID 정의)          (호스트 UI 디코딩용 DB)              │
│          │                               │                             │
│          ▼ GCC (C11, -std=c11)           │                             │
│   firmware.elf / firmware.bin            │                             │
└──────────┬───────────────────────────────┼─────────────────────────────┘
           │ Flashing                      │ Loading
           ▼                               ▼
┌───────────────────────────┐     ┌──────────────────────────────────────┐
│ [2. 타깃 런타임 (MCU)]    │     │ [3. 호스트 UI 테스트 프레임워크]     │
│                           │     │                                      │
│ EVENT_LOG(...) 호출       │     │ J-Link RTT Stream 수신               │
│   ├─ C11 _Generic 타입식별│     │   │                                  │
│   ├─ DWT 사이클 타임스탬프│     │   ▼ Binary Packet Parser             │
│   └─ 고정 슬롯 + 가변 꼬리│     │   ├─ 0xA5 Sync 바이트 동기화         │
│          │                │     │   ├─ Event ID / Key ID 매핑 (JSON)   │
│          ▼ Direct Write   │     │   ├─ Type 필드별 포맷 역직렬화       │
│ SEGGER RTT Ring Buffer    │     │   └─ 가변 헥사/문자열 오프셋 슬라이싱│
│ (Channel 1, Non-Cacheable)│     │          │                           │
└──────────┬────────────────┘     │          ▼ Text Synthesizer          │
           │                      │ "[MODULE:EVENT] key=val key=\"...\"" │
           │ SWD Background Access│          │                           │
           └─────────────────────►│          ▼ 기존 UI 테스트 엔진       │
                                  │ (태그 간 시간차, DWT 사이클 판정,   │
                                  │  Key 값 범위 검증 등)                │
                                  └──────────────────────────────────────┘
```

### 2.2 계층별 역할 및 상호작용
1. **Pre-build 스캐너 레이어 (`gen_rtt_framework.py`)**:
   - 빌드 직전 소스 트리를 스캔하여 `EVENT_LOG*` 및 `KV*` 매크로 호출을 탐색합니다.
   - Key 이름 및 이벤트 식별자를 고유 번호로 인덱싱하여 C 헤더(`generated_rtt_keys.h`)와 호스트 메타데이터(`mapping.json`)를 동기 생성합니다.
2. **타깃 런타임 레이어 (`rtt_logger.h`)**:
   - C11 `_Generic`을 통해 인자 타입을 컴파일 타임에 분기하고 6바이트 정형 슬롯을 스택에 구성합니다.
   - 0xA5 매직 바이트, DWT 클록 카운터 타임스탬프, 슬롯 데이터 및 가변 페이로드를 SEGGER RTT 버퍼(채널 1)로 연속 전송합니다.
3. **호스트 디코더 레이어 (`host_rtt_adapter.py`)**:
   - J-Link RTT 통신 채널로부터 원시 바이트 스트림을 수신하고 0xA5 동기화 바이트를 기준으로 프레임을 정렬합니다.
   - `mapping.json`을 참조하여 Event ID 및 Key ID를 실제 문자열 심볼로 복원하고 기존 UI 엔진이 인식하는 ASCII 텍스트로 합성합니다.

---

## 3. 통신 패킷 프로토콜 명세

패킷은 **고정 크기 헤더(8B)**, **고정 크기 Key-Value 슬롯 배열(개당 6B, $N \times 6\text{B}$)**, 그리고 가변 길이 데이터가 순차 배치되는 **가변 데이터 꼬리(Trailing Payload, $M\text{B}$)**로 구성됩니다.

### 3.1 패킷 프레임 레이아웃

```
┌───────────┬──────────────┬──────────────────┬────────────┬─────────────────────────────┬───────────────────────────┐
│ Sync Byte │ Event ID     │ HW Timestamp     │ Item Count │ Key-Value Slots (N x 6B)    │ Trailing Payload (가변B)  │
│ 0xA5 (1B) │ uint16_t(2B) │ DWT->CYCCNT (4B) │ uint8_t(1B)│ [Tag 2B][Raw Value 4B] x N  │ Raw Hex Buffers / Strings │
└───────────┴──────────────┴──────────────────┴────────────┴─────────────────────────────┴───────────────────────────┘
```

### 3.2 패킷 필드 정의

| 필드명 | 오프셋 (Byte) | 크기 (Bytes) | 자료형 | 설명 |
| :--- | :---: | :---: | :---: | :--- |
| **Sync Byte** | 0 | 1 | `uint8_t` | 고정 매직 바이트 (`0xA5`). 패킷 유실 시 프레임 경계 재동기화에 사용 |
| **Event ID** | 1 | 2 | `uint16_t` | `[모듈:이벤트]`를 식별하는 16비트 정수 식별자 (Pre-build 단계 자동 할당) |
| **HW Timestamp** | 3 | 4 | `uint32_t` | 타깃 MCU의 하드웨어 타이머 (`DWT->CYCCNT`, 1 CPU 사이클 정밀도) |
| **Item Count** | 7 | 1 | `uint8_t` | 뒤따라오는 Key-Value 슬롯의 개수 ($N \le 255$) |
| **Key-Value Slots** | 8 | $N \times 6$ | `RttLogItem_t[]` | 고정 6바이트 슬롯의 연속 배열 (Tag 2B + Value 4B) |
| **Trailing Payload** | $8 + 6N$ | 가변 ($M$) | `uint8_t[]` | `HEX_ARR`, `DYN_STR` 등의 원시 바이트 덤프 영역 |

### 3.3 Key-Value 슬롯 비트 구조 (6 Bytes)

```
┌──────────────────────────────────────┬──────────────────────────────────────────────────┐
│          Tag (uint16_t, 2 Bytes)     │             Value (union, 4 Bytes)               │
├──────────────────┬───────────────────┼──────────────────────────────────────────────────┤
│ Type Code (4bit) │ Key ID (12bit)    │ uint32 / int32 / float / str_ptr / {len, rsvd}   │
│ [15:12]          │ [11:0]            │ [31:0]                                           │
└──────────────────┴───────────────────┴──────────────────────────────────────────────────┘
```

- **Tag 상위 4비트 (`Tag[15:12]`)**: 데이터 타입 및 호스트 표출 포맷 힌트 (0 ~ 15)
- **Tag 하위 12비트 (`Tag[11:0]`)**: 컴파일 타임에 생성된 Key 인덱스 번호 (최대 4,096개 지원: 0 ~ 4095)
- **Value (4 Bytes, 32-bit Union)**:
  - 단일 값: 정수, 부동소수점, 또는 Flash 문자열 주소의 원시 32비트 비트열.
  - 가변 길이 타입 (`TYPE_HEX_ARR`, `TYPE_DYN_STR`): 하위 16비트에 꼬리 영역의 데이터 바이트 길이(`len`)를 저장.

### 3.4 데이터 타입(Type Code) 정의 및 포맷 힌트

| Type Code | 열거형 심볼 | 페이로드 위치 | 원시 비트 크기 | 호스트 표출 서식 | 설명 |
| :---: | :--- | :---: | :---: | :--- | :--- |
| `0x0` | `TYPE_U32` | 슬롯 (Value) | 4 Bytes | `%u` | 32비트 부호 없는 정수 |
| `0x1` | `TYPE_I32` | 슬롯 (Value) | 4 Bytes | `%d` | 32비트 부호 있는 정수 |
| `0x2` | `TYPE_FLOAT` | 슬롯 (Value) | 4 Bytes | `%.3f` | IEEE-754 32비트 단정밀도 부동소수점 |
| `0x3` | `TYPE_HEX8` | 슬롯 (Value) | 4 Bytes | `0x%02X` | 8비트 16진수 표기 (하위 8비트 유효) |
| `0x4` | `TYPE_HEX16` | 슬롯 (Value) | 4 Bytes | `0x%04X` | 16비트 16진수 표기 (하위 16비트 유효) |
| `0x5` | `TYPE_HEX32` | 슬롯 (Value) | 4 Bytes | `0x%08X` | 32비트 16진수 표기 |
| `0x6` | `TYPE_FLASH_STR` | 슬롯 (Value) | 4 Bytes | `"%s"` | Flash/ROM 메모리 상주 문자열 포인터 주소 |
| `0x7` | `TYPE_HEX_ARR` | Trailing 꼬리 | $K$ Bytes | `"AABBCCD..."` | 가변 길이 바이트 배열 (슬롯 Value에 $K$ 기록) |
| `0x8` | `TYPE_DYN_STR` | Trailing 꼬리 | $K$ Bytes | `"text"` | 동적 버퍼/RAM 문자열 (슬롯 Value에 $K$ 기록) |
| `0x9` | `TYPE_CYC` | 슬롯 (Value) | 4 Bytes | `%u` | DWT 실행 사이클 전용 측정값 |

### 3.5 가변 길이 트레일링 페이로드 (Trailing Payload) 배치 규칙
1. 슬롯 배열 내에 `TYPE_HEX_ARR` 또는 `TYPE_DYN_STR`로 지정된 아이템이 선언된 순서대로, Trailing 영역에 바이트 데이터가 연속 배치됩니다.
2. 각 가변 데이터의 크기 $L_i$는 해당 슬롯의 `val.var.len`에 명시됩니다.
3. 호스트 디코더는 슬롯을 순회하면서 가변 슬롯을 만날 때마다 현재 `trailing_offset` 위치에서 $L_i$ 바이트만큼 슬라이싱하여 복원합니다.

---

## 4. 타깃 펌웨어 구현 명세 (C11 / STM32H7RS)

### 4.1 핵심 헤더 (`rtt_logger.h`) 설계

```c
#ifndef RTT_LOGGER_H_
#define RTT_LOGGER_H_

#include <stdint.h>
#include <stddef.h>
#include <string.h>
#include "SEGGER_RTT.h"
#include "generated_rtt_keys.h"

#if defined(STM32H7RSxx)
  #include "stm32h7rsxx.h"
  #define GET_DWT_CYCCNT() (DWT->CYCCNT)
#elif defined(ARM_CM7) || defined(ARM_CM4) || defined(ARM_CM3)
  #include "core_cm7.h"
  #define GET_DWT_CYCCNT() (DWT->CYCCNT)
#else
  #define GET_DWT_CYCCNT() (0U)
#endif

#define RTT_LOG_SYNC_BYTE 0xA5
#define RTT_LOG_CHANNEL   1

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
    uint16_t tag; // [15:12] Type Code | [11:0] Key ID
    union {
        uint32_t    u32;
        int32_t     i32;
        float       f32;
        uint32_t    str_addr; // 32-bit Flash/ROM 주소
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
```

### 4.2 C11 `_Generic` 타입 디스패치 매크로

인라인 슬롯 빌더 및 C11 `_Generic`을 통해 컴파일 타임에 타입 코드를 결정합니다. 컴파일러 최적화(-O2, -O3, -Os) 적용 시 추가 함수 호출 오버헤드 없이 인라인 어셈블리 명령 1~2개로 압축됩니다. 특히 포인터와 산술 타입 간 컴파일 타임 캐스팅 충돌을 방지하기 위해 타입별 인라인 디스패치 함수를 거쳐 호출됩니다.

```c
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

// C11 _Generic 디스패치 타깃 함수군
static inline RttLogItem_t _rtt_slot_flt(uint16_t k, float v)        { return _rtt_make_flt(k, v); }
static inline RttLogItem_t _rtt_slot_dbl(uint16_t k, double v)       { return _rtt_make_flt(k, (float)v); }
static inline RttLogItem_t _rtt_slot_i32(uint16_t k, int32_t v)      { return _rtt_make_i32(k, v); }
static inline RttLogItem_t _rtt_slot_u32(uint16_t k, uint32_t v)     { return _rtt_make_u32(k, v); }
static inline RttLogItem_t _rtt_slot_str(uint16_t k, const char *v)  { return _rtt_make_flash_str(k, v); }

// C11 _Generic 자동 타입 분기 매크로 (함수 포인터 선택 후 인자 전달)
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

// 명시적 16진수 및 사이클 전용 매크로
#define KV_HEX8(k, v)      _rtt_make_hex8(KEY_ID_##k, (uint32_t)(v))
#define KV_HEX16(k, v)     _rtt_make_hex16(KEY_ID_##k, (uint32_t)(v))
#define KV_HEX32(k, v)     _rtt_make_hex32(KEY_ID_##k, (uint32_t)(v))
#define KV_CYC(k, v)       _rtt_make_cyc(KEY_ID_##k, (uint32_t)(v))

// 가변 배열 및 동적 문자열 기술 매크로
#define KV_HEX_ARR(k, len) _rtt_make_hex_arr(KEY_ID_##k, (uint16_t)(len))
#define KV_DYN_STR(k, len) _rtt_make_dyn_str(KEY_ID_##k, (uint16_t)(len))
#define BUF_REF(buf, len)  _rtt_make_buf_ref((buf), (uint16_t)(len))

// 전송 드라이버 루틴
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

// 1. 기본 인자 로깅 매크로
#define EVENT_LOG(evt_id, ...) do { \
    const RttLogItem_t _items[] = { __VA_ARGS__ }; \
    const uint8_t _icnt = (uint8_t)(sizeof(_items) / sizeof(_items[0])); \
    _rtt_log_send_stream(evt_id, _icnt, _items, 0, NULL); \
} while(0)

// 2. 가변 버퍼 페이로드 결합 로깅 매크로
#define EVENT_LOG_BUFS(evt_id, buf_array, ...) do { \
    const RttLogItem_t _items[] = { __VA_ARGS__ }; \
    const uint8_t _icnt = (uint8_t)(sizeof(_items) / sizeof(_items[0])); \
    const RttRawBufRef_t _bufs[] = buf_array; \
    const uint8_t _bcnt = (uint8_t)(sizeof(_bufs) / sizeof(_bufs[0])); \
    _rtt_log_send_stream(evt_id, _icnt, _items, _bcnt, _bufs); \
} while(0)

#endif /* RTT_LOGGER_H_ */
```

### 4.3 Cortex-M7 하드웨어 최적화 및 D-Cache 코히런시
STM32H7RS와 같은 Cortex-M7 코어는 L1 Data Cache(D-Cache, 16KB/32KB)와 Store Buffer를 탑재하고 있습니다. 일반적인 메모리 구성에서는 CPU 코어가 RTT 링 버퍼에 데이터를 기록하더라도 D-Cache 라인에 머물러 실제 물리 SRAM에 즉시 반영되지 않을 수 있습니다.
J-Link 디버거 프로브는 SWD 인터페이스의 DAP(Debug Access Port)를 통해 시스템 버스(AXI/AHB)를 경유하여 물리 SRAM을 직접 읽어들이므로, 캐시 플러시(`SCB_CleanDCache`)를 누락하면 오래된 데이터를 읽거나 데이터 오염이 발생합니다.

매 로깅마다 캐시 플러시 명령을 수행하면 수십 사이클의 페널티가 발생하므로, **RTT 제어 블록 및 채널 버퍼 전용 메모리 영역을 MPU를 통해 `Non-Cacheable`로 지정**하는 아키텍처를 적용합니다.

### 4.4 MPU Non-Cacheable 영역 구성 가이드
링 버퍼를 전용 링커 섹션(`.rtt_buf_section`)에 배치하고, 해당 영역에 대해 MPU 설정을 적용합니다.

```c
void MPU_Config_RTT_Region(void) {
    MPU_Region_InitTypeDef MPU_InitStruct = {0};
    HAL_MPU_Disable();

    // Region 7: RTT Buffer 전용 32KB 영역 (Normal Memory, Non-Cacheable)
    MPU_InitStruct.Enable = MPU_REGION_ENABLE;
    MPU_InitStruct.Number = MPU_REGION_NUMBER7;
    MPU_InitStruct.BaseAddress = 0x24000000; // AXI-SRAM D2 전용 오프셋
    MPU_InitStruct.Size = MPU_REGION_SIZE_32KB;
    MPU_InitStruct.SubRegionDisable = 0x00;
    MPU_InitStruct.TypeExtField = MPU_TEX_LEVEL1;
    MPU_InitStruct.AccessPermission = MPU_REGION_FULL_ACCESS;
    MPU_InitStruct.DisableExec = MPU_INSTRUCTION_ACCESS_DISABLE;
    MPU_InitStruct.IsShareable = MPU_ACCESS_NOT_SHAREABLE;
    MPU_InitStruct.IsCacheable = MPU_ACCESS_NOT_CACHEABLE;   // 캐시 우회
    MPU_InitStruct.IsBufferable = MPU_ACCESS_NOT_BUFFERABLE; // 버퍼링 배제

    HAL_MPU_ConfigRegion(&MPU_InitStruct);
    HAL_MPU_Enable(MPU_PRIVILEGED_DEFAULT);
}
```

### 4.5 재진입성(Reentrancy) 및 ISR 안전성
- SEGGER RTT 기본 구현은 버퍼 포인터 연산 시 임계 영역(Critical Section, 인터럽트 비활성화/복원)을 제공합니다 (`SEGGER_RTT_LOCK()` / `SEGGER_RTT_UNLOCK()`).
- 채널 1의 모드는 `SEGGER_RTT_MODE_NO_BLOCK_SKIP`으로 설정하여, 버퍼가 포화 상태일 때 MCU가 멈추지 않고 실시간성을 최우선으로 보장하도록 합니다.

---

## 5. 프리 컴파일(Pre-build) 자동화 파이프라인

컴파일러 실행 전 소스 트리를 스캔하여 `generated_rtt_keys.h`와 호스트용 `mapping.json`을 단일 실행으로 자동 생성합니다.

### 5.1 소스 스캐너 (`gen_rtt_framework.py`) 구조
스캐너는 프로젝트 내 모든 C/C++ 소스(`*.c`, `*.h`, `*.cpp`)를 파싱하여:
1. 주석(`/* ... */`, `// ...`)을 안전하게 제거
2. `EVENT_LOG(EVT_..., ...)` 호출부에서 이벤트 토큰 추출
3. `KV(key, ...)` 및 `KV_*(key, ...)` 호출부에서 키 토큰 추출
4. 기존에 할당된 ID의 안정성을 보존하면서 결정론적(Deterministic) 정렬 기반 신규 ID를 증분 할당

### 5.2 키 식별자 헤더 (`generated_rtt_keys.h`) 생성 규칙
Key ID는 12비트 범위(`0x001` ~ `0xFFF`) 내에서 할당되며, C 매크로 정의 형식으로 출력됩니다.

```c
/* Auto-generated by gen_rtt_framework.py. DO NOT EDIT! */
#ifndef GENERATED_RTT_KEYS_H_
#define GENERATED_RTT_KEYS_H_

#define KEY_ID_channel                  0x001
#define KEY_ID_std_id                   0x002
#define KEY_ID_data                     0x003
#define KEY_ID_exec_cyc                 0x004
#define KEY_ID_temp                     0x005
#define KEY_ID_limit                    0x006
#define KEY_ID_msg                      0x007

#endif /* GENERATED_RTT_KEYS_H_ */
```

### 5.3 디코딩 메타데이터 (`mapping.json`) 스키마
호스트 어댑터가 참조하는 JSON 스키마는 이벤트 및 키의 매핑 사전을 담고 있습니다.

```json
{
  "events": {
    "0x0001": {
      "token": "EVT_CAN_RX",
      "module": "CAN",
      "event": "RX"
    },
    "0x0002": {
      "token": "EVT_TEMP_CTRL",
      "module": "TEMP",
      "event": "CTRL"
    }
  },
  "keys": {
    "0x001": { "name": "channel" },
    "0x002": { "name": "std_id" },
    "0x003": { "name": "data" },
    "0x004": { "name": "exec_cyc" },
    "0x005": { "name": "temp" },
    "0x006": { "name": "limit" },
    "0x007": { "name": "msg" }
  }
}
```

### 5.4 CMake 및 Makefile 빌드 시스템 통합
빌드 시스템에서 컴파일 타깃 이전에 실행되도록 종속성을 구성합니다.

```cmake
# CMakeLists.txt 구성 예시
find_package(Python3 REQUIRED)

add_custom_target(GenerateRttArtifacts ALL
    COMMAND Python3::Interpreter ${CMAKE_SOURCE_DIR}/tools/gen_rtt_framework.py
                                 ${CMAKE_SOURCE_DIR}/src
                                 ${CMAKE_SOURCE_DIR}/include/generated_rtt_keys.h
                                 ${CMAKE_BINARY_DIR}/mapping.json
    COMMENT "Scanning firmware sources for RTT logging keys and mapping JSON..."
)

add_executable(${PROJECT_NAME}.elf ${SOURCES})
add_dependencies(${PROJECT_NAME}.elf GenerateRttArtifacts)
target_include_directories(${PROJECT_NAME}.elf PRIVATE ${CMAKE_SOURCE_DIR}/include)
target_compile_options(${PROJECT_NAME}.elf PRIVATE -std=c11)
```

---

## 6. 호스트 UI 프레임워크 연동 및 디코딩 명세

호스트 수신 레이어는 J-Link RTT 스트림에서 동기화 바이트(`0xA5`)를 추적하고, 바이너리를 역직렬화하여 기존 테스트 엔진이 사용하는 텍스트 포맷으로 변환합니다.

### 6.1 프레임 동기화 및 패킷 파싱 파이프라인
1. **Sync Byte 정렬**: 수신 버퍼에서 `0xA5` 매직 바이트를 선형 탐색합니다. 앞선 오염 바이트는 즉시 폐기(Drop)합니다.
2. **헤더 검증**: 최소 8바이트 확보 후 `Sync(1B)`, `Event ID(2B)`, `HW Timestamp(4B)`, `Item Count(1B)`를 리틀 엔디언으로 언패킹합니다.
3. **슬롯 스캔 및 가변 길이 합산**: $N$개 슬롯($N \times 6\text{B}$)을 읽으며 `TYPE_HEX_ARR` 및 `TYPE_DYN_STR`에 명시된 가변 바이트 길이($L_i$)의 총합($M$)을 계산합니다.
4. **전체 패킷 도달 검사**: 현재 수신 버퍼 길이가 $8 + 6N + M$ 바이트 이상인지 검사하고, 부족할 경우 추가 스트림 도달 시점까지 대기를 유지합니다.
5. **텍스트 합성**: `mapping.json` 사전을 매핑하여 `[모듈:이벤트] key1=val1 key2=val2 ...` 포맷으로 복원합니다.

### 6.2 호스트 어댑터 (`host_rtt_adapter.py`) 핵심 로직
(자세한 소스 코드는 프로젝트의 `tools/host_rtt_adapter.py` 파일 참조)

```python
class RttFrameDecoder:
    def decode_packet(self, buffer: bytes):
        # 1. Sync 바이트 동기화
        sync_idx = buffer.find(b'\xA5')
        if sync_idx == -1:
            return None, buffer[-0:] # Sync가 없으면 모두 드롭

        buffer = buffer[sync_idx:]
        if len(buffer) < 8:
            return None, buffer

        # 2. 헤더 파싱
        sync, event_id, timestamp, item_cnt = struct.unpack_from('<BHIB', buffer, 0)
        expected_slots_len = 8 + (item_cnt * 6)
        if len(buffer) < expected_slots_len:
            return None, buffer

        # 3. 슬롯 순회 및 가변 바이트 길이 누적
        # 4. Trailing 바이트 슬라이싱 및 필드 역직렬화
        # 5. [MODULE:EVENT] key=value 문자열 합성
```

---

## 7. 실무 코드 작성 및 검증 예시

### 7.1 기본 변수 및 단일 이벤트 로깅
```c
#include "rtt_logger.h"

#define EVT_CAN_RX    0x0001
#define EVT_TEMP_CTRL 0x0002

void Process_CAN_Message(void) {
    uint8_t payload[8] = { 0x11, 0x22, 0x33, 0x44, 0xAA, 0xBB, 0xCC, 0xDD };
    uint32_t start_cyc = GET_DWT_CYCCNT();

    // 사용자 제어 로직 수행...

    uint32_t elapsed_cyc = GET_DWT_CYCCNT() - start_cyc;

    // 다중 배열과 변수를 결합한 초고속 로깅 (타깃 소요시간 ~1.0us)
    EVENT_LOG_BUFS(EVT_CAN_RX,
        { BUF_REF(payload, sizeof(payload)) },
        KV(channel, 1),
        KV_HEX16(std_id, 0x07E8),
        KV_HEX_ARR(data, sizeof(payload)),
        KV_CYC(exec_cyc, elapsed_cyc)
    );
}
```

### 7.2 가변 헥사 버퍼 및 동적 문자열 로깅
```c
void Process_Temperature_Loop(float current_temp) {
    char alert_msg[16] = "OVERHEAT";

    // C11 _Generic float 자동 추론 및 동적 문자열 꼬리 페이로드 전송
    EVENT_LOG_BUFS(EVT_TEMP_CTRL,
        { BUF_REF(alert_msg, strlen(alert_msg)) },
        KV(temp, current_temp),       // float 자동 식별 (TYPE_FLOAT)
        KV(limit, 85),                // int 자동 식별 (TYPE_I32)
        KV_DYN_STR(msg, strlen(alert_msg))
    );
}
```

### 7.3 호스트 UI 출력 복원 결과 비교
호스트 파서가 바이너리 패킷을 디코딩하여 복원하는 최종 텍스트:

```text
[CAN:RX] channel=1 std_id=0x07E8 data="11223344AABBCCDD" exec_cyc=184
[TEMP:CTRL] temp=87.420 limit=85 msg="OVERHEAT"
```

기존 호스트 UI 테스트 엔진은 수신된 텍스트를 파싱하여:
- `[CAN:RX]`와 다음 이벤트 간 타임스탬프 시간차 검증
- `exec_cyc` 값이 250 사이클 이하인지 임계값 판정
- `temp` 값이 상한 `limit`을 초과했는지 범위 검증
등을 기존 정규식 스크립트 수정 없이 100% 동일하게 수행할 수 있습니다.

---

## 8. 기대 효과 및 결론

1. **실행 지연 시간 약 98% 단축**:
   - 기존 `printf` 방식의 $50 \sim 150\,\mu\text{s}$ 실행 지연을 **$0.2 \sim 1.5\,\mu\text{s}$** (600MHz STM32H7RS 기준 약 $120 \sim 900$ 사이클)로 단축합니다.
   - 제어 루프 교란(Heisenbug)을 원천 차단하고 DWT 기반 초정밀 실행 사이클 측정이 가능합니다.
2. **RTT 대역폭 절감 및 오버플로우 방지**:
   - 평균 $60 \sim 100$ 바이트의 ASCII 텍스트가 **$14 \sim 26$ 바이트**의 고밀도 바이너리로 압축 전송됩니다.
   - 고주파 이벤트 로깅 환경에서도 RTT 링 버퍼 포화 및 패킷 드롭 확률을 75% 이상 낮춥니다.
3. **완전 자동화된 무관리 유지보수**:
   - C11 `_Generic`을 통해 타입 선언을 자동화하고, 빌드 파이프라인 연동 Python 스크립트가 Key ID 및 딕셔너리(`mapping.json`)를 동기화하므로 엔지니어가 수동으로 식별자 번호표를 관리할 필요가 없습니다.

---

## 9. 부록: 확장 및 신뢰성 고려사항

1. **체크섬 (Checksum/CRC) 옵션**:
   - 고주파 노이즈가 심한 SWD 환경을 위해 필요 시 패킷 말미에 1바이트 XOR 체크섬 또는 CRC-16 필드를 추가할 수 있도록 프레임 규격의 버전 플래그를 확장할 수 있습니다.
2. **Flash 상주 문자열 (`TYPE_FLASH_STR`) 심볼 역참조**:
   - 타깃은 `const char*`의 32비트 절대 메모리 주소만 전송하고, 호스트 디코더가 ELF 파일(`.rodata` 섹션)을 로드하여 해당 주소의 문자열을 복원하도록 파이프라인을 확장하면 버퍼 전송 대역폭을 0바이트로 극대화할 수 있습니다.
3. **버퍼 오버플로우 검출**:
   - 패킷 헤더의 `sync` 필드 바이트를 확장하거나 시퀀스 번호(1바이트 Sequence Counter)를 헤더에 부여하여 호스트 레이어에서 패킷 드롭 여부를 실시간 카운팅할 수 있습니다.

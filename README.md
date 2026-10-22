# RTT-Engine: RTT 기반 고속 바이너리 로깅 및 테스트 프레임워크

[![Standard: C11](https://img.shields.io/badge/C_Standard-C11-blue.svg)](https://en.cppreference.com/w/c/11)
[![Target: Cortex-M7](https://img.shields.io/badge/Target-ARM_Cortex--M7_(STM32H7RS)-orange.svg)](https://www.st.com)
[![Protocol: SEGGER RTT](https://img.shields.io/badge/Protocol-SEGGER_RTT-green.svg)](https://www.segger.com/products/debug-probes/j-link/technology/about-real-time-transfer/)

> **초경량 타깃 연산(Zero-Formatting)과 C11 `_Generic` 자동 타입 디스패치 기반의 초고속 임베디드 바이너리 로깅 시스템**

---

## 1. 개요 (Overview)

기존 `vsnprintf` 기반의 텍스트 로깅(`[모듈:이벤트] key=value ...`)은 개발자에게 직관적이지만 호출당 **$50 \sim 150\,\mu\text{s}$**의 지연을 발생시켜 고속 제어 루프나 DWT 사이클 측정을 왜곡하고 하이젠버그(Heisenbug)를 유발합니다.

**RTT-Engine**은 컴파일 타임 정적 분석, C11 `_Generic` 타입 디스패치, 그리고 SEGGER RTT 바이너리 스트리밍을 결합하여:
- **실행 시간 단축**: 호출당 **$0.2 \sim 1.5\,\mu\text{s}$** (600MHz STM32H7RS 기준 약 $120 \sim 900$ 사이클, 약 98% 단축)
- **대역폭 절감**: 이벤트당 $60 \sim 100$ 바이트 $\rightarrow$ **$14 \sim 26$ 바이트** (약 75% 절감)
- **100% 하위 호환성**: 호스트 파서가 바이너리를 기존 텍스트 규격으로 즉각 역직렬화하여 기존 UI 테스트 엔진을 무수정 재사용

자세한 설계 사양은 [상세 설계서 (docs/RTT_BINARY_LOGGING_DESIGN_SPEC.md)](docs/RTT_BINARY_LOGGING_DESIGN_SPEC.md)를 참조하십시오.

---

## 2. 시스템 아키텍처 (Architecture)

```
[1. Pre-build 단계]
  C 소스 코드 (*.c, *.h)
         │
         ▼ tools/gen_rtt_framework.py
         ├──► include/generated_rtt_keys.h (컴파일 타임 Key ID 매크로)
         └──► build/mapping.json           (초기 호스트 UI 디코딩용 사전)

[2. 컴파일 및 Post-compile 단계]
  컴파일러 (GCC / Clang)
         │
         ▼ firmware.elf (타깃 바이너리)
         │
         ▼ tools/post_compile_strings.py (.rodata / 심볼 주소 분석)
         └──► build/mapping.json 업데이트 완료
              (Flash 상주 상수 문자열 주소-문자열 맵이 mapping.json에 영구 기록됨)

[3. 타깃 런타임 (MCU)]
  EVENT_LOG / EVENT_LOG_BUFS 호출
         │ (C11 _Generic 타입 식별 + DWT 타임스탬프 + 직렬화)
         │ * 상수 문자열은 4바이트 Flash 주소만 초고속(Zero Copy) 전송
         ▼
  SEGGER RTT 버퍼 (Channel 1, Non-Cacheable MPU 영역)
         │
         ▼ SWD Background Direct Memory Access (J-Link)

[4. 호스트 수신 레이어]
  tools/host_rtt_adapter.py (0xA5 Sync + mapping.json 역직렬화)
         │ * 호스트는 바이너리(.elf) 없이 mapping.json 하나만으로 상수 문자열 복원!
         ▼ Text Synthesizer
  "[CAN:RX] channel=1 std_id=0x07E8 data=\"11223344\" exec_cyc=184"
  "[SYS:STATE] state=\"STANDBY\" desc=\"SYSTEM_READY\""
         │
         ▼ 기존 UI 자동화 테스트 엔진 (DWT 판정, 범위 검증 등)
```

---

## 3. 디렉터리 구조 (Directory Structure)

```
.
├── docs/
│   └── RTT_BINARY_LOGGING_DESIGN_SPEC.md  # 상세 기술 설계서 (TDD)
├── include/
│   ├── rtt_logger.h                      # 타깃 로깅 코어 헤더 (C11 _Generic)
│   ├── SEGGER_RTT.h                      # SEGGER RTT 인터페이스
│   └── generated_rtt_keys.h              # [자동생성] Key ID 매크로
├── src/
│   └── SEGGER_RTT.c                      # SEGGER RTT 참조 구현 / 모의 구현
├── tools/
│   ├── gen_rtt_framework.py              # Pre-build C 소스 스캐너
│   ├── post_compile_strings.py           # Post-compile 바이너리 상수 문자열 추출기
│   └── host_rtt_adapter.py               # 호스트 바이너리 패킷 파서 및 어댑터
├── examples/
│   └── main_example.c                    # 타깃 사용 예시 코드
├── tests/
│   └── test_rtt_framework.py             # 파이프라인 검증 및 단위 테스트
├── CMakeLists.txt                        # CMake 빌드 구성 (Pre/Post 파이프라인 통합)
└── README.md
```

---

## 4. 통신 패킷 프로토콜 명세 (Packet Protocol)

```
┌───────────┬──────────────┬──────────────────┬────────────┬─────────────────────────────┬───────────────────────────┐
│ Sync Byte │ Event ID     │ HW Timestamp     │ Item Count │ Key-Value Slots (N x 6B)    │ Trailing Payload (가변B)  │
│ 0xA5 (1B) │ uint16_t(2B) │ DWT->CYCCNT (4B) │ uint8_t(1B)│ [Tag 2B][Raw Value 4B] x N  │ Raw Hex Buffers / Strings │
└───────────┴──────────────┴──────────────────┴────────────┴─────────────────────────────┴───────────────────────────┘
```

- **Tag (2 Bytes)**: 상위 4비트(Type Code) + 하위 12비트(Key ID)
- **Value (4 Bytes)**: 32비트 기본형 값 또는 가변 데이터 길이 (`len`)

---

## 5. 빠른 시작 (Quick Start)

### 5.1 Pre-build 및 Post-compile 파이프라인 수동 실행
```bash
# 1. Pre-build: 소스 스캔 및 헤더/기본 매핑 생성
python3 tools/gen_rtt_framework.py ./examples ./include/generated_rtt_keys.h ./mapping.json

# 2. 컴파일 (예: CMake 또는 GCC)
gcc -std=c11 -O2 -no-pie -Iinclude src/SEGGER_RTT.c examples/main_example.c -o rtt_example

# 3. Post-compile: 최종 ELF 바이너리에서 상수 문자열 주소를 추출하여 mapping.json 업데이트
python3 tools/post_compile_strings.py rtt_example ./mapping.json

# 4. 호스트 디코더 실행: mapping.json 단독 파일만으로 디코딩 운용
./rtt_example
python3 tools/host_rtt_adapter.py -m mapping.json -i rtt_output.bin
```

### 5.2 타깃 펌웨어 코드 작성 예시
```c
#include "rtt_logger.h"

#define EVT_CAN_RX    0x0001
#define EVT_SYS_STATE 0x0002

void OnCanReceived(uint8_t *payload, uint16_t len) {
    uint32_t start_cyc = GET_DWT_CYCCNT();
    
    // 처리 로직...
    
    uint32_t elapsed_cyc = GET_DWT_CYCCNT() - start_cyc;

    EVENT_LOG_BUFS(EVT_CAN_RX,
        { BUF_REF(payload, len) },
        KV(channel, 1),
        KV_HEX16(std_id, 0x07E8),
        KV_HEX_ARR(data, len),
        KV_CYC(exec_cyc, elapsed_cyc)
    );
}

void OnStateChanged(void) {
    // 상수 문자열은 4바이트 Flash 주소만 초고속(Zero Copy) 전송
    EVENT_LOG(EVT_SYS_STATE,
        KV(state, "STANDBY"),
        KV_FLASH_STR(desc, "SYSTEM_READY")
    );
}
```

### 5.3 테스트 스위트 실행
```bash
python3 -m unittest discover tests
```

---

## 6. 라이선스 (License)
본 프로젝트는 MIT 라이선스를 따릅니다.

cmake_minimum_required(VERSION 3.12)
project(rtt_engine C)

set(CMAKE_C_STANDARD 11)
set(CMAKE_C_STANDARD_REQUIRED ON)

find_package(Python3 COMPONENTS Interpreter REQUIRED)

set(GEN_SCRIPT ${CMAKE_CURRENT_SOURCE_DIR}/tools/gen_rtt_framework.py)
set(GEN_HEADER ${CMAKE_CURRENT_SOURCE_DIR}/include/generated_rtt_keys.h)
set(GEN_JSON   ${CMAKE_CURRENT_BINARY_DIR}/mapping.json)

# Custom target: Pre-build source scan
add_custom_target(GenerateRttArtifacts ALL
    COMMAND ${Python3_EXECUTABLE} ${GEN_SCRIPT}
            ${CMAKE_CURRENT_SOURCE_DIR}/examples
            ${GEN_HEADER}
            ${GEN_JSON}
            --extra-src ${CMAKE_CURRENT_SOURCE_DIR}/src ${CMAKE_CURRENT_SOURCE_DIR}/include
    BYPRODUCTS ${GEN_HEADER} ${GEN_JSON}
    COMMENT "Pre-scanning sources for RTT logging keys and mapping JSON..."
)

include_directories(
    ${CMAKE_CURRENT_SOURCE_DIR}/include
)

set(SOURCES
    src/SEGGER_RTT.c
    examples/main_example.c
)

add_executable(rtt_example ${SOURCES})
add_dependencies(rtt_example GenerateRttArtifacts)

if(CMAKE_C_COMPILER_ID MATCHES "GNU|Clang")
    target_compile_options(rtt_example PRIVATE -Wall -Wextra -O2)
endif()

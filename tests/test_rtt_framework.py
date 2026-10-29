#!/usr/bin/env python3
"""Unit and integration test suite for RTT binary logging framework."""

import os
import sys
import json
import unittest
import struct
import tempfile
import shutil

# Add project root to sys.path
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(PROJECT_ROOT, "tools"))

from gen_rtt_framework import (
    strip_c_comments,
    parse_event_token,
    parse_firmware_sources,
    generate_header,
    generate_mapping_json,
)
from post_compile_strings import (
    parse_elf_sections_and_symbols,
    extract_rodata_strings,
    resolve_symbols_to_strings,
    match_candidate_strings,
    update_mapping_with_strings,
)
from host_rtt_adapter import RttFrameDecoder


class TestScanner(unittest.TestCase):
    """Tests for the Pre-build source code scanner."""

    def test_strip_c_comments(self):
        c_code = """
        // Line comment
        int a = 10; /* Block comment */
        /* Multi-line
           comment
        */
        int b = 20;
        """
        stripped = strip_c_comments(c_code)
        self.assertNotIn("Line comment", stripped)
        self.assertNotIn("Block comment", stripped)
        self.assertNotIn("Multi-line", stripped)
        self.assertIn("int a = 10;", stripped)
        self.assertIn("int b = 20;", stripped)

    def test_parse_event_token(self):
        self.assertEqual(parse_event_token("EVT_CAN_RX"), ("CAN", "RX"))
        self.assertEqual(parse_event_token("EVT_TEMP_CTRL"), ("TEMP", "CTRL"))
        self.assertEqual(parse_event_token("EVT_HEARTBEAT"), ("HEARTBEAT", "LOG"))
        self.assertEqual(parse_event_token("MOTOR_FAULT"), ("MOTOR", "FAULT"))

    def test_scanner_end_to_end(self):
        temp_dir = tempfile.mkdtemp()
        try:
            src_file = os.path.join(temp_dir, "test_app.c")
            with open(src_file, "w", encoding="utf-8") as f:
                f.write("""
                void Test(void) {
                    EVENT_LOG(EVT_SYS_BOOT, KV(boot_count, 1), KV_HEX16(version, 0x0102));
                    EVENT_LOG_BUFS(EVT_SENSOR_DATA, { BUF_REF(buf, 4) }, KV(reading, 12.5), KV_HEX_ARR(raw, 4));
                }
                """)

            events, keys, candidates = parse_firmware_sources([temp_dir])
            self.assertIn("EVT_SYS_BOOT", events)
            self.assertIn("EVT_SENSOR_DATA", events)
            self.assertIn("boot_count", keys)
            self.assertIn("version", keys)
            self.assertIn("reading", keys)
            self.assertIn("raw", keys)

            header_path = os.path.join(temp_dir, "keys.h")
            json_path = os.path.join(temp_dir, "mapping.json")
            generate_header(keys, header_path)
            generate_mapping_json(events, keys, json_path)

            self.assertTrue(os.path.exists(header_path))
            self.assertTrue(os.path.exists(json_path))

            with open(header_path, "r", encoding="utf-8") as f:
                header_content = f.read()
            self.assertIn("#define KEY_ID_boot_count", header_content)

            with open(json_path, "r", encoding="utf-8") as f:
                json_content = f.read()
            self.assertIn("EVT_SYS_BOOT", json_content)
            self.assertIn("SYS", json_content)
        finally:
            shutil.rmtree(temp_dir)


class TestHostDecoder(unittest.TestCase):
    """Tests for binary packet decoding and text synthesis."""

    def setUp(self):
        self.mapping_file = os.path.join(PROJECT_ROOT, "mapping.json")
        self.assertTrue(os.path.exists(self.mapping_file), "mapping.json must exist")
        self.decoder = RttFrameDecoder(self.mapping_file)

    def test_decode_single_scalar_packet(self):
        # Packet: EVT_CAN_RX (id=1), timestamp=12345, item_cnt=2
        # item 0: channel (key_id=1, TYPE_U32=0) -> val=2
        # item 1: exec_cyc (key_id=3, TYPE_CYC=9) -> val=150
        header = struct.pack('<BHIB', 0xA5, 0x0001, 12345, 2)
        slot0 = struct.pack('<HI', (0x0 << 12) | 0x001, 2)
        slot1 = struct.pack('<HI', (0x9 << 12) | 0x003, 150)
        packet = header + slot0 + slot1

        text, ts, consumed = self.decoder.decode_packet(packet)
        self.assertEqual(consumed, len(packet))
        self.assertEqual(ts, 12345)
        self.assertIn("[CAN:RX]", text)
        self.assertIn("channel=2", text)
        self.assertIn("exec_cyc=150", text)

    def test_resync_on_garbage_bytes(self):
        # Garbage prefix preceding valid packet
        garbage = b"\x00\xFF\x12\x34\x56"
        header = struct.pack('<BHIB', 0xA5, 0x0001, 9999, 1)
        slot = struct.pack('<HI', (0x0 << 12) | 0x001, 10)
        stream = garbage + header + slot

        results = self.decoder.feed(stream)
        self.assertEqual(len(results), 1)
        text, ts = results[0]
        self.assertEqual(ts, 9999)
        self.assertIn("[CAN:RX] channel=10", text)

    def test_streaming_chunked_reception(self):
        # Test feeding packet in fragmented 2-byte chunks
        header = struct.pack('<BHIB', 0xA5, 0x0002, 7777, 2)
        slot0 = struct.pack('<HI', (0x2 << 12) | 0x007, struct.unpack('<I', struct.pack('<f', 42.5))[0])
        slot1 = struct.pack('<HI', (0x1 << 12) | 0x004, 100)
        packet = header + slot0 + slot1

        decoder = RttFrameDecoder(self.mapping_file)
        results = []
        chunk_size = 3
        for i in range(0, len(packet), chunk_size):
            chunk = packet[i : i + chunk_size]
            results.extend(decoder.feed(chunk))

        self.assertEqual(len(results), 1)
        text, ts = results[0]
        self.assertEqual(ts, 7777)
        self.assertIn("[TEMP:CTRL]", text)
        self.assertIn("temp=42.500", text)
        self.assertIn("limit=100", text)

    def test_decode_flash_str_with_mapping(self):
        # Flash string address 0x08001000 -> "SYS_OK" in mapping.json
        temp_dir = tempfile.mkdtemp()
        try:
            m_path = os.path.join(temp_dir, "m.json")
            with open(m_path, "w", encoding="utf-8") as f:
                json.dump({
                    "events": { "0x0001": { "token": "EVT_TEST", "module": "TEST", "event": "RUN" } },
                    "keys": { "0x001": { "name": "status" }, "0x002": { "name": "unmapped" } },
                    "strings": { "0x08001000": "SYS_OK" }
                }, f)

            decoder = RttFrameDecoder(m_path)
            # Item 0: key=0x001, TYPE_FLASH_STR=6, val=0x08001000
            # Item 1: key=0x002, TYPE_FLASH_STR=6, val=0x08009999 (not mapped)
            header = struct.pack('<BHIB', 0xA5, 0x0001, 5555, 2)
            slot0 = struct.pack('<HI', (0x6 << 12) | 0x001, 0x08001000)
            slot1 = struct.pack('<HI', (0x6 << 12) | 0x002, 0x08009999)
            packet = header + slot0 + slot1

            text, ts, consumed = decoder.decode_packet(packet)
            self.assertEqual(consumed, len(packet))
            self.assertEqual(ts, 5555)
            self.assertIn('[TEST:RUN]', text)
            self.assertIn('status="SYS_OK"', text)
            self.assertIn('unmapped=0x08009999', text)
        finally:
            shutil.rmtree(temp_dir)

    def test_post_compile_string_extraction(self):
        # Unit test verifying post-compile string extractor logic on a dummy ELF or binary
        temp_dir = tempfile.mkdtemp()
        try:
            c_code = """
            #include <stdio.h>
            const char g_boot_str[] = "SYSTEM_INITIALIZED";
            const char g_ready_str[] = "DEVICE_ONLINE";
            int main(void) {
                printf("%s %s\\n", g_boot_str, g_ready_str);
                return 0;
            }
            """
            src_path = os.path.join(temp_dir, "test_app.c")
            elf_path = os.path.join(temp_dir, "test_app.elf")
            mapping_path = os.path.join(temp_dir, "mapping.json")

            with open(src_path, "w", encoding="utf-8") as f:
                f.write(c_code)

            import subprocess
            subprocess.check_call(["gcc", "-O2", "-no-pie", src_path, "-o", elf_path])

            with open(mapping_path, "w", encoding="utf-8") as f:
                json.dump({
                    "events": {},
                    "keys": {},
                    "candidate_strings": ["SYSTEM_INITIALIZED", "DEVICE_ONLINE"]
                }, f)

            sections, symbols = parse_elf_sections_and_symbols(elf_path)
            rodata_str = extract_rodata_strings(sections)
            sym_str = resolve_symbols_to_strings(sections, symbols)
            cand_str = match_candidate_strings(sections, ["SYSTEM_INITIALIZED", "DEVICE_ONLINE"])
            all_str = {**rodata_str, **sym_str, **cand_str}

            update_mapping_with_strings(mapping_path, all_str)

            with open(mapping_path, "r", encoding="utf-8") as f:
                updated_data = json.load(f)

            self.assertIn("strings", updated_data)
            str_values = list(updated_data["strings"].values())
            self.assertIn("SYSTEM_INITIALIZED", str_values)
            self.assertIn("DEVICE_ONLINE", str_values)
        finally:
            shutil.rmtree(temp_dir)

    def test_c_binary_dump_verification(self):
        # Build and execute C example to verify end-to-end binary stream
        import subprocess
        bin_path = os.path.join(PROJECT_ROOT, "build_test_example")
        test_mapping = os.path.join(PROJECT_ROOT, "test_mapping.json")
        test_header = os.path.join(PROJECT_ROOT, "include", "generated_rtt_keys.h")

        # 1. Run pre-build scanner
        events, keys, candidates = parse_firmware_sources([
            os.path.join(PROJECT_ROOT, "examples")
        ])
        generate_header(keys, test_header, events)
        generate_mapping_json(events, keys, test_mapping, candidates)

        # 2. Compile C binary
        compile_cmd = [
            "gcc", "-std=c11", "-O2", "-no-pie",
            "-I" + os.path.join(PROJECT_ROOT, "include"),
            os.path.join(PROJECT_ROOT, "src", "SEGGER_RTT.c"),
            os.path.join(PROJECT_ROOT, "examples", "main_example.c"),
            "-o", bin_path
        ]
        try:
            subprocess.check_call(compile_cmd)

            # 3. Run post-compile string extractor to populate test_mapping.json
            sections, symbols = parse_elf_sections_and_symbols(bin_path)
            rodata_strings = extract_rodata_strings(sections)
            sym_strings = resolve_symbols_to_strings(sections, symbols)
            cand_strings = match_candidate_strings(sections, list(candidates))
            all_str = {**rodata_strings, **sym_strings, **cand_strings}
            update_mapping_with_strings(test_mapping, all_str)

            # 4. Execute C binary
            subprocess.check_call([bin_path])

            output_file = os.path.join(PROJECT_ROOT, "rtt_output.bin")
            with open(output_file, "rb") as f:
                data = f.read()

            # 5. Host decoder operates SOLELY with test_mapping.json (no binary file passed)
            decoder = RttFrameDecoder(test_mapping)
            events = decoder.feed(data)
            self.assertEqual(len(events), 3)

            evt1_text, evt1_ts = events[0]
            self.assertIn("[CAN:RX]", evt1_text)
            self.assertIn("channel=1", evt1_text)
            self.assertIn("std_id=0x07E8", evt1_text)
            self.assertIn('data="11223344AABBCCDD"', evt1_text)
            self.assertIn("exec_cyc=184", evt1_text)

            evt2_text, evt2_ts = events[1]
            self.assertIn("[TEMP:CTRL]", evt2_text)
            self.assertIn("temp=87.420", evt2_text)
            self.assertIn("limit=85", evt2_text)
            self.assertIn('msg="OVERHEAT"', evt2_text)

            evt3_text, evt3_ts = events[2]
            self.assertIn("[SYS:STATE]", evt3_text)
            self.assertIn('state="STANDBY"', evt3_text)
            self.assertIn('desc="SYSTEM_READY"', evt3_text)
        finally:
            if os.path.exists(bin_path):
                os.remove(bin_path)
            if os.path.exists(os.path.join(PROJECT_ROOT, "rtt_output.bin")):
                os.remove(os.path.join(PROJECT_ROOT, "rtt_output.bin"))
            if os.path.exists(test_mapping):
                os.remove(test_mapping)


if __name__ == "__main__":
    unittest.main()

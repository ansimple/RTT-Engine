#!/usr/bin/env python3
"""Unit and integration test suite for RTT binary logging framework."""

import os
import sys
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

            events, keys = parse_firmware_sources([temp_dir])
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

    def test_c_binary_dump_verification(self):
        # Build and execute C example to verify end-to-end binary stream
        import subprocess
        bin_path = os.path.join(PROJECT_ROOT, "build_test_example")
        dump_path = os.path.join(PROJECT_ROOT, "test_output.bin")

        compile_cmd = [
            "gcc", "-std=c11", "-O2",
            "-I" + os.path.join(PROJECT_ROOT, "include"),
            os.path.join(PROJECT_ROOT, "src", "SEGGER_RTT.c"),
            os.path.join(PROJECT_ROOT, "examples", "main_example.c"),
            "-o", bin_path
        ]
        try:
            subprocess.check_call(compile_cmd)
            subprocess.check_call([bin_path])

            output_file = os.path.join(PROJECT_ROOT, "rtt_output.bin")
            with open(output_file, "rb") as f:
                data = f.read()

            decoder = RttFrameDecoder(self.mapping_file)
            events = decoder.feed(data)
            self.assertEqual(len(events), 2)

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
        finally:
            if os.path.exists(bin_path):
                os.remove(bin_path)
            if os.path.exists(os.path.join(PROJECT_ROOT, "rtt_output.bin")):
                os.remove(os.path.join(PROJECT_ROOT, "rtt_output.bin"))


if __name__ == "__main__":
    unittest.main()

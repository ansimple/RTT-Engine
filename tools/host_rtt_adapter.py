#!/usr/bin/env python3
"""Host-side RTT Binary Stream Decoder and Adapter.

Parses binary packets received via SEGGER RTT (Channel 1) and synthesizes
them into standardized text format:
  [MODULE:EVENT] key1=val1 key2=val2 ...
ensuring 100% backward compatibility with host UI automation test engines.
"""

import sys
import struct
import json
import argparse
from typing import Optional, Tuple, List, Dict, Any


class RttFrameDecoder:
    """Decoder for RTT binary logging frames."""

    SYNC_BYTE = 0xA5
    HEADER_SIZE = 8
    SLOT_SIZE = 6

    def __init__(self, mapping_json_path: str, elf_path: Optional[str] = None):
        with open(mapping_json_path, 'r', encoding='utf-8') as f:
            self.mapping = json.load(f)
        self.events_map: Dict[str, Dict[str, Any]] = self.mapping.get("events", {})
        self.keys_map: Dict[str, Dict[str, Any]] = self.mapping.get("keys", {})
        self.strings_map: Dict[str, str] = self.mapping.get("strings", {})
        self.elf_path = elf_path
        self._stream_buffer = bytearray()

    def decode_packet(self, buffer: bytes) -> Tuple[Optional[str], Optional[int], int]:
        """Decodes one packet from the front of buffer.

        Returns:
            (synthesized_text, hw_timestamp, consumed_bytes)
            If packet is incomplete or sync byte is not yet aligned, returns (None, None, consumed_bytes).
        """
        if len(buffer) < self.HEADER_SIZE:
            return None, None, 0

        # 1. Locate and align to Sync byte (0xA5)
        sync_idx = buffer.find(bytes([self.SYNC_BYTE]))
        if sync_idx == -1:
            # Entire buffer lacks sync byte; drop it
            return None, None, len(buffer)
        if sync_idx > 0:
            # Drop invalid bytes preceding the sync marker
            return None, None, sync_idx

        # 2. Parse fixed 8-byte header
        sync, event_id, timestamp, item_cnt = struct.unpack_from('<BHIB', buffer, 0)
        expected_slots_len = self.HEADER_SIZE + (item_cnt * self.SLOT_SIZE)
        if len(buffer) < expected_slots_len:
            return None, None, 0  # Incomplete slots; wait for more data

        # 3. First pass over slots to determine trailing payload length
        slot_items: List[Tuple[int, str, int, int]] = []
        trailing_data_len = 0
        offset = self.HEADER_SIZE

        for _ in range(item_cnt):
            tag, raw_val = struct.unpack_from('<HI', buffer, offset)
            offset += self.SLOT_SIZE
            type_code = (tag >> 12) & 0x0F
            key_id = f"0x{(tag & 0x0FFF):03X}"

            if type_code in (0x6, 0x7, 0x8):  # TYPE_STR, TYPE_HEX_ARR, or TYPE_DYN_STR
                length = raw_val & 0xFFFF
                trailing_data_len += length
                slot_items.append((type_code, key_id, raw_val, length))
            else:
                slot_items.append((type_code, key_id, raw_val, 0))

        total_packet_len = expected_slots_len + trailing_data_len
        if len(buffer) < total_packet_len:
            return None, None, 0  # Incomplete trailing payload; wait for more data

        # 4. Deserialize slots and slice trailing variable data
        trailing_offset = expected_slots_len
        kv_pairs = []

        for type_code, key_id, raw_val, var_len in slot_items:
            key_meta = self.keys_map.get(key_id, {"name": f"k_{key_id}"})
            key_name = key_meta["name"]

            if type_code == 0x0:  # TYPE_U32
                val_str = str(raw_val)
            elif type_code == 0x1:  # TYPE_I32
                val_i32 = struct.unpack('<i', struct.pack('<I', raw_val))[0]
                val_str = str(val_i32)
            elif type_code == 0x2:  # TYPE_FLOAT
                val_flt = struct.unpack('<f', struct.pack('<I', raw_val))[0]
                val_str = f"{val_flt:.3f}"
            elif type_code == 0x3:  # TYPE_HEX8
                val_str = f"0x{(raw_val & 0xFF):02X}"
            elif type_code == 0x4:  # TYPE_HEX16
                val_str = f"0x{(raw_val & 0xFFFF):04X}"
            elif type_code == 0x5:  # TYPE_HEX32
                val_str = f"0x{raw_val:08X}"
            elif type_code in (0x6, 0x8):  # TYPE_STR or TYPE_DYN_STR (Trailing ASCII/UTF-8 String)
                str_bytes = buffer[trailing_offset: trailing_offset + var_len]
                trailing_offset += var_len
                val_str = f'"{str_bytes.decode("utf-8", errors="replace")}"'
            elif type_code == 0x7:  # TYPE_HEX_ARR (Trailing Raw Byte Array)
                arr_bytes = buffer[trailing_offset: trailing_offset + var_len]
                trailing_offset += var_len
                val_str = f'"{arr_bytes.hex().upper()}"'
            elif type_code == 0x9:  # TYPE_CYC
                val_str = str(raw_val)
            else:
                val_str = str(raw_val)

            kv_pairs.append(f"{key_name}={val_str}")

        # 5. Synthesize standard text tag: [MODULE:EVENT] key=value ...
        evt_key = f"0x{event_id:04X}"
        evt_meta = self.events_map.get(evt_key, {"module": "SYS", "event": f"EVT_{evt_key}"})
        mod = evt_meta.get("module", "SYS")
        evt = evt_meta.get("event", f"EVT_{evt_key}")

        synthesized_text = f"[{mod}:{evt}] " + " ".join(kv_pairs) if kv_pairs else f"[{mod}:{evt}]"
        return synthesized_text, timestamp, total_packet_len

    def feed(self, chunk: bytes) -> List[Tuple[str, int]]:
        """Appends new bytes to internal stream buffer and returns all decoded events."""
        self._stream_buffer.extend(chunk)
        results = []

        while len(self._stream_buffer) > 0:
            text, ts, consumed = self.decode_packet(bytes(self._stream_buffer))
            if consumed == 0:
                break
            del self._stream_buffer[:consumed]
            if text is not None and ts is not None:
                results.append((text, ts))

        return results


def main():
    parser = argparse.ArgumentParser(description="Host RTT Binary Decoder")
    parser.add_argument("--mapping", "-m", required=True, help="Path to mapping.json")
    parser.add_argument("--input", "-i", default="-", help="Input binary file (or - for stdin)")
    parser.add_argument("--show-timestamp", "-t", action="store_true", help="Prefix output with HW timestamp")

    args = parser.parse_args()

    decoder = RttFrameDecoder(args.mapping)

    if args.input == "-":
        stream = sys.stdin.buffer
    else:
        stream = open(args.input, "rb")

    try:
        while True:
            chunk = stream.read(4096)
            if not chunk:
                break
            events = decoder.feed(chunk)
            for text, ts in events:
                if args.show_timestamp:
                    print(f"[{ts:010d}] {text}")
                else:
                    print(text)
    finally:
        if args.input != "-":
            stream.close()


if __name__ == '__main__':
    main()

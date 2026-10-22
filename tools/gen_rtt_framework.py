#!/usr/bin/env python3
"""Pre-build scanner for RTT binary logging framework.

Scans C/C++ source trees to automatically assign:
- Event IDs (16-bit)
- Key IDs (12-bit)
And generates:
- generated_rtt_keys.h for firmware compilation
- mapping.json for host UI decoding
"""

import os
import re
import json
import sys
import argparse
from typing import Dict, Tuple, Any, Optional


def strip_c_comments(content: str) -> str:
    """Strips block (/* ... */) and line (// ...) comments from C source code."""
    pattern = r'/\*[\s\S]*?\*/|//.*'
    return re.sub(pattern, '', content)


def parse_event_token(token: str) -> Tuple[str, str]:
    """Extracts module and event name from an event token (e.g. EVT_CAN_RX -> CAN, RX)."""
    name_body = token[4:] if token.startswith("EVT_") else token
    parts = name_body.split('_', 1)
    module = parts[0] if parts[0] else "SYS"
    event = parts[1] if len(parts) > 1 and parts[1] else "LOG"
    return module, event


def parse_firmware_sources(src_dirs: list, existing_mapping_path: Optional[str] = None) -> Tuple[Dict[str, Dict[str, Any]], Dict[str, int], set]:
    """Scans directories for EVENT_LOG and KV macro usages.
    
    If existing_mapping_path is provided and exists, preserves previously assigned IDs.
    """
    evt_pattern = re.compile(r'\bEVENT_LOG(?:_BUFS)?\s*\(\s*([A-Za-z0-9_]+)')
    kv_pattern = re.compile(r'\bKV(?:_[A-Za-z0-9_]+)?\s*\(\s*([A-Za-z0-9_]+)')
    literal_str_pattern = re.compile(r'"([^"\\]*(?:\\.[^"\\]*)*)"')

    events_found = {}
    keys_found = set()
    string_candidates = set()

    for s_dir in src_dirs:
        if not os.path.exists(s_dir):
            continue
        for root, _, files in os.walk(s_dir):
            for f in sorted(files):
                if not f.endswith(('.c', '.h', '.cpp', '.hpp')):
                    continue
                # Skip framework definition headers themselves to avoid matching macro definition placeholders
                if f in ('rtt_logger.h', 'generated_rtt_keys.h'):
                    continue
                path = os.path.join(root, f)
                try:
                    with open(path, 'r', encoding='utf-8', errors='ignore') as fp:
                        content = fp.read()
                except Exception as e:
                    print(f"[Warning] Failed reading {path}: {e}", file=sys.stderr)
                    continue

                clean_content = strip_c_comments(content)

                for match in evt_pattern.finditer(clean_content):
                    token = match.group(1)
                    if token not in events_found:
                        mod, evt = parse_event_token(token)
                        events_found[token] = {"module": mod, "event": evt}

                for match in kv_pattern.finditer(clean_content):
                    k_name = match.group(1)
                    keys_found.add(k_name)

                for match in literal_str_pattern.finditer(clean_content):
                    s_lit = match.group(1)
                    if len(s_lit) > 0 and len(s_lit) < 256:
                        string_candidates.add(s_lit)

    # Load existing IDs if mapping file is provided
    existing_events = {}
    existing_keys = {}
    if existing_mapping_path and os.path.exists(existing_mapping_path):
        try:
            with open(existing_mapping_path, 'r', encoding='utf-8') as fp:
                old_map = json.load(fp)
                for h_id, e_info in old_map.get("events", {}).items():
                    tok = e_info.get("token")
                    if tok:
                        existing_events[tok] = int(h_id, 16)
                for h_id, k_info in old_map.get("keys", {}).items():
                    kn = k_info.get("name")
                    if kn:
                        existing_keys[kn] = int(h_id, 16)
        except Exception:
            pass

    # Assign IDs, preserving existing ones
    events_result = {}
    assigned_evt_ids = set(existing_events.values())
    next_evt_id = 1

    for token in sorted(events_found.keys()):
        if token in existing_events:
            e_id = existing_events[token]
        else:
            while next_evt_id in assigned_evt_ids:
                next_evt_id += 1
            e_id = next_evt_id
            assigned_evt_ids.add(e_id)
        events_result[token] = {
            "id": e_id,
            "module": events_found[token]["module"],
            "event": events_found[token]["event"]
        }

    keys_result = {}
    assigned_key_ids = set(existing_keys.values())
    next_key_id = 1

    for k_name in sorted(keys_found):
        if k_name in existing_keys:
            k_id = existing_keys[k_name]
        else:
            while next_key_id in assigned_key_ids:
                next_key_id += 1
            k_id = next_key_id
            assigned_key_ids.add(k_id)
        keys_result[k_name] = k_id

    return events_result, keys_result, string_candidates


def generate_header(keys: Dict[str, int], out_header_path: str, events: Dict[str, Dict[str, Any]] = None) -> None:
    """Generates the C header file containing KEY_ID_* and optional EVT_* definitions."""
    os.makedirs(os.path.dirname(os.path.abspath(out_header_path)), exist_ok=True)
    with open(out_header_path, 'w', encoding='utf-8') as f:
        f.write("/* Auto-generated by gen_rtt_framework.py. DO NOT EDIT! */\n")
        f.write("#ifndef GENERATED_RTT_KEYS_H_\n")
        f.write("#define GENERATED_RTT_KEYS_H_\n\n")

        if events:
            f.write("/* Auto-assigned Event IDs */\n")
            for e_token in sorted(events.keys()):
                e_id = events[e_token]["id"]
                f.write(f"#ifndef {e_token}\n")
                f.write(f"#define {e_token:<32} 0x{e_id:04X}\n")
                f.write(f"#endif\n")
            f.write("\n")

        f.write("/* Auto-assigned Key IDs */\n")
        for k_name in sorted(keys.keys()):
            k_id = keys[k_name]
            f.write(f"#define KEY_ID_{k_name:<28} 0x{k_id:03X}\n")
        f.write("\n#endif /* GENERATED_RTT_KEYS_H_ */\n")


def generate_mapping_json(events: Dict[str, Dict[str, Any]], keys: Dict[str, int], out_json_path: str, candidate_strings: set = None) -> None:
    """Generates the mapping.json database used by host UI decoding.
    
    If mapping.json already exists and contains a 'strings' dictionary
    (e.g. from previous post-compile runs), it preserves existing strings.
    Candidate strings discovered from source scan are also recorded under
    'candidate_strings' to assist post-compile exact address matching.
    """
    existing_strings = {}
    if os.path.exists(out_json_path):
        try:
            with open(out_json_path, 'r', encoding='utf-8') as f:
                old_data = json.load(f)
                if isinstance(old_data, dict) and "strings" in old_data:
                    existing_strings = old_data["strings"]
        except Exception:
            pass

    mapping = {
        "events": {},
        "keys": {},
        "strings": existing_strings
    }

    if candidate_strings:
        mapping["candidate_strings"] = sorted(list(candidate_strings))

    for e_token, e_info in events.items():
        hex_id = f"0x{e_info['id']:04X}"
        mapping["events"][hex_id] = {
            "token": e_token,
            "module": e_info["module"],
            "event": e_info["event"]
        }

    for k_name, k_id in keys.items():
        hex_id = f"0x{k_id:03X}"
        mapping["keys"][hex_id] = {
            "name": k_name,
            "display_override": ""
        }

    os.makedirs(os.path.dirname(os.path.abspath(out_json_path)), exist_ok=True)
    with open(out_json_path, 'w', encoding='utf-8') as f:
        json.dump(mapping, f, indent=2)


def main():
    parser = argparse.ArgumentParser(description="RTT Binary Logging Pre-build Code Generator")
    parser.add_argument("src", nargs="?", default="./src", help="Source directory or file")
    parser.add_argument("header_out", nargs="?", default="./include/generated_rtt_keys.h", help="Output C header file")
    parser.add_argument("json_out", nargs="?", default="./mapping.json", help="Output JSON mapping file")
    parser.add_argument("--extra-src", nargs="*", default=[], help="Extra source directories to scan")

    args = parser.parse_args()

    src_dirs = [args.src] + args.extra_src
    events, keys, candidates = parse_firmware_sources(src_dirs, args.json_out)

    generate_header(keys, args.header_out, events)
    generate_mapping_json(events, keys, args.json_out, candidates)

    print(f"[Pre-build] Success: {len(events)} Events, {len(keys)} Keys indexed.")
    print(f"            Header: {args.header_out}")
    print(f"            JSON:   {args.json_out}")


if __name__ == '__main__':
    main()

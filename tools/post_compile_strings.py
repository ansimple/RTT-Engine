#!/usr/bin/env python3
"""Post-compile binary string extractor for RTT binary logging framework.

Reads the compiled target binary (ELF file) to extract constant string literals
and symbols from read-only data sections (.rodata, .text, .data), then maps their
absolute virtual memory addresses (VMA) into the mapping.json database.

This enables the host decoder to operate SOLELY with mapping.json, resolving
Flash/ROM string addresses to actual strings without needing access to the
firmware binary file during operation.
"""

import os
import sys
import json
import struct
import argparse
from typing import Dict, List, Tuple, Optional, Any


def parse_elf_sections_and_symbols(elf_path: str) -> Tuple[List[Dict[str, Any]], Dict[str, int]]:
    """Parses ELF file to extract section information and symbols.
    
    Returns:
        (sections_list, symbols_dict: {symbol_name: vma_address})
    """
    with open(elf_path, 'rb') as f:
        elf_bytes = f.read()

    if len(elf_bytes) < 52 or elf_bytes[:4] != b'\x7fELF':
        raise ValueError(f"Not a valid ELF file: {elf_path}")

    ei_class = elf_bytes[4]      # 1: 32-bit, 2: 64-bit
    ei_data = elf_bytes[5]       # 1: Little-endian, 2: Big-endian
    endian = '<' if ei_data == 1 else '>'
    is_64 = (ei_class == 2)

    if is_64:
        shoff = struct.unpack_from(endian + 'Q', elf_bytes, 40)[0]
        shentsize = struct.unpack_from(endian + 'H', elf_bytes, 58)[0]
        shnum = struct.unpack_from(endian + 'H', elf_bytes, 60)[0]
        shstrndx = struct.unpack_from(endian + 'H', elf_bytes, 62)[0]
    else:
        shoff = struct.unpack_from(endian + 'I', elf_bytes, 32)[0]
        shentsize = struct.unpack_from(endian + 'H', elf_bytes, 46)[0]
        shnum = struct.unpack_from(endian + 'H', elf_bytes, 48)[0]
        shstrndx = struct.unpack_from(endian + 'H', elf_bytes, 50)[0]

    # Read section name string table (.shstrtab)
    if is_64:
        strtab_off = struct.unpack_from(endian + 'Q', elf_bytes, shoff + shstrndx * shentsize + 24)[0]
        strtab_size = struct.unpack_from(endian + 'Q', elf_bytes, shoff + shstrndx * shentsize + 32)[0]
    else:
        strtab_off = struct.unpack_from(endian + 'I', elf_bytes, shoff + shstrndx * shentsize + 16)[0]
        strtab_size = struct.unpack_from(endian + 'I', elf_bytes, shoff + shstrndx * shentsize + 20)[0]

    shstrtab = elf_bytes[strtab_off:strtab_off + strtab_size]

    sections = []
    symtab_sections = []

    for i in range(shnum):
        s_hdr = shoff + i * shentsize
        name_idx = struct.unpack_from(endian + 'I', elf_bytes, s_hdr)[0]
        sh_type = struct.unpack_from(endian + 'I', elf_bytes, s_hdr + 4)[0]
        sec_name = shstrtab[name_idx:].split(b'\x00')[0].decode('latin1', errors='replace')

        if is_64:
            s_addr = struct.unpack_from(endian + 'Q', elf_bytes, s_hdr + 16)[0]
            s_offset = struct.unpack_from(endian + 'Q', elf_bytes, s_hdr + 24)[0]
            s_size = struct.unpack_from(endian + 'Q', elf_bytes, s_hdr + 32)[0]
            s_link = struct.unpack_from(endian + 'I', elf_bytes, s_hdr + 40)[0]
            s_entsize = struct.unpack_from(endian + 'Q', elf_bytes, s_hdr + 56)[0]
        else:
            s_addr = struct.unpack_from(endian + 'I', elf_bytes, s_hdr + 12)[0]
            s_offset = struct.unpack_from(endian + 'I', elf_bytes, s_hdr + 16)[0]
            s_size = struct.unpack_from(endian + 'I', elf_bytes, s_hdr + 20)[0]
            s_link = struct.unpack_from(endian + 'I', elf_bytes, s_hdr + 24)[0]
            s_entsize = struct.unpack_from(endian + 'I', elf_bytes, s_hdr + 36)[0]

        sec_data = elf_bytes[s_offset:s_offset + s_size]
        sec_info = {
            "index": i,
            "name": sec_name,
            "type": sh_type,
            "addr": s_addr,
            "offset": s_offset,
            "size": s_size,
            "link": s_link,
            "entsize": s_entsize,
            "data": sec_data
        }
        sections.append(sec_info)
        if sh_type in (2, 11):  # SHT_SYMTAB=2, SHT_DYNSYM=11
            symtab_sections.append(sec_info)

    symbols = {}
    for sym_sec in symtab_sections:
        link_idx = sym_sec["link"]
        if link_idx < len(sections):
            str_sec = sections[link_idx]
            symstr = str_sec["data"]
            s_entsize = sym_sec["entsize"] if sym_sec["entsize"] > 0 else (24 if is_64 else 16)
            symcount = sym_sec["size"] // s_entsize
            sec_offset = sym_sec["offset"]

            for s_idx in range(symcount):
                sym_hdr = sec_offset + s_idx * s_entsize
                st_name = struct.unpack_from(endian + 'I', elf_bytes, sym_hdr)[0]
                sym_name = symstr[st_name:].split(b'\x00')[0].decode('latin1', errors='replace')
                if is_64:
                    st_value = struct.unpack_from(endian + 'Q', elf_bytes, sym_hdr + 8)[0]
                else:
                    st_value = struct.unpack_from(endian + 'I', elf_bytes, sym_hdr + 4)[0]

                if sym_name:
                    symbols[sym_name] = st_value

    return sections, symbols


def extract_rodata_strings(sections: List[Dict[str, Any]]) -> Dict[str, str]:
    """Scans .rodata (and similar read-only) sections for null-terminated strings.
    
    Returns:
        { "0x08001234": "string_content", ... }
    """
    strings_map = {}
    target_sections = ['.rodata']

    for sec in sections:
        # Match only read-only data sections (.rodata and sub-sections)
        # Avoid .text or .comment sections which contain opcode or compiler banner false positives
        matched = False
        for ts in target_sections:
            if sec["name"] == ts or sec["name"].startswith(ts + "."):
                matched = True
                break
        if not matched:
            continue

        data = sec["data"]
        base_addr = sec["addr"]
        if not data or base_addr == 0:
            continue

        # Extract null-terminated strings
        # A valid string candidate has length >= 1, ASCII/UTF-8 printable characters
        start = 0
        n = len(data)
        while start < n:
            end = data.find(b'\x00', start)
            if end == -1:
                break
            raw_chunk = data[start:end]

            # Look for sub-slice that is ASCII printable
            # Because non-string binary literals (e.g. floats, ints) can precede strings without a null byte
            p_start = 0
            while p_start < len(raw_chunk) and not (0x20 <= raw_chunk[p_start] <= 0x7E):
                p_start += 1
            
            valid_chunk = raw_chunk[p_start:]
            if len(valid_chunk) >= 1:
                try:
                    s_text = valid_chunk.decode('utf-8')
                    if s_text.isprintable() and len(s_text.strip()) > 0:
                        addr_str = f"0x{(base_addr + start + p_start):08X}"
                        strings_map[addr_str] = s_text
                except UnicodeDecodeError:
                    pass
            start = end + 1

    return strings_map


def match_candidate_strings(sections: List[Dict[str, Any]], candidates: List[str]) -> Dict[str, str]:
    """Finds exact virtual addresses of candidate strings in read-only sections.
    
    Candidate strings are matched against section bytes with trailing null byte.
    """
    matched = {}
    for cand in candidates:
        if not cand:
            continue
        needle = cand.encode('utf-8') + b'\x00'
        for sec in sections:
            # Search in rodata and data sections
            if not (sec["name"].startswith('.rodata') or sec["name"].startswith('.data')):
                continue
            data = sec["data"]
            base_addr = sec["addr"]
            if not data or base_addr == 0:
                continue
            pos = 0
            while True:
                found = data.find(needle, pos)
                if found == -1:
                    break
                vma = base_addr + found
                matched[f"0x{vma:08X}"] = cand
                pos = found + 1
    return matched


def resolve_symbols_to_strings(sections: List[Dict[str, Any]], symbols: Dict[str, int]) -> Dict[str, str]:
    """Resolves string variable symbols that point to section data."""
    symbol_strings = {}
    for name, vma in symbols.items():
        if vma == 0:
            continue
        for sec in sections:
            sec_start = sec["addr"]
            sec_end = sec_start + sec["size"]
            if sec_start <= vma < sec_end:
                offset_in_sec = vma - sec_start
                data = sec["data"][offset_in_sec:]
                null_pos = data.find(b'\x00')
                if null_pos != -1:
                    raw_str = data[:null_pos]
                    try:
                        s_text = raw_str.decode('utf-8')
                        if s_text.isprintable() and len(s_text.strip()) > 0:
                            addr_str = f"0x{vma:08X}"
                            symbol_strings[addr_str] = s_text
                    except UnicodeDecodeError:
                        pass
                break
    return symbol_strings


def update_mapping_with_strings(mapping_path: str, strings_map: Dict[str, str]) -> int:
    """Updates the mapping.json file with extracted constant strings.
    
    Returns:
        Number of strings written to mapping.json.
    """
    mapping = {}
    if os.path.exists(mapping_path):
        with open(mapping_path, 'r', encoding='utf-8') as f:
            mapping = json.load(f)

    # Re-populate strings fresh from ELF
    mapping["strings"] = dict(sorted(strings_map.items()))

    # Remove temporary candidate_strings from final mapping.json if present
    mapping.pop("candidate_strings", None)

    with open(mapping_path, 'w', encoding='utf-8') as f:
        json.dump(mapping, f, indent=2)

    return len(mapping["strings"])


def main():
    parser = argparse.ArgumentParser(description="RTT Binary Logging Post-Compile Constant String Extractor")
    parser.add_argument("elf", help="Path to compiled target ELF binary")
    parser.add_argument("mapping", help="Path to mapping.json to update")
    parser.add_argument("--verbose", "-v", action="store_true", help="Print extracted strings")

    args = parser.parse_args()

    if not os.path.exists(args.elf):
        print(f"[Post-compile Error] ELF file not found: {args.elf}", file=sys.stderr)
        sys.exit(1)

    if not os.path.exists(args.mapping):
        print(f"[Post-compile Error] mapping.json not found: {args.mapping}", file=sys.stderr)
        sys.exit(1)

    try:
        sections, symbols = parse_elf_sections_and_symbols(args.elf)
        rodata_strings = extract_rodata_strings(sections)
        sym_strings = resolve_symbols_to_strings(sections, symbols)

        candidate_matched = {}
        with open(args.mapping, 'r', encoding='utf-8') as f:
            mapping_data = json.load(f)
            candidates = mapping_data.get("candidate_strings", [])
            if candidates:
                candidate_matched = match_candidate_strings(sections, candidates)

        all_strings = {**rodata_strings, **sym_strings, **candidate_matched}

        total_in_db = update_mapping_with_strings(args.mapping, all_strings)

        print(f"[Post-compile] Success: Extracted {len(all_strings)} constant strings from {os.path.basename(args.elf)}.")
        print(f"               Updated mapping: {args.mapping} (Total strings in DB: {total_in_db})")

        if args.verbose:
            for addr, s_val in sorted(all_strings.items()):
                print(f"  {addr} -> \"{s_val}\"")
    except Exception as e:
        print(f"[Post-compile Error] Failed extracting strings from ELF: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__':
    main()

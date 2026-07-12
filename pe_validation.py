from __future__ import annotations

import struct
from pathlib import Path

PE_SIGNATURE = b"PE\x00\x00"
VALID_OPTIONAL_MAGIC = {0x10B, 0x20B}
VALID_MACHINE_TYPES = {0x14C, 0x8664, 0xAA64}
MIN_PE_SIZE = 256
MAX_SECTION_COUNT = 96


def validate_pe_file(path: Path) -> str | None:
    target = Path(path)
    if not target.exists():
        return f"Missing executable: {target}"
    if not target.is_file():
        return f"Executable is not a regular file: {target}"
    size = target.stat().st_size
    if size < MIN_PE_SIZE:
        return f"Executable is too small to be a valid PE file: {size} bytes"
    with target.open("rb") as handle:
        data = handle.read()
    if data[:2] != b"MZ":
        return f"Executable does not start with MZ: {target}"
    if len(data) < 0x40:
        return f"Executable is truncated before e_lfanew: {target}"
    e_lfanew = struct.unpack_from("<I", data, 0x3C)[0]
    if e_lfanew < 0x40 or e_lfanew + 24 > len(data):
        return f"Executable has invalid e_lfanew: {e_lfanew}"
    if data[e_lfanew : e_lfanew + 4] != PE_SIGNATURE:
        return f"Executable is missing PE signature: {target}"
    coff_offset = e_lfanew + 4
    machine, section_count, _timestamp, _sym_ptr, _sym_count, optional_size, _characteristics = struct.unpack_from(
        "<HHIIIHH",
        data,
        coff_offset,
    )
    if machine not in VALID_MACHINE_TYPES:
        return f"Executable has unsupported machine type: 0x{machine:04X}"
    if section_count <= 0 or section_count > MAX_SECTION_COUNT:
        return f"Executable has invalid section count: {section_count}"
    if optional_size <= 0:
        return "Executable has empty optional header"
    optional_offset = coff_offset + 20
    optional_end = optional_offset + optional_size
    if optional_end > len(data):
        return "Executable optional header is truncated"
    optional_magic = struct.unpack_from("<H", data, optional_offset)[0]
    if optional_magic not in VALID_OPTIONAL_MAGIC:
        return f"Executable has invalid optional header magic: 0x{optional_magic:04X}"
    section_table_end = optional_end + (section_count * 40)
    if section_table_end > len(data):
        return "Executable section table is truncated"
    return None


def pe_file_metadata(path: Path) -> dict[str, object]:
    failure = validate_pe_file(path)
    if failure is not None:
        raise ValueError(failure)
    data = Path(path).read_bytes()
    pe_offset = struct.unpack_from("<I", data, 0x3C)[0]
    machine = struct.unpack_from("<H", data, pe_offset + 4)[0]
    optional_magic = struct.unpack_from("<H", data, pe_offset + 24)[0]
    return {
        "machine_type": f"0x{machine:04X}",
        "format": "PE32+" if optional_magic == 0x20B else "PE32",
    }


def is_valid_pe_file(path: Path) -> bool:
    return validate_pe_file(path) is None

"""The symbol tables of ELF files, read with the standard library only, so that the servers' kit can
check a game's libraries (nwi_server_kit.check_gamedata) without pyelftools."""

import struct
from pathlib import Path

# The section types of symbol tables: SHT_SYMTAB and SHT_DYNSYM
SYMBOL_TABLES = (2, 11)


def symbols(path: Path) -> set[str]:
    """The names of an ELF file's symbol tables (.symtab and .dynsym)."""
    data = path.read_bytes()
    if data[:4] != b"\x7fELF":
        raise ValueError(f"{path} isn't an ELF file")
    wide = data[4] == 2
    order = "<" if data[5] == 1 else ">"
    if wide:
        (shoff,) = struct.unpack_from(order + "Q", data, 0x28)
        shentsize, shnum = struct.unpack_from(order + "HH", data, 0x3A)
    else:
        (shoff,) = struct.unpack_from(order + "I", data, 0x20)
        shentsize, shnum = struct.unpack_from(order + "HH", data, 0x2E)
    sections = []
    for index in range(shnum):
        base = shoff + index * shentsize
        if wide:
            _, kind, _, _, offset, size, link, _, _, entsize = struct.unpack_from(
                order + "IIQQQQIIQQ", data, base
            )
        else:
            _, kind, _, _, offset, size, link, _, _, entsize = struct.unpack_from(
                order + "IIIIIIIIII", data, base
            )
        sections.append((kind, offset, size, link, entsize))
    names = set()
    for kind, offset, size, link, entsize in sections:
        if kind not in SYMBOL_TABLES or not entsize:
            continue
        strings = sections[link][1]
        for entry in range(offset, offset + size, entsize):
            (name,) = struct.unpack_from(order + "I", data, entry)
            end = data.index(b"\0", strings + name)
            names.add(data[strings + name : end].decode("utf-8", "replace"))
    return names

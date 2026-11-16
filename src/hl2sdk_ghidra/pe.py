"""Unique SourceMod-style byte signatures for functions of a Windows library (PE), 32-bit or 64-bit.

The bytes of absolute addresses (base relocations), the targets of relative calls and jumps, and on
x86_64 the displacements relative to RIP are wildcards; the pattern grows by whole instructions until
it matches only once in the library's executable sections.
"""

import re
from pathlib import Path

AMD64 = 0x8664
# IMAGE_SCN_MEM_EXECUTE
EXECUTABLE = 0x20000000
# The bytes read of a function at most
MAX_BYTES = 512
# The shortest signature
MIN_BYTES = 8

Pattern = list[int | None]


def format_signature(pattern: Pattern) -> str:
    """A pattern as SourceMod's gamedata writes it, \\x2A for a wildcard."""
    return "".join("\\x2A" if byte is None else f"\\x{byte:02X}" for byte in pattern)


class Library:
    """A Windows library, read for signatures."""

    def __init__(self, path: Path) -> None:
        import capstone
        import pefile

        self.pe = pefile.PE(str(path))
        self.wide = self.pe.FILE_HEADER.Machine == AMD64
        self.base = self.pe.OPTIONAL_HEADER.ImageBase
        # The bytes of absolute addresses: IMAGE_REL_BASED_HIGHLOW (3) or DIR64 (10)
        self.relocated: set[int] = set()
        for block in getattr(self.pe, "DIRECTORY_ENTRY_BASERELOC", []):
            for entry in block.entries:
                if entry.type == 3:
                    self.relocated.update(range(entry.rva, entry.rva + 4))
                elif entry.type == 10:
                    self.relocated.update(range(entry.rva, entry.rva + 8))
        self.code = [
            section.get_data()
            for section in self.pe.sections
            if section.Characteristics & EXECUTABLE
        ]
        self.disassembler = capstone.Cs(
            capstone.CS_ARCH_X86,
            capstone.CS_MODE_64 if self.wide else capstone.CS_MODE_32,
        )
        self.disassembler.detail = True

    def count(self, pattern: Pattern) -> int:
        """How often a pattern is in the executable sections."""
        regex = re.compile(
            b"".join(
                b"." if byte is None else re.escape(bytes([byte])) for byte in pattern
            ),
            re.DOTALL,
        )
        return sum(len(regex.findall(data)) for data in self.code)

    def signature(self, address: int) -> Pattern | None:
        """The shortest unique signature of the function at a virtual address (with the image base),
        or None if none is unique."""
        import capstone.x86

        rva = address - self.base
        pattern: Pattern = []
        for instruction in self.disassembler.disasm(
            self.pe.get_data(rva, MAX_BYTES), rva
        ):
            data: Pattern = list(instruction.bytes)
            for index in range(len(data)):
                if instruction.address + index in self.relocated:
                    data[index] = None
            # rel32 targets of calls and jumps
            opcode = instruction.bytes[0]
            if opcode in (0xE8, 0xE9) or (
                opcode == 0x0F and 0x80 <= instruction.bytes[1] <= 0x8F
            ):
                data[-4:] = [None] * 4
            # Displacements relative to RIP
            if (
                self.wide
                and instruction.disp_size
                and any(
                    operand.type == capstone.x86.X86_OP_MEM
                    and operand.mem.base == capstone.x86.X86_REG_RIP
                    for operand in instruction.operands
                )
            ):
                start = instruction.disp_offset
                data[start : start + instruction.disp_size] = [
                    None
                ] * instruction.disp_size
            pattern += data
            if len(pattern) >= MIN_BYTES and self.count(pattern) == 1:
                return pattern
        return None

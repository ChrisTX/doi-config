#!/usr/bin/env python3
"""Make unique SourceMod-style byte signatures for functions of a Windows library (PE).

    pe_signature.py DLL ADDRESS...

ADDRESS is a function's virtual address (as Ghidra shows it, with the image base). The bytes of
absolute addresses (base relocations), the targets of relative calls and jumps, and on x86_64 the
displacements relative to RIP are wildcards; the pattern grows by whole instructions until it matches
only once in the library's executable sections.
"""

import re
import sys

import capstone
import capstone.x86
import pefile

AMD64 = 0x8664


def main() -> None:
    if len(sys.argv) < 3:
        sys.exit(__doc__)
    pe = pefile.PE(sys.argv[1])
    wide = pe.FILE_HEADER.Machine == AMD64
    base = pe.OPTIONAL_HEADER.ImageBase
    # The bytes of absolute addresses: IMAGE_REL_BASED_HIGHLOW (3) or DIR64 (10)
    relocated = set()
    for block in getattr(pe, "DIRECTORY_ENTRY_BASERELOC", []):
        for entry in block.entries:
            if entry.type == 3:
                relocated.update(range(entry.rva, entry.rva + 4))
            elif entry.type == 10:
                relocated.update(range(entry.rva, entry.rva + 8))
    code = [s.get_data() for s in pe.sections if s.Characteristics & 0x20000000]
    disassembler = capstone.Cs(
        capstone.CS_ARCH_X86, capstone.CS_MODE_64 if wide else capstone.CS_MODE_32
    )
    disassembler.detail = True

    def count(pattern: list[int | None]) -> int:
        regex = re.compile(
            b"".join(b"." if b is None else re.escape(bytes([b])) for b in pattern),
            re.DOTALL,
        )
        return sum(len(regex.findall(data)) for data in code)

    for argument in sys.argv[2:]:
        rva = int(argument, 16) - base
        pattern: list[int | None] = []
        result = None
        for ins in disassembler.disasm(pe.get_data(rva, 512), rva):
            data: list[int | None] = list(ins.bytes)
            for i in range(len(data)):
                if ins.address + i in relocated:
                    data[i] = None
            # rel32 targets of calls and jumps
            opcode = ins.bytes[0]
            if opcode in (0xE8, 0xE9) or (
                opcode == 0x0F and 0x80 <= ins.bytes[1] <= 0x8F
            ):
                data[-4:] = [None] * 4
            # displacements relative to RIP
            if (
                wide
                and ins.disp_size
                and any(
                    op.type == capstone.x86.X86_OP_MEM
                    and op.mem.base == capstone.x86.X86_REG_RIP
                    for op in ins.operands
                )
            ):
                data[ins.disp_offset : ins.disp_offset + ins.disp_size] = [
                    None
                ] * ins.disp_size
            pattern += data
            if len(pattern) >= 8 and count(pattern) == 1:
                result = pattern
                break
        if result:
            signature = "".join("\\x2A" if b is None else f"\\x{b:02X}" for b in result)
            print(f"{argument}: {len(result)} bytes {signature}")
        else:
            print(f"{argument}: not unique")


if __name__ == "__main__":
    main()

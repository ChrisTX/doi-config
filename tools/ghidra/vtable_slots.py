#!/usr/bin/env python3
"""List the virtual methods of classes with their vtable slot, from DWARF.

    vtable_slots.py OBJECT CLASS...

OBJECT is an object of sdk_types.sh (--no-gdt is enough), whose DWARF has the SDK's classes with their
vtable slots as the headers lay them out, e.g. the interfaces Metamod:Source and SourceMod hook, to
compare with the vtables of a game's binaries. Each line: the class, the slot, the method and its
mangled name.
"""

import sys

from elftools.elf.elffile import ELFFile


def main() -> None:
    if len(sys.argv) < 3:
        sys.exit(__doc__)
    wanted = set(sys.argv[2:])
    seen = set()
    with open(sys.argv[1], "rb") as f:
        dwarf = ELFFile(f).get_dwarf_info()
        for unit in dwarf.iter_CUs():
            for die in unit.iter_DIEs():
                if die.tag not in ("DW_TAG_class_type", "DW_TAG_structure_type"):
                    continue
                name = die.attributes.get("DW_AT_name")
                if not name or "DW_AT_declaration" in die.attributes:
                    continue
                cls = name.value.decode()
                if cls not in wanted or cls in seen:
                    continue
                seen.add(cls)
                for child in die.iter_children():
                    location = child.attributes.get("DW_AT_vtable_elem_location")
                    if child.tag != "DW_TAG_subprogram" or not location:
                        continue
                    # DW_OP_constu <slot>, as a list of the expression's bytes or a number
                    slot = (
                        location.value[1]
                        if isinstance(location.value, list)
                        else location.value
                    )
                    linkage = child.attributes.get("DW_AT_linkage_name")
                    method = child.attributes["DW_AT_name"].value.decode()
                    print(cls, slot, method, linkage.value.decode() if linkage else "")


if __name__ == "__main__":
    main()

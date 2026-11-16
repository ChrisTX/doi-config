"""The virtual methods of the SDK's classes with their vtable slots, from the DWARF of an SDK object
(sdk.py), e.g. the interfaces Metamod:Source and SourceMod hook, as the SDK's headers lay them out, to
compare with the vtables of a game's binaries (check.py)."""

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Method:
    """A virtual method: its class, slot, name and mangled name."""

    cls: str
    slot: int
    name: str
    mangled: str


def vtable_slots(sdk_object: Path, classes: list[str]) -> list[Method]:
    """The virtual methods of the classes, of the first definition of each in the object's DWARF."""
    from elftools.elf.elffile import ELFFile

    wanted = set(classes)
    seen = set()
    methods = []
    with sdk_object.open("rb") as file:
        dwarf = ELFFile(file).get_dwarf_info()
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
                    methods.append(
                        Method(
                            cls,
                            int(slot),
                            child.attributes["DW_AT_name"].value.decode(),
                            linkage.value.decode() if linkage else "",
                        )
                    )
    return methods

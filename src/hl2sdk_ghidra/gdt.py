"""The SDK's types and function signatures as a Ghidra data type archive (.gdt), and brought into a
game's program.

The archive has every type of the SDK object's DWARF (sdk.py), and each function's signature as a
function definition under /SdkFunctions, named by its mangled name, so that overloads (and GCC's
several names of constructors and destructors) stay apart. Applied to a program, it brings in the
composite types, replaces the demangler's empty stand-ins of the same name, and applies the signatures
by the exact mangled names of the program's functions.
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from . import ghidra

if TYPE_CHECKING:
    from ghidra.program.model.data import DataType
    from ghidra.program.model.listing import Program

SDK_FUNCTIONS = "/SdkFunctions"
# The seconds the decompiler has for a function
DECOMPILE_TIMEOUT = 120


def mangled_names(found: "Program", entry: "object") -> list[str]:
    """The mangled names of a function's entry point: GCC emits constructors and destructors under
    several (C1 complete, C2 base, D0/D1/D2) at the same address, and callers use any of them."""
    return [
        symbol.getName()
        for symbol in found.getSymbolTable().getSymbols(entry)
        if symbol.getName().startswith("_Z")
    ]


def export(found: "Program", output: Path) -> tuple[int, int]:
    """Save the program's types and its functions' signatures as the archive OUTPUT; returns how many
    types and signatures."""
    from ghidra.program.model.data import (
        BuiltInDataType,
        CategoryPath,
        DataTypeConflictHandler,
        FileDataTypeManager,
        FunctionDefinition,
        FunctionDefinitionDataType,
    )
    from java.io import File

    output.unlink(missing_ok=True)
    types = signatures = 0
    archive = FileDataTypeManager.createFileArchive(File(str(output)))
    # Closed on errors too: an archive left open stays locked until Ghidra exits
    try:
        transaction = archive.startTransaction("SDK types")
        try:
            for data_type in found.getDataTypeManager().getAllDataTypes():
                if isinstance(data_type, (BuiltInDataType, FunctionDefinition)):
                    continue
                archive.resolve(data_type, DataTypeConflictHandler.KEEP_HANDLER)
                types += 1
            category = CategoryPath(SDK_FUNCTIONS)
            for function in found.getFunctionManager().getFunctions(True):
                for name in mangled_names(found, function.getEntryPoint()):
                    definition = FunctionDefinitionDataType(function, False)
                    definition.setNameAndCategory(category, name)
                    archive.resolve(definition, DataTypeConflictHandler.REPLACE_HANDLER)
                    signatures += 1
        finally:
            archive.endTransaction(transaction, True)
        archive.save()
    finally:
        archive.close()
    return types, signatures


def build(sdk_object: Path, output: Path) -> tuple[int, int]:
    """The archive of an SDK object: imported into a temporary project, whose DWARF analyser reads the
    types, and exported."""
    with ghidra.target(None, str(sdk_object)) as found:
        return export(found, output)


@dataclass
class Applied:
    """What applying an archive did."""

    added: int = 0
    replaced: int = 0
    signatures: int = 0
    ambiguous: int = 0
    skipped: list[str] = field(default_factory=list)


def apply(found: "Program", archive_path: Path) -> Applied:
    """Bring the archive's types and signatures into the program, see the module's documentation."""
    import pyghidra
    from ghidra.app.cmd.function import ApplyFunctionSignatureCmd
    from ghidra.program.model.data import (
        Composite,
        DataTypeConflictHandler,
        DataTypeDependencyException,
        FileDataTypeManager,
        FunctionDefinition,
    )
    from ghidra.program.model.symbol import SourceType
    from java.io import File
    from java.lang import IllegalArgumentException

    result = Applied()
    manager = found.getDataTypeManager()
    archive = FileDataTypeManager.openFileArchive(File(str(archive_path)), False)
    try:
        with pyghidra.transaction(found, "SDK types"):
            definitions: dict[str, list[FunctionDefinition]] = {}
            full: dict[str, DataType] = {}
            # Composite types, in two passes: resolve all (their dependencies come along), then
            # replace the demangler's empty stand-ins of the same name that are still there.
            # replaceDataType keeps the stand-in's path, e.g. a class stays under /Demangler.
            for data_type in archive.getAllDataTypes():
                if isinstance(data_type, FunctionDefinition):
                    if data_type.getCategoryPath().getPath() == SDK_FUNCTIONS:
                        definitions.setdefault(data_type.getName(), []).append(
                            data_type
                        )
                    continue
                if not isinstance(data_type, Composite) or data_type.isNotYetDefined():
                    continue
                resolved = manager.resolve(
                    data_type, DataTypeConflictHandler.KEEP_HANDLER
                )
                full.setdefault(data_type.getName(), resolved)
                result.added += 1
            # A stand-in is an empty or undefined composite of the same name that isn't the resolved
            # type itself, compared by its ID in the program
            stand_ins = [
                data_type
                for data_type in manager.getAllDataTypes()
                if isinstance(data_type, Composite)
                and (data_type.isNotYetDefined() or data_type.getLength() <= 1)
                and data_type.getName() in full
                and manager.getID(full[data_type.getName()]) != manager.getID(data_type)
            ]
            for stand_in in stand_ins:
                if not manager.contains(stand_in):
                    continue
                try:
                    manager.replaceDataType(stand_in, full[stand_in.getName()], True)
                    result.replaced += 1
                # A replacement that would depend on the stand-in itself, or doesn't fit it
                except (DataTypeDependencyException, IllegalArgumentException) as error:
                    result.skipped.append(f"{stand_in.getPathName()}: {error}")
            # Signatures by the exact mangled name of each function, so every overload gets its own
            for function in list(found.getFunctionManager().getFunctions(True)):
                for name in mangled_names(found, function.getEntryPoint()):
                    candidates = definitions.get(name)
                    if candidates is None:
                        continue
                    if len(candidates) != 1:
                        result.ambiguous += 1
                        continue
                    command = ApplyFunctionSignatureCmd(
                        function.getEntryPoint(), candidates[0], SourceType.USER_DEFINED
                    )
                    if command.applyTo(found, pyghidra.task_monitor()):
                        result.signatures += 1
                    break
    finally:
        archive.close()
    return result


def decompile(found: "Program", addresses: list[int], folder: Path, label: str) -> None:
    """Decompile the functions at the addresses into FOLDER/<function>.<label>.c, to compare."""
    import pyghidra
    from ghidra.app.decompiler import DecompInterface

    folder.mkdir(parents=True, exist_ok=True)
    decompiler = DecompInterface()
    try:
        decompiler.openProgram(found)
        for offset in addresses:
            function = found.getFunctionManager().getFunctionAt(
                ghidra.address(found, offset)
            )
            if function is None:
                print(f"No function at {offset:#x}")
                continue
            results = decompiler.decompileFunction(
                function, DECOMPILE_TIMEOUT, pyghidra.task_monitor()
            )
            text = (
                results.getDecompiledFunction().getC()
                if results.decompileCompleted()
                else f"FAILED {results.getErrorMessage()}"
            )
            (folder / f"{function.getName()}.{label}.c").write_text(str(text))
    finally:
        decompiler.dispose()

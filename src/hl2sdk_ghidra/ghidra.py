"""Ghidra, in this process through PyGhidra: projects, and programs imported into them and opened.

Ghidra is GHIDRA_INSTALL_DIR's, /opt/ghidra by default, with GHIDRA_HEADLESS_MAXMEM of memory (16G by
default, which the import of an SDK object needs). A project is named by its .gpr file; one open
in Ghidra's GUI is locked, close it there first. Without a project, a temporary one is used, which is
removed afterwards.
"""

import os
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ghidra.framework.model import Project
    from ghidra.program.model.address import Address
    from ghidra.program.model.listing import Program

# Flags returning functions, e.g. Plat_FloatTime, as not returning, which hides the calls after them
# (ghidra#9769): off before a new program is analysed
NO_RETURN_ANALYSER = "Non-Returning Functions - Discovered"


def start() -> None:
    """Start the JVM and Ghidra, once."""
    import pyghidra
    from pyghidra.launcher import HeadlessPyGhidraLauncher

    if not pyghidra.started():
        launcher = HeadlessPyGhidraLauncher(
            install_dir=Path(os.environ.get("GHIDRA_INSTALL_DIR", "/opt/ghidra"))
        )
        launcher.add_vmargs(f"-Xmx{os.environ.get('GHIDRA_HEADLESS_MAXMEM', '16G')}")
        launcher.start()


@contextmanager
def project(gpr: Path | None) -> Iterator["Project"]:
    """The project of a .gpr file, made if it's missing; without one, a temporary project."""
    start()
    import pyghidra

    with tempfile.TemporaryDirectory() as temporary:
        if gpr is None:
            location, name = Path(temporary), "hl2sdk-ghidra"
        else:
            if gpr.suffix != ".gpr":
                raise ValueError(f"not a Ghidra project's .gpr file: {gpr}")
            location, name = gpr.parent, gpr.stem
            location.mkdir(parents=True, exist_ok=True)
        opened = pyghidra.open_project(location, name, create=True)
        try:
            yield opened
        finally:
            opened.close()


def import_program(opened: "Project", binary: Path, folder: str = "/") -> str:
    """Import a binary into the project's folder, unless it's there already, and analyse it; returns
    its path in the project."""
    import pyghidra
    from java.io import File

    path = f"{folder.rstrip('/')}/{binary.name}"
    if opened.getProjectData().getFile(path) is not None:
        return path
    loader = (
        pyghidra.program_loader()
        .source(File(str(binary)))
        .project(opened)
        .projectFolderPath(folder)
    )
    with loader.load() as results:
        results.save(pyghidra.task_monitor())
    with program(opened, path, save=True) as loaded:
        analyse(loaded)
    return path


def analyse(loaded: "Program") -> None:
    """Analyse a program, without the analyser that flags returning functions as not returning."""
    import pyghidra

    with pyghidra.transaction(loaded, "Analysis options"):
        options = pyghidra.analysis_properties(loaded)
        if options.contains(NO_RETURN_ANALYSER):
            options.setBoolean(NO_RETURN_ANALYSER, False)
    pyghidra.analyze(loaded)


@contextmanager
def program(opened: "Project", path: str, save: bool = False) -> Iterator["Program"]:
    """A program of the project, by its path there (e.g. /doi/server_srv.so); saved afterwards with
    SAVE."""
    import pyghidra

    with pyghidra.program_context(opened, path) as found:
        yield found
        if save and found.isChanged():
            found.save("hl2sdk-ghidra", pyghidra.task_monitor())


@contextmanager
def target(gpr: Path | None, name: str, save: bool = False) -> Iterator["Program"]:
    """The program NAME: a binary, a file, imported into the project, or else a program's path in the
    project (e.g. /doi/server_srv.so)."""
    with project(gpr) as opened:
        if Path(name).is_file():
            path = import_program(opened, Path(name).absolute())
        elif name.startswith("/"):
            path = name
        else:
            raise ValueError(
                f"neither a file nor a program's path in the project: {name}"
            )
        with program(opened, path, save) as found:
            yield found


def address(found: "Program", offset: int) -> "Address":
    """The address of an offset in the program's default address space."""
    return found.getAddressFactory().getDefaultAddressSpace().getAddress(offset)

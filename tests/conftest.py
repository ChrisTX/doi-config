"""The fixtures of the tests: a fake updater's state of layers and a fake /run, in a temporary folder,
which layers.py, health.py and notify.py use instead of the system's."""

import json
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import pytest

from nwi_server_kit import health, layers, notify


@dataclass
class State:
    """The fake state: the layers, the source the versions are copies of, and the server's files."""

    root: Path
    layers: Path
    source: Path

    def version(self, layer: str, version: str, good: bool = False) -> Path:
        """A version of a layer, on trial, or good."""
        path = layers.snapshot(self.source, layers.folder(self.layers, layer), version)
        return layers.renamed(path, None) if good else path

    def mounted(
        self, name: str, versions: list[Path], core: list[Path], maps: dict[str, Path]
    ) -> None:
        """A server's record of its versions, as mount.py writes it, and its health folder."""
        health.IN_USE.mkdir(parents=True, exist_ok=True)
        (health.RUN / name).mkdir(parents=True, exist_ok=True)

        def canonical(path: Path) -> str:
            return str(layers.canonical(path))

        record = {
            "versions": [canonical(path) for path in versions],
            "core": [canonical(path) for path in core],
            "maps": {map_name: canonical(path) for map_name, path in maps.items()},
        }
        (health.IN_USE / name).write_text(json.dumps(record))

    def status(self, name: str, invocation: str, **values: object) -> None:
        """The status the server's watchdog writes."""
        status = {
            "invocation": invocation,
            "ready": True,
            "map": None,
            "busy_seconds": 0,
            "completed": [],
        }
        (health.RUN / name / "status.json").write_text(json.dumps(status | values))

    def notifications(self) -> list[str]:
        """The subjects of the queued notifications."""
        if not notify.QUEUE.is_dir():
            return []
        return [
            json.loads(path.read_text())["subject"]
            for path in sorted(notify.QUEUE.glob("*.json"))
        ]


@pytest.fixture
def state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> State:
    root = tmp_path
    (root / "layers").mkdir()
    source = root / "source"
    source.mkdir()
    (source / "file").write_text("content\n")
    monkeypatch.setattr(layers, "IN_USE", root / "run/in-use")
    monkeypatch.setattr(health, "IN_USE", root / "run/in-use")
    monkeypatch.setattr(health, "RUN", root / "run/health")
    monkeypatch.setattr(health, "STATE", root / "state")
    monkeypatch.setattr(health, "LAYERS", root / "layers")
    monkeypatch.setattr(notify, "QUEUE", root / "run/notify")
    for variable in (
        "NWI_TRIES",
        "NWI_KEEP_VERSIONS",
        "NWI_BLESS_PLAYERS",
        "NWI_BLESS_MINUTES",
    ):
        monkeypatch.delenv(variable, raising=False)
    return State(root, root / "layers", source)


@pytest.fixture
def run(monkeypatch: pytest.MonkeyPatch) -> Callable[[str], str]:
    """Set the server's run, systemd's INVOCATION_ID, as ExecStopPost= has it."""

    def start(invocation: str) -> str:
        monkeypatch.setenv("INVOCATION_ID", invocation)
        return invocation

    return start

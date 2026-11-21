# Contributing

Thanks for helping with this configuration. It's the configuration of the Kim Jong Un Day of Infamy servers: the game's configuration files, the scripts that set up and update a server, the systemd units that run and monitor it, and a few SourceMod plugins. See the [README](README.md) for how it's used on a server.

## Reporting problems

For problems with a server or a script, open an issue. Problems of the game, SourceMod, Metamod:Source, SourceBans or a plugin that aren't caused by this configuration belong upstream.

## Getting started

The tools of the checks are in the Arch Linux repositories, apart from six from the AUR: SourceMod's compiler `spcomp`, which comes with `sourcemod-scripting`, `hadolint`, `python-srctools`, the library the tools read the game's files with (KeyValues, VDF, VPK), `python-a2s`, the watchdog's queries of the servers, `python-jpype1`, which PyGhidra runs Ghidra with for hl2sdk-ghidra, and `powershell`, which runs PSScriptAnalyzer on the client's PowerShell scripts. PSScriptAnalyzer itself isn't in the AUR, so install it into PowerShell with `pwsh -Command 'Install-Module PSScriptAnalyzer'` (the servers' version is 1.25.0). PyGhidra comes with Ghidra, as a wheel in `/opt/ghidra/Ghidra/Features/PyGhidra/pypkg/dist`, and the virtual environment below has it:

```bash
sudo pacman -S --needed prek shfmt shellcheck shellharden ruff mypy \
  python-pytest systemd-lsp yamllint tombi rumdl typos trivy \
  editorconfig-checker reuse clang ghidra jdk21-openjdk python-pyelftools \
  python-capstone python-pefile
```

clang's `clang-format` formats the C++ of hl2sdk-ghidra, `src/hl2sdk_ghidra/sdk_types.cpp`. Ghidra's own type stubs (`/opt/ghidra/docs/ghidra_stubs`) let mypy check hl2sdk-ghidra's use of Ghidra's API; the virtual environment has them.

What runs where:

- `src/`: the packages, everything a server, its updates and its admins run. In `src/nwi_server_kit`, the modules are the library, and `cli/` has the command line of each: its arguments, what it prints and its exit status.
- `deploy/`: the systemd units, the container image, the Quadlet units and the package (`deploy/arch/PKGBUILD`).
- `checks/`: what the git hooks and GitHub Actions run on the repository's files, e.g. the check of the game's configs against the game's cvars (`checks/cvars/<game>.json`, which `checks/dump_cvars.py` makes of a running server, `tests/integration/instance.py dump-cvars`).
- `tests/unit/`: the tests of the packages (pytest).
- `tests/integration/`: the tests with real servers: the test instance (`tests/integration/instance.py`), the image with sanitiser builds, the soak test (`instance.py soak`, its config in `tests/integration/servers`) the round test (`instance.py rounds`, `tests/integration/rounds.py`) and the stress test of the network (`instance.py stress`, `tests/integration/stress.py`). Neither `checks/` nor `tests/` is installed.

The tools are a Python package, `src/nwi_server_kit`, with the commands `nwi-server` and `nwi-rcon`, and the Ghidra tools another, `src/hl2sdk_ghidra`, with the command `hl2sdk-ghidra` (see [its README](src/hl2sdk_ghidra/README.md)). Instead of the Python packages, its dependencies can come from a virtual environment: `pyproject.toml` lists them, `uv.lock` pins their versions and checksums, mypy's and pytest's included, of the development group. [uv](https://docs.astral.sh/uv/) (the `uv` package) makes it in `.venv`, with the package installed from the checkout, which the hooks then use while it's active:

```bash
uv sync
source .venv/bin/activate
```

After changing the dependencies in `pyproject.toml`, `uv lock` updates `uv.lock`; `uv lock --upgrade` takes their newest versions. Keep them at the versions of the Arch Linux packages the servers run.

Then install the git hooks, which run the checks on the staged files before each commit and check the spelling of the commit message:

```bash
prek install
```

`pre-commit` works the same way as `prek`. To run the checks on all files, e.g. after changing `.pre-commit-config.yaml`:

```bash
prek run --all-files
```

GitHub Actions runs the same checks on every push and pull request. The AUR isn't available there: it builds spcomp from the SourceMod release the servers run, downloads the releases of hadolint and PowerShell (then PSScriptAnalyzer from the PowerShell Gallery), and makes the virtual environment of `uv.lock`, see `.github/workflows/check.yml`.

## Checks

- Shell scripts are formatted with shfmt and pass shellcheck and shellharden. Write `cd … || exit` instead of disabling SC2164.
- PowerShell scripts (`client/*.ps1`) pass PSScriptAnalyzer (`checks/psscriptanalyzer.ps1`, with the rules in `checks/PSScriptAnalyzerSettings.psd1`). The excluded rules are for reusable modules; suppress nothing else without a reason.
- Python scripts are formatted with ruff and pass `ruff check`. Suppress a rule only where the code can't comply, with `# noqa: <rule>` and a comment saying why.
- The Python code passes mypy, with the settings of `pyproject.toml`: functions without annotations are checked too. Narrow a type where it's ambiguous, e.g. a KeyValues value that may be a string or a block, rather than casting it or ignoring the error.
- The tests in `tests/unit/` pass: `python3 -m pytest`. They run the code on fake state in temporary folders, never the system's; a change of the layers, their trial (`health.py`) or what the watchdog records comes with tests. The tests of the Workshop uploads build a stand-in of the Steamworks API's library, `tests/unit/fake_steam_api.c`, with the C compiler (`cc`).
- The SourceMod plugins (`game/common/addons/sourcemod/scripting/*.sp`) compile without warnings: `spcomp -E`.
- C and C++ (`src/hl2sdk_ghidra/sdk_types.cpp`, `tests/unit/fake_steam_api.c`) are formatted with `clang-format` (`.clang-format`).
- The Containerfile passes hadolint and `trivy config`.
- systemd units pass systemd-lsp, the GitHub files yamllint, Markdown files rumdl, TOML files tombi (formatted with `tombi format`, checked with `tombi lint`).
- Everything follows `.editorconfig`, checked by editorconfig-checker. Formatters fix files themselves; run the check again afterwards.
- The MOTDs (`servers/*/motd.txt`) keep their trailing whitespace, which the game needs to render them as intended.
- Patches have to apply as they are, so they're left as they are, line endings included.
- Every file has copyright and licence information, checked by `reuse lint`. Files of this repository are MIT, which `REUSE.toml` covers. A file under another licence, like the vendored AFK Manager, says so in an SPDX header or gets its own annotation in `REUSE.toml`.
- Built files like `.smx` plugins don't belong into the repository, they're built on the server by its updates (`nwi-server update`).

## Writing

- Texts are in British English: documentation, comments, commit messages and what players see, like the MOTDs and advertisements. Names keep their spelling, e.g. cvars, keywords of file formats, the game's terms like "theater", and texts from upstream like the licence texts and vendored code. Terms of software keep theirs too, like "sanitizer" (the compilers' -fsanitize), as in the AUR packages. typos checks the spelling of the files, American spellings included; the names, terms and files it leaves alone are in `.typos.toml`.

## Commits

- One commit per logical change.
- Message summary: `<scope>: <summary>`, where the scope is the script, file or area that changes (e.g. `launch:`, `MOTD:`, `systemd:`, `.github:`). The summary is imperative (`Add …`, `Fix …`, `Remove …`), without a trailing period. The commit-msg hook checks it: the scope has to be a file or folder of the repository, by its name with or without the extension, or one of the areas in `checks/check_commit_msg.sh`.
- The body says why, where the summary doesn't.

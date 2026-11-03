# Contributing

Thanks for helping with this configuration. It's the configuration of the Kim Jong Un Day of Infamy servers: the game's configuration files, the scripts that set up and update a server, the systemd units that run and monitor it, and a few SourceMod plugins. See the [README](README.md) for how it's used on a server.

## Reporting problems

For problems with a server or a script, open an issue. Problems of the game, SourceMod, Metamod:Source, SourceBans or a plugin that aren't caused by this configuration belong upstream.

## Getting started

The tools of the checks are all in the Arch Linux repositories:

```bash
sudo pacman -S --needed prek shfmt shellcheck shellharden ruff systemd-lsp \
  yamllint rumdl editorconfig-checker reuse
```

Then install the git hooks, which run the checks on the staged files before each commit:

```bash
prek install
```

`pre-commit` works the same way as `prek`. To run the checks on all files, e.g. after changing `.pre-commit-config.yaml`:

```bash
prek run --all-files
```

GitHub Actions runs the same checks on every push and pull request.

## Checks

- Shell scripts are formatted with shfmt and pass shellcheck and shellharden. Write `cd … || exit` instead of disabling SC2164.
- Python scripts are formatted with ruff and pass `ruff check`. Suppress a rule only where the code can't comply, with `# noqa: <rule>` and a comment saying why.
- systemd units pass systemd-lsp, the GitHub files yamllint, Markdown files rumdl.
- Everything follows `.editorconfig`, checked by editorconfig-checker. Formatters fix files themselves; run the check again afterwards.
- The MOTDs in `texts/` keep their trailing whitespace, which the game needs to render them as intended.
- The map files in `mods/` are copies of the game's own files and patches have to apply as they are, so both are left as they are, line endings included.
- Every file has copyright and licence information, checked by `reuse lint`. Files of this repository are MIT, which `REUSE.toml` covers. A file under another licence, like the vendored AFK Manager, says so in an SPDX header or gets its own annotation in `REUSE.toml`.
- Built files like `.smx` plugins don't belong into the repository, they're built on the server by `prepare_server.sh`. The patched server binary in `server-patch/` is the exception.

## Writing

- Texts are in British English: documentation, comments, commit messages and what players see, like the MOTDs and advertisements. Names keep their spelling, e.g. cvars, keywords of file formats, the game's terms like "theater", and texts from upstream like the licence texts and vendored code.

## Commits

- One commit per logical change.
- Message summary: `<scope>: <summary>`, where the scope is the script, file or area that changes (e.g. `prepare_server:`, `MOTD:`, `systemd:`, `.github:`). The summary is imperative (`Add …`, `Fix …`, `Remove …`), without a trailing period.
- The body says why, where the summary doesn't.

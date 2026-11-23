<!--
SPDX-FileCopyrightText: Christian Pfeiffer
SPDX-License-Identifier: MIT
-->

# SourceMod patches for Windows

Fixes of SourceMod that the servers need on Windows, 64-bit above all, natively
or under Wine. They're for our own builds of SourceMod, not sent upstream yet:
see [Upstream](#upstream). Each patch's message says what it fixes, why, how to
reproduce it and how it was tested.

| Patch | Fixes | Shown with MSVC |
| --- | --- | --- |
| 0001 | x86_64 DHooks detours return the return address instead of the function's value | yes, on top of 0004 |
| 0002 | x86_64 DHooks crash creating detours, after a dozen or so | yes |
| 0003 | DHooks params of a second setup of a detoured function read wrongly | no, with clang-cl's build |
| 0004 | x86_64 Windows DHooks crash on thiscall detours (alliedmodders/sourcemod#2282) | yes |
| 0005 | x86_64 Windows DHooks params in registers read garbage; needs 0004 | no, with clang-cl's build |
| 0006 | x86_64 Windows servers crash at the first map start if a plugin loaded at startup uses SDK Hooks | yes |

0001 to 0005 are needed by `nwi_gamedata`'s detours on 64-bit Windows, for
rounds with bots only and the server's visibility. 0006 doesn't depend on
DHooks: any plugin that uses SDK Hooks and is loaded at the server's start
crashes a 64-bit Windows server without it. 0003 and 0005 fix reads of
registers whose contents depend on the compiler, so their bugs show with
clang-cl's builds but not with MSVC's in the same tests; they're still bugs of
the code.

## Applying them

The series applies to SourceMod's master at `cfcda295`, the merge of
alliedmodders/sourcemod#2611, with git, which keeps each patch's message as its commit's:

```bash
git -C sourcemod am --keep-cr /path/to/doi-config/patches/sourcemod/*.patch
```

`--keep-cr` keeps the line endings of SDK Hooks' `extension.cpp`, which are
CRLF; without it, `git am` strips them and 0006 doesn't apply.

Then build SourceMod as usual, for Windows with MSVC. With the series, a 64-bit and a 32-bit Day of Infamy
server on Windows 11 ran with all of SourceMod's extensions and 25 plugins,
the only error SourceMod's own sigscan of FireOutput; the round test's bots
played coop and PvP rounds on the 64-bit server under Wine.

## Upstream

alliedmodders/sourcemod#2403 and #2546 replace DHooks' detours, whose code
0001 to 0005 change, and it isn't clear yet whether x86_64 Windows detours are
meant to be supported before them. Once that's clearer, the DHooks patches
could go upstream, or their bugs as tests for the rewrite. 0006 is independent
of DHooks and could go upstream on its own. Until then, the patches are kept
here and rebased onto SourceMod's master when it moves.

# REA findings

## Decision

REA was not used for Milestone 0. RimSort source, The Indie Stone's Build 42 mod-system announcement, and existing Project Zomboid manager source were available. Broad binary analysis would add cost without answering a necessary Milestone 0 question.

## Focused questions still open

These questions do not block the current conservative implementation, which preserves candidate metadata and reports order suggestions as proposals. Revisit only before claiming the behavior as guaranteed or implementing build-specific conflict resolution:

- Which exact `common`/version candidate wins for every current-build edge case, including malformed metadata and multiple matching IDs?
- Which installed copy wins when separate entries declare the same Mod ID?
- For each PZ resource type, does an identical relative path replace, merge, or coexist at runtime?
- How does the game handle dependency/order cycles and malformed reference separators beyond the documented comma forms?

## Evidence collected without REA

- Local `ModSelectorModel.lua` distinguishes `default` global state from `currentGame` save/new-game state. A selected save is written through `WriteModsDotTxt`; the global state is saved via `saveModsFile()`. This was enough to scope a guarded global-only adapter; save writes remain unsupported.
- The same manager queries `getRequire`, `getIncompatible`, `getLoadAfter`, and `getLoadBefore`; its auto-order routine is visible in `ModLoadOrderPanel.lua`. The current app uses these declarations conservatively and does not claim full Java loader equivalence.
- The real `Zomboid/mods/default.txt` was parsed read-only and matched the strict version-1 `mods`/`maps` fixture. No game launch or write experiment was performed.
- The installed game reports Build 42.21.0, and the current `mod.info` API reference documents comma-separated dependency lists, ordering fields, version bounds, and repeatable `poster` values. The local library scan and log inspection were read-only.
- Workshop collection metadata can be requested through public Steamworks read-only endpoints. Subscription/download actions use different endpoints and remain out of scope.

No REA or binary analysis was needed. Ordinary source, the 42.21 mod.info reference, and controlled fixtures answered the questions required for the current milestones. Do not investigate the remaining runtime precedence questions until a specific feature needs them.

Start with documentation and inspect only the relevant files or a controlled local game fixture. Consider REA only if an executable behavior remains essential and undocumented; ask the user before installing REA or any substantial dependency. Record observations separately from assumptions and update this file rather than repeating the investigation.

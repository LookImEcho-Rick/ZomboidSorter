# Mod-manager list UX source review

Inspected 2026-10-24 to review warning separation and state continuity in ZomboidSorter's Discover and Active Order lists. This is an interaction-pattern comparison, not a proposal to import another game's data or sorting rules. Source references are pinned to the inspected commits because these repositories move frequently.

## Findings

### RimSort

- **Verified:** `app/views/mods_panel.py` uses custom list rows with distinct error and warning messages/icons, selection and hover states, and row-level actions. Its filtering and list coordination stay in the panel/controller boundary.
- **Relation to ZomboidSorter:** warning identity should remain attached to the row and list that can resolve it. Discover metadata/layout findings belong to Discover; missing or ambiguous configured Mod IDs and dependency findings belong to Active Order.
- **Do not transfer:** RimWorld's `About.xml`, Package IDs, mod-type checks, community rules, and tiered sort behavior.
- **Source:** [RimSort `mods_panel.py` at `4964bf8`](https://github.com/RimSort/RimSort/blob/4964bf8900aa31f946591cd1c711be58d0ef2873/app/views/mods_panel.py).

### Mod Organizer 2

- **Verified:** `src/modlistview.h/.cpp` builds a Qt `QTreeView` over separate sorting/grouping proxy models, exposes customizable columns and filter state, and marks list positions in a specialized scrollbar. The view handles keyboard, selection, drag/drop, and context-menu behavior around that model.
- **Relation to ZomboidSorter:** keep list state stable through rebuilds and preserve the existing staged model as the source of truth. A model/view rewrite is unnecessary for the current library size and would add complexity without measured benefit.
- **Do not transfer:** virtual filesystem behavior, priority semantics, plugin rules, or Skyrim-specific load-order mechanics.
- **Source:** [MO2 `modlistview.cpp`](https://github.com/ModOrganizer2/modorganizer/blob/4ba22f0d8b6f9e08e44008b8395cd774551b4ebe/src/modlistview.cpp), [header](https://github.com/ModOrganizer2/modorganizer/blob/4ba22f0d8b6f9e08e44008b8395cd774551b4ebe/src/modlistview.h), and [license](https://github.com/ModOrganizer2/modorganizer/blob/4ba22f0d8b6f9e08e44008b8395cd774551b4ebe/LICENSE).

### Vortex

- **Verified:** `ModList.tsx` composes a table with text and option filters, a toolbar, row actions, and an explicit no-results state. Its dependency-manager extension tracks unsolved conflicts and reports them through a separate conflict surface.
- **Relation to ZomboidSorter:** maintain compact search/filter controls and explicit empty states; keep deeper dependency explanations available on demand rather than crowding each row.
- **Do not transfer:** Vortex's extension framework, deployment/file-conflict model, or game-specific dependency rules.
- **Source:** [Vortex `ModList.tsx`](https://github.com/Nexus-Mods/Vortex/blob/cf009c405974332195f68a76d0fb386f1ecb5d98/src/renderer/src/extensions/mod_management/views/ModList.tsx), [dependency manager](https://github.com/Nexus-Mods/Vortex/blob/cf009c405974332195f68a76d0fb386f1ecb5d98/extensions/mod-dependency-manager/src/index.tsx), and [project license](https://github.com/Nexus-Mods/Vortex/blob/cf009c405974332195f68a76d0fb386f1ecb5d98/README.md).

### Gale

- **Verified:** `src/lib/components/mod-list/ModList.svelte` uses a virtual list with stable row IDs and grows the visible result window in batches of 20. It resets scroll to the top when query arguments change.
- **Relation to ZomboidSorter:** stable IDs and bounded rendering are useful if performance measurements show a large-library problem. Current local scans are around 60 entries and complete quickly, so the existing Qt lists remain the simpler choice. For equivalent-data refreshes, ZomboidSorter now keeps the current scroll offsets.
- **Do not transfer:** Thunderstore/Hexium source identity, install, profile sync, or game-specific behavior.
- **Source:** [Gale `ModList.svelte`](https://github.com/Kesomannen/gale/blob/dd41fcdc2d6f564a793cbba84c3a196b19653aa1/src/lib/components/mod-list/ModList.svelte), [version and license metadata](https://github.com/Kesomannen/gale/blob/dd41fcdc2d6f564a793cbba84c3a196b19653aa1/src-tauri/Cargo.toml).

## Cross-cutting conclusions

- **Verified:** the four implementations place search/filtering and diagnostics close to their lists, but keep the details or resolution path available beyond a bare status color.
- **Implementation decision:** preserve ZomboidSorter's two-list workflow and staged order; keep warning types scoped to the list they describe; preserve scroll position during equivalent list rebuilds. Do not add a generic model layer or virtualization based only on another app's architecture.
- **Hypothesis:** if real libraries grow substantially, stable-key virtualization could reduce Qt row construction and paint work. No local benchmark currently demonstrates that bottleneck.
- **Unresolved:** this review does not establish Project Zomboid runtime load behavior or compare performance across managers.

## Licensing

The inspected projects identify GPL-3.0 licensing (MO2's `LICENSE` is GPLv3; RimSort and Vortex document GPL-3.0; Gale's project metadata reports GPL-3.0 and its Flatpak metadata specifies GPL-3.0-only). ZomboidSorter is GPL-3.0-or-later. No code, icons, or other assets were copied. Review the exact source and component terms before any future adaptation or redistribution; the repositories' UI ideas are used only as design references here.

## Related ZomboidSorter code and checks

- `src/zomboid_mod_manager/ui/window_library.py` rebuilds active and Discover lists and retains row selection and scroll offsets.
- `src/zomboid_mod_manager/ui/window_workspace_layout.py` places the Discover bulk actions explicitly in the keyboard path before Active Order; a 980×680 fixture test follows that path into Details.
- `src/zomboid_mod_manager/ui/window_diagnostics.py` separates library warnings from active-order issues, shows the declaring mod for dependency findings, and routes each **Review** action to its first finding in the shared diagnostics view. Discover's library action appears only while warnings or errors exist. `window_discovery.py` retains the previous finding text after a failed refresh so the review target remains visible.
- `tests/test_ui.py` covers warning scope, dependency source/path context, scroll preservation after rebuilding an unchanged list, plain singular/plural issue counts, pre-scan status, keyboard activation and navigation for both **Review** actions, and minimum-size traversal through Discover, Active Order, and Details.
- `src/zomboid_mod_manager/ui/window_lifecycle.py` keeps saved and initial window rectangles inside the selected display when the available area meets the app minimum. `tests/test_ui.py` covers oversized/off-screen, partial, and already-valid rectangles; a live source run showed the workspace and footer at 200% Qt scaling.
- Current performance evidence: [Project Zomboid research](PROJECT_ZOMBOID.md) records real-library scan timing; no virtualization threshold has been established.

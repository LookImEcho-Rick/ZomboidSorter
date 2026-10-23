# RimSort research

Inspected RimSort's current public source and documentation on 2026-10-22, focusing on its package layout, metadata/list services, sorting controller, persistence path, and UI guidance. Recheck upstream before relying on implementation details in later milestones.

## What RimSort provides

- A native PySide6 application structured into `views`, `controllers`, `models`, `services`, `sort`, and utilities. The main UI supports active/inactive mod lists, search/filtering, selection details, warnings, settings, and game instances.
- Discovery and metadata are RimWorld-specific: installed game `Data`, local mods, Workshop mods, `About.xml`, Package IDs, game versions, and optional external metadata databases.
- Sorting compiles dependency/rule graphs for active mods, partitions them into four RimWorld-specific tiers, then sorts each tier. Topological sorting groups dependency levels and alphabetizes ties; cycles fail the operation. Optional community and user rules add load-before/after, incompatibility, top/bottom rules.
- Import/export parses RimWorld `ModsConfig.xml` or RimSort JSON; writes a generated `ModsConfig.xml`. These formats and the Core/DLC checks do not apply to Project Zomboid.
- Steam Workshop integration, metadata caching, profiles/history, settings persistence, launch integration, logging, and support diagnostics are implemented in game-specific modules.

## Useful patterns and limits

Adapt the two-list workflow, details panel, staged changes, diagnostics, settings, profile concepts, service/controller separation, and explainable graph sorting. Keep discovery and UI concerns separate. RimSort's parser, game path service, metadata schema, profile format, Steam DB, rule database, content tiers, and config writer are not reusable as-is.

For the Phase A window pass, the relevant current source is `app/views/main_content_panel.py` (`_init_widgets` and `_setup_layout`): it places a `ModInfoPanel` and `ModsPanel` in a noncollapsible horizontal `QSplitter`, uses a narrow handle, and gives the information pane a minimum width. `app/views/mod_info_panel.py` owns preview handling; `app/views/mods_panel.py` owns the mod-list workspace. The screenshots confirm the compact inactive/active columns and a large selected-mod area. The Zomboid UI independently adopts that split and composition without copying code or assets. Preview image discovery is deferred to Phase C.

For Phase B, `app/views/mods_panel.py` connects current-item changes to details, double-clicks to list transfer, uses extended selection and drag/drop, and builds item-specific context actions. The Zomboid implementation follows those interaction patterns with only actions supported by its own data and staged-list backend. Its active list keeps the configured order; inactive sorting is visual.

Do not copy its sorter or infer Project Zomboid ordering from RimWorld. The target game's documented identifiers, directory/version selection, configuration surfaces, and runtime load semantics differ. The external rule databases are also specific to RimWorld.

## Licensing

The repository declares GPL-3.0. This project has not copied RimSort source. Architectural ideas and observed behavior are recorded with attribution. If implementation later adapts source code, distribution must be reviewed for GPLv3 obligations; decide the product license before doing so.

## Sources

- [RimSort repository](https://github.com/RimSort/RimSort) — structure and license.
- [RimSort `pyproject.toml`](https://github.com/RimSort/RimSort/blob/main/pyproject.toml) — Python and PySide6 dependencies.
- [Sort controller](https://github.com/RimSort/RimSort/blob/main/app/controllers/sort_controller.py), [topological sorter](https://github.com/RimSort/RimSort/blob/main/app/sort/topo_sort.py), and [sorting guide](https://rimsort.github.io/RimSort/user-guide/sorting-algorithms) — graph and tier behavior.
- [Mod-list parser](https://github.com/RimSort/RimSort/blob/main/app/services/mod_list_parser.py) and [import/export service](https://github.com/RimSort/RimSort/blob/main/app/services/import_export_service.py) — XML/JSON formats and RimWorld config writes.
- [Basic usage](https://rimsort.github.io/RimSort/user-guide/basic-usage), [databases](https://rimsort.github.io/RimSort/user-guide/databases), and [rule editor](https://rimsort.github.io/RimSort/user-guide/rule-editor) — UI, validation, and optional rule databases.
- [Qt for Python licensing](https://doc.qt.io/qtforpython-6/) — PySide6 license options.

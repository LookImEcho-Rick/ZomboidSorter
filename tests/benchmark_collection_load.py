"""Disposable load benchmark; run with the project Python, outside unittest.

Thirty items, each with 64 distinct 8-KiB media files. Reports median wall time
over three first loads, reloads and switches retaining half the deployed mods.
Setup and cache interning are excluded. This does not benchmark game loading.
"""

from pathlib import Path
from statistics import median
from tempfile import TemporaryDirectory
from time import perf_counter

from zomboid_mod_manager.collection_deployment import load_collection
from zomboid_mod_manager.collection_store import CollectionStore
from zomboid_mod_manager.profiles import ModProfile


def main():
    with TemporaryDirectory(prefix="zomboidsorter-benchmark-") as temporary:
        root = Path(temporary)
        store = CollectionStore(root / "collections")
        references = []
        for index in range(30):
            source = root / "downloads" / str(index)
            entry = source / "mods" / f"Mod{index}"
            media = entry / "media"
            media.mkdir(parents=True)
            (entry / "mod.info").write_text(f"name=Mod{index}\nid=Mod{index}\n")
            for file_index in range(64):
                (media / f"file{file_index}.lua").write_bytes(
                    bytes([(index + file_index) % 256]) * 8192
                )
            references.append(store.intern(source, str(index + 1)))
        full = ModProfile(
            "Full",
            tuple(f"Mod{i}" for i in range(30)),
            tuple(str(i + 1) for i in range(30)),
            None,
            tuple(references),
        )
        half = ModProfile(
            "Half",
            full.mod_ids[:15],
            full.workshop_ids[:15],
            None,
            full.collection_content[:15],
        )
        timings = {"first": [], "reload": [], "half-overlap switch": []}
        for run in range(3):
            local = root / str(run) / "Zomboid" / "mods"
            local.mkdir(parents=True)
            for stage, profile in (
                ("first", full),
                ("reload", full),
                ("half-overlap switch", half),
            ):
                started = perf_counter()
                load_collection(store, profile, local, [local])
                timings[stage].append(perf_counter() - started)
        for stage, values in timings.items():
            print(f"{stage}: median {median(values):.3f}s; runs {values}")


if __name__ == "__main__":
    main()

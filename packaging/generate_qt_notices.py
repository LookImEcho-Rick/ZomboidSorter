"""Build bundle-scoped Qt attribution documents from the pinned source appendices."""

from __future__ import annotations

import argparse
import gzip
import html
import re
import shutil
from pathlib import Path

PACKAGING = Path(__file__).resolve().parent
LICENSE_SOURCE = PACKAGING / "licenses"
SECTION_RE = re.compile(r"<section><h2>.*?</section>", re.DOTALL)
ATTRIBUTION_RE = re.compile(
    r'href="https://doc\.qt\.io/qt-6/(qt[\w-]*)-attribution-[^\"]+"'
)


def _read_source(path: Path) -> str:
    if path.suffix == ".gz":
        with gzip.open(path, "rt", encoding="utf-8") as source:
            return source.read()
    return path.read_text(encoding="utf-8")


def _section_prefix(section: str) -> str:
    match = ATTRIBUTION_RE.search(section)
    if match is None:
        raise ValueError("Qt attribution section is missing its upstream page link")
    return match.group(1)


def _module_doc_prefix(dll_name: str) -> str | None:
    """Map a bundled Qt DLL to the Qt documentation module name."""
    stem = Path(dll_name).stem
    if not stem.startswith("Qt6"):
        return None
    module = stem[3:].lower()

    if module.startswith("3d"):
        return "qt3d"
    if module.startswith("core5compat"):
        return "qtcore5compat"
    if module.startswith("quick3dphysics"):
        return "qtquick3dphysics"
    if module.startswith("quick3d"):
        return "qtquick3d"
    if module.startswith("quickcontrols2"):
        return "qtquickcontrols"
    if module.startswith("quick"):
        return "qtquick"
    if module.startswith("qml"):
        return "qtqml"
    if module.startswith("webengine"):
        # Qt WebEngine has a separate, much larger Chromium attribution appendix.
        return None
    return f"qt{module}"


def _read_sections(
    path: Path, expected: int, *, validate_links: bool = True
) -> list[str]:
    source = _read_source(path)
    sections = SECTION_RE.findall(source)
    if len(sections) != expected:
        raise ValueError(
            f"Expected {expected} attribution sections in {path.name}, found {len(sections)}"
        )
    if validate_links:
        for section in sections:
            _section_prefix(section)
    return sections


def _write_filtered_qt_appendix(
    destination: Path,
    sections: list[str],
    needed_prefixes: set[str],
    has_software_gl: bool,
) -> tuple[int, set[str]]:
    selected: list[str] = []
    selected_prefixes: set[str] = set()
    for section in sections:
        prefix = _section_prefix(section)
        if prefix in needed_prefixes:
            selected.append(section)
            selected_prefixes.add(prefix)
        elif (
            prefix == "qt" and has_software_gl and "qt-attribution-llvmpipe" in section
        ):
            # Qt's software OpenGL renderer is shipped as opengl32sw.dll.
            selected.append(section)
            selected_prefixes.add(prefix)

    if not selected:
        raise ValueError("No Qt attribution pages matched the Qt runtime bundle")

    visible_modules = ", ".join(sorted(selected_prefixes))
    header = f"""<!doctype html><html lang="en"><meta charset="utf-8"><title>Qt 6.12.0 third-party notices</title><style>body{{font:15px/1.5 system-ui,sans-serif;max-width:1000px;margin:2rem auto;padding:0 1rem;color:#222}}pre{{white-space:pre-wrap;border:1px solid #ccc;padding:1rem}}section{{border-top:1px solid #aaa;padding:1rem 0}}h1,h2{{line-height:1.2}}small{{color:#555}}</style><body>
<h1>Qt 6.12.0 third-party notices and license texts</h1>
<p>This offline appendix contains {len(selected)} component attribution pages selected from the complete Qt 6.12.0 inventory for the Qt modules recorded in <code>BUILD_COMPONENTS.txt</code>. Included documentation module groups: {html.escape(visible_modules)}.</p>
<p>Qt source inventory: <a href="https://doc.qt.io/qt-6/licenses-used-in-qt.html">Third-Party Code Used in Qt 6.12</a>. Each retained detail page preserves its component-specific descriptions, copyright notices, license statements, and upstream source links.</p>
<p>Qt documentation text is copyrighted by The Qt Company and respective contributors and is provided under GNU Free Documentation License 1.3. The full FDL 1.3 text is included alongside this appendix.</p>
<p>Retrieved 2026-10-22. The appendix is filtered at build time against the Qt DLLs in this installer.</p>
"""
    destination.write_text(
        header + "\n".join(selected) + "\n</body></html>\n", encoding="utf-8"
    )
    return len(selected), selected_prefixes


def build_notices(
    bundle: Path, license_output: Path
) -> tuple[list[str], set[str], int, int]:
    qt_directory = bundle / "_internal" / "PySide6"
    if not qt_directory.is_dir():
        raise FileNotFoundError(
            f"Bundled PySide6 directory was not found: {qt_directory}"
        )

    qt_dlls = sorted(
        {
            path.name
            for path in qt_directory.rglob("Qt*.dll")
            if path.is_file() and path.name.startswith("Qt6")
        }
    )
    if not any(name == "Qt6Core.dll" for name in qt_dlls):
        raise ValueError("The bundle does not contain Qt6Core.dll")
    if not any(name == "Qt6WebEngineCore.dll" for name in qt_dlls):
        raise ValueError("The bundle does not contain Qt6WebEngineCore.dll")
    if (qt_directory / "qml").exists():
        raise ValueError(
            "The unused QML asset/plugin tree was collected into the bundle"
        )
    for plugin_group in ("generic", "platforminputcontexts", "qmltooling"):
        if any((qt_directory / "plugins" / plugin_group).glob("*.dll")):
            raise ValueError(
                f"The unused Qt plugin group was collected: {plugin_group}"
            )

    needed_prefixes = {
        prefix for name in qt_dlls if (prefix := _module_doc_prefix(name)) is not None
    }
    if any((qt_directory / "plugins" / "imageformats").glob("*.dll")):
        needed_prefixes.add("qtimageformats")

    qt_source = LICENSE_SOURCE / "QT-6.12.0-THIRD-PARTY.html.gz"
    webengine_source = LICENSE_SOURCE / "QT-WEBENGINE-6.140.0-THIRD-PARTY.html.gz"
    qt_sections = _read_sections(qt_source, expected=138)
    webengine_sections = _read_sections(
        webengine_source, expected=125, validate_links=False
    )

    licenses = license_output
    licenses.mkdir(parents=True, exist_ok=True)
    qt_count, documentation_groups = _write_filtered_qt_appendix(
        licenses / "QT-6.12.0-THIRD-PARTY.html",
        qt_sections,
        needed_prefixes,
        has_software_gl=(qt_directory / "opengl32sw.dll").is_file(),
    )

    # QtWebEngineCore includes Chromium and its dependencies, so retain Qt's complete
    # WebEngine appendix whenever its runtime is redistributed.
    # The WebEngine source is gzip-compressed in this repository to keep generated
    # upstream legal text out of source-code viewers; restore the readable appendix.
    webengine_output = licenses / "QT-WEBENGINE-6.140.0-THIRD-PARTY.html"
    with gzip.open(webengine_source, "rt", encoding="utf-8") as source:
        webengine_output.write_text(source.read(), encoding="utf-8")

    for name in ("FDL-1.3.txt", "LGPL-2.1.txt", "LGPL-3.0.txt", "OPENSSL-LICENSE.txt"):
        shutil.copyfile(LICENSE_SOURCE / name, licenses / name)

    manifest = licenses / "BUILD_COMPONENTS.txt"
    manifest_lines = manifest.read_text(encoding="utf-8").splitlines()
    manifest_lines = [
        line for line in manifest_lines if not line.startswith("Qt runtime DLLs:")
    ]
    manifest_lines = [
        line for line in manifest_lines if not line.startswith("Qt attribution groups:")
    ]
    manifest_lines.extend(
        (
            f"Qt runtime DLLs ({len(qt_dlls)}): " + ", ".join(qt_dlls),
            "Qt attribution documentation groups: "
            + ", ".join(sorted(documentation_groups)),
            f"Qt 6.12.0 attribution pages included: {qt_count}",
            f"Qt WebEngine 6.140.0 attribution pages included: {len(webengine_sections)} (complete appendix)",
        )
    )
    manifest.write_text("\n".join(manifest_lines) + "\n", encoding="utf-8")
    return qt_dlls, documentation_groups, qt_count, len(webengine_sections)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("bundle", type=Path, help="PyInstaller onedir output directory")
    parser.add_argument(
        "license_output", type=Path, help="Staged installer license directory"
    )
    args = parser.parse_args()
    qt_dlls, groups, qt_count, webengine_count = build_notices(
        args.bundle.resolve(), args.license_output.resolve()
    )
    print(f"Qt runtime DLLs inventoried: {len(qt_dlls)}")
    print(f"Qt attribution documentation groups: {', '.join(sorted(groups))}")
    print(f"Qt attribution pages: {qt_count}; WebEngine pages: {webengine_count}")


if __name__ == "__main__":
    main()

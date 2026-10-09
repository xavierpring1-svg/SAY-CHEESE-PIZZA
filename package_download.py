"""Trim verified Qt runtime files and write a reproducible portable download."""
from __future__ import annotations

import hashlib
import os
import re
import subprocess
import tempfile
import zipfile
from pathlib import Path


QT_MODULES = ("QtCore", "QtGui", "QtWidgets", "QtNetwork")
QT_PLUGINS = (
    "platforms/qwindows.dll", "platforms/qoffscreen.dll",
    "styles/qmodernwindowsstyle.dll", "iconengines/qsvgicon.dll",
    "imageformats/qico.dll", "imageformats/qjpeg.dll", "imageformats/qgif.dll",
    "imageformats/qsvg.dll", "imageformats/qwebp.dll",
    "networkinformation/qnetworklistmanager.dll",
    "tls/qschannelbackend.dll", "tls/qcertonlybackend.dll",
)


def _dll_dependencies(path, objdump):
    inspection = subprocess.run([str(objdump), "-p", str(path)], check=True,
                                capture_output=True, text=True)
    return re.findall(r"DLL Name:\s*(\S+)", inspection.stdout)


def _is_license(path):
    legal = ("license", "licence", "copying", "copyright", "notice")
    return any(any(term in part.lower() for term in legal) for part in path.parts)


def trim_python_runtime(runtime, objdump, omit_installers=True):
    """Omit development-only Python files while keeping app libraries and licenses.

    All app dependencies are already bundled, and models are checksum-verified
    archive downloads. The portable app therefore does not need pip/ensurepip.
    Development from source uses a separate, full Python installation.
    """
    runtime = Path(runtime)
    roots = [runtime / name for name in (
        "include", "libs", "Lib/test", "Lib/idlelib", "Lib/tkinter", "tcl",
    )]
    if omit_installers:
        roots += [runtime / "Lib/ensurepip", runtime / "Lib/site-packages/pip"]
        roots += [runtime / "Scripts" / name for name in ("pip.exe", "pip3.exe", "pip3.12.exe")]
    candidates = set()
    for root in roots:
        if root.is_dir():
            candidates.update(path for path in root.rglob("*") if path.is_file())
        elif root.is_file():
            candidates.add(root)
    tk_binaries = {
        path for path in runtime.rglob("*")
        if path.is_file() and re.fullmatch(r"(?:_tkinter.*\.pyd|(?:tcl|tk)\d.*\.dll)", path.name, re.I)
    }
    candidates.update(tk_binaries)
    protected = set()
    # Protect DLLs still imported by any retained extension/launcher. If a Tk
    # library is required, keep all Tk support data as well as its binary closure.
    candidate_dlls = {path.name.casefold(): path for path in tk_binaries}
    if candidate_dlls:
        pending = [path for path in runtime.rglob("*")
                   if path.is_file() and path.suffix.lower() in {".dll", ".pyd", ".exe"}
                   and path not in candidates]
        while pending:
            path = pending.pop()
            for dependency in _dll_dependencies(path, objdump):
                resolved = candidate_dlls.get(dependency.casefold())
                if resolved is not None and resolved not in protected:
                    protected.add(resolved)
                    pending.append(resolved)
        if protected:
            tk_roots = [runtime / name for name in ("Lib/tkinter", "tcl")]
            protected.update(path for path in candidates
                             if path in tk_binaries or any(path.is_relative_to(root) for root in tk_roots))
    retained_licenses = [path for path in candidates if _is_license(path.relative_to(runtime))]
    protected.update(retained_licenses)
    removed = []
    removed_bytes = 0
    for path in sorted(candidates - protected):
        removed.append(path.relative_to(runtime).as_posix())
        removed_bytes += path.stat().st_size
        path.unlink()
    for root in roots:
        if root.is_dir():
            for directory in sorted(root.rglob("*"), reverse=True):
                if directory.is_dir() and not any(directory.iterdir()):
                    directory.rmdir()
            if not any(root.iterdir()):
                root.rmdir()
    return {
        "reason": "Portable runtime omits development headers, import libraries, Tk tools, and installers; app dependencies are bundled",
        "installers_omitted": omit_installers,
        "removed_files": removed, "removed_bytes": removed_bytes,
        "retained_license_files": sorted(path.relative_to(runtime).as_posix() for path in retained_licenses),
        "protected_imported_files": sorted(path.relative_to(runtime).as_posix() for path in protected if path not in retained_licenses),
    }


def trim_qt(site, objdump):
    """Keep app bindings, dynamic Qt plugins and their imported DLL closure.

    Only already verified wheel files are considered. The software OpenGL
    decoder and Windows TLS backend are explicitly retained because Qt loads
    them dynamically and they do not appear in the PE import tables.
    """
    qt = Path(site) / "PySide6"
    required = [qt / (name + ".pyd") for name in QT_MODULES]
    required.extend(qt / "plugins" / name for name in QT_PLUGINS)
    required.append(qt / "opengl32sw.dll")
    missing = [str(path.relative_to(qt)) for path in required if not path.is_file()]
    if missing:
        raise RuntimeError("Required Windows Qt files are missing: " + ", ".join(missing))
    dlls = {path.name.casefold(): path for path in qt.rglob("*.dll")}
    keep = set(required)
    pending = required.copy()
    imported = {}
    while pending:
        path = pending.pop()
        dependencies = _dll_dependencies(path, objdump)
        imported[str(path.relative_to(qt))] = sorted(dependencies, key=str.casefold)
        for dependency in dependencies:
            resolved = dlls.get(dependency.casefold())
            if resolved is not None and resolved not in keep:
                keep.add(resolved)
                pending.append(resolved)
            elif resolved is None and dependency.casefold().startswith(("qt6", "pyside6")):
                raise RuntimeError(f"Missing Qt dependency {dependency} required by {path.name}")
    # Python support modules are small and some are imported by the bindings.
    keep.update(path for path in qt.rglob("*.py") if "__pycache__" not in path.parts)
    keep.update(path for path in qt.iterdir() if path.name in {
        "PySide6_Essentials.json", "py.typed",
    })
    removed = []
    for path in sorted(qt.rglob("*"), reverse=True):
        if path.is_file() and path not in keep:
            removed.append(str(path.relative_to(qt)))
            path.unlink()
        elif path.is_dir() and not any(path.iterdir()):
            path.rmdir()
    return {
        "bindings": list(QT_MODULES), "plugins": list(QT_PLUGINS),
        "kept_files": sorted(str(path.relative_to(qt)) for path in keep),
        "imported_dlls": imported, "removed_files": sorted(removed),
    }


def file_sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def create_download(release, output_directory, maximum_bytes=100 * 1024 * 1024):
    """Publish ZIP and checksum only after integrity and size checks pass."""
    release, output_directory = Path(release), Path(output_directory)
    output_directory.mkdir(parents=True, exist_ok=True)
    output = output_directory / "JARVIS-Windows.zip"
    temporary = tempfile.NamedTemporaryFile(prefix=".jarvis-", suffix=".zip", dir=output_directory, delete=False)
    temporary.close()
    archive_path = Path(temporary.name)
    try:
        with zipfile.ZipFile(archive_path, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
            for file in sorted(release.rglob("*")):
                if file.is_file():
                    relative = (Path("JARVIS-Windows") / file.relative_to(release)).as_posix()
                    # Stable metadata makes unchanged inputs produce the same ZIP.
                    info = zipfile.ZipInfo(relative, date_time=(2024, 1, 1, 0, 0, 0))
                    info.compress_type = zipfile.ZIP_DEFLATED
                    info.external_attr = 0o100644 << 16
                    archive.writestr(info, file.read_bytes(), compresslevel=9)
        if archive_path.stat().st_size >= maximum_bytes:
            raise RuntimeError("The portable ZIP exceeds the GitHub 100 MiB file limit.")
        with zipfile.ZipFile(archive_path) as archive:
            damaged = archive.testzip()
            if damaged:
                raise RuntimeError(f"ZIP integrity check failed: {damaged}")
        checksum = file_sha256(archive_path)
        checksum_path = output_directory / "JARVIS-Windows.sha256"
        checksum_temporary = checksum_path.with_name("." + checksum_path.name + ".tmp")
        checksum_temporary.write_text(checksum + "  JARVIS-Windows.zip\n", encoding="ascii")
        os.replace(archive_path, output)
        os.replace(checksum_temporary, checksum_path)
        return output, checksum
    finally:
        archive_path.unlink(missing_ok=True)

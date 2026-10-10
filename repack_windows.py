"""Update app sources while reusing a checksum-verified portable Windows runtime.

Use this for Python/UI/asset changes with unchanged dependency declarations and
native launcher source. Full dependency or launcher changes require build_windows.py.
The resulting manifest records reuse; this command does not freshly verify wheels.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import stat
import tempfile
import zipfile
from pathlib import Path, PurePosixPath

from build_windows import ROOT, SOURCE_FOLDERS, copy_app_sources, source_file_hashes
from package_download import create_download, file_sha256


def verify_base(archive_path, checksum_path):
    """Verify the complete base ZIP and the manifest's complete source map."""
    checksum_line = Path(checksum_path).read_text(encoding="utf-8").strip().split()
    if len(checksum_line) != 2 or checksum_line[1].lstrip("*") != Path(archive_path).name:
        raise ValueError("Base checksum must identify the selected ZIP filename")
    expected = checksum_line[0].lower()
    if len(expected) != 64 or any(letter not in "0123456789abcdef" for letter in expected):
        raise ValueError("Invalid base SHA256 checksum")
    actual = file_sha256(archive_path)
    if actual != expected:
        raise ValueError("Base Windows ZIP failed SHA256 verification")
    with zipfile.ZipFile(archive_path) as archive:
        seen = set()
        for info in archive.infolist():
            name = PurePosixPath(info.filename)
            if (name.is_absolute() or ".." in name.parts or "\\" in info.filename
                    or ":" in info.filename or not name.parts
                    or name.parts[0] != "JARVIS-Windows"):
                raise ValueError(f"Unsafe base archive path: {info.filename}")
            if info.filename in seen:
                raise ValueError(f"Duplicate base archive path: {info.filename}")
            seen.add(info.filename)
            if stat.S_ISLNK(info.external_attr >> 16):
                raise ValueError(f"Base archive contains a symlink: {info.filename}")
        damaged = archive.testzip()
        if damaged:
            raise ValueError(f"Base ZIP failed CRC integrity: {damaged}")
        manifest_bytes = archive.read("JARVIS-Windows/package-manifest.json")
        manifest = json.loads(manifest_bytes)
        recorded = manifest.get("source_files_sha256", {})
        if not recorded:
            raise ValueError("Base package has no source hash manifest")
        source_names = {
            info.filename.removeprefix("JARVIS-Windows/")
            for info in archive.infolist() if not info.is_dir()
            and not info.filename.startswith("JARVIS-Windows/runtime/")
            and info.filename != "JARVIS-Windows/package-manifest.json"
        }
        if source_names != set(recorded):
            raise ValueError("Base source manifest does not cover exactly all source files")
        for relative, source_hash in recorded.items():
            data = archive.read("JARVIS-Windows/" + relative)
            if hashlib.sha256(data).hexdigest() != source_hash:
                raise ValueError(f"Base source hash mismatch: {relative}")
        for relative in ("requirements.txt", "requirements-dev.txt", "launcher.c"):
            if (ROOT / relative).read_bytes() != archive.read("JARVIS-Windows/" + relative):
                raise ValueError(f"{relative} changed; use a full build_windows.py build")
    return manifest, actual, hashlib.sha256(manifest_bytes).hexdigest()


def runtime_tree_hash(runtime):
    """Hash sorted POSIX paths plus each file's SHA256 to document runtime reuse."""
    digest = hashlib.sha256()
    files = [path for path in sorted(Path(runtime).rglob("*")) if path.is_file()]
    for file in files:
        relative = file.relative_to(runtime).as_posix()
        digest.update(relative.encode("utf-8") + b"\0")
        digest.update(bytes.fromhex(file_sha256(file)))
    return digest.hexdigest(), len(files)


def repack(base_zip, base_checksum, output_zip):
    base_zip, base_checksum, output_zip = map(Path, (base_zip, base_checksum, output_zip))
    if output_zip.suffix.lower() != ".zip":
        raise ValueError("The output filename must end with .zip")
    checksum_path = output_zip.with_suffix(".sha256")
    protected = {base_zip.resolve(), base_checksum.resolve()}
    if output_zip.resolve() in protected or checksum_path.resolve() in protected:
        raise ValueError("Write the updated ZIP to a separate path to preserve the base")
    manifest, base_hash, manifest_hash = verify_base(base_zip, base_checksum)
    output_zip.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".jarvis-repack-", dir=output_zip.parent) as work:
        work = Path(work)
        with zipfile.ZipFile(base_zip) as archive:
            archive.extractall(work)
        release = work / "JARVIS-Windows"
        reused_runtime_hash, runtime_count = runtime_tree_hash(release / "runtime")
        launcher_hash = file_sha256(release / "JARVIS.exe")
        for folder in SOURCE_FOLDERS:
            shutil.rmtree(release / folder, ignore_errors=True)
        # Remove old optional root source files/scripts so renamed/deleted files
        # cannot remain in an updated package.
        old_sources = manifest["source_files_sha256"]
        for relative in old_sources:
            if "/" not in relative and relative != "JARVIS.exe":
                (release / relative).unlink(missing_ok=True)
        copy_app_sources(release)
        final_runtime_hash, final_count = runtime_tree_hash(release / "runtime")
        if final_runtime_hash != reused_runtime_hash or final_count != runtime_count:
            raise ValueError("Repack unexpectedly changed the bundled runtime")
        if file_sha256(release / "JARVIS.exe") != launcher_hash:
            raise ValueError("Repack unexpectedly changed the native launcher")
        manifest["source_files_sha256"] = source_file_hashes(release)
        manifest["repack"] = {
            "base_archive": base_zip.name,
            "base_archive_sha256": base_hash,
            "base_manifest_sha256": manifest_hash,
            "base_source_files_verified": True,
            "runtime_reused_unchanged": True,
            "runtime_files": runtime_count,
            "runtime_tree_sha256": reused_runtime_hash,
            "runtime_tree_hash_format": "Sorted UTF-8 POSIX relative path, NUL, raw file SHA256; concatenated and SHA256 hashed",
            "launcher_reused_sha256": launcher_hash,
            "dependency_verification": "Original package provenance retained; fresh upstream wheel verification was not performed by repack",
        }
        (release / "package-manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        generated, checksum = create_download(release, work / "output")
        checksum_temporary = work / "output.sha256"
        checksum_temporary.write_text(checksum + "  " + output_zip.name + "\n", encoding="utf-8")
        os.replace(generated, output_zip)
        os.replace(checksum_temporary, checksum_path)
    print(f"Created {output_zip} ({output_zip.stat().st_size / 1024 / 1024:.1f} MiB)")
    print("SHA256:", checksum)
    print("Original bundled runtime/launcher reused unchanged; source hashes refreshed.")
    return output_zip, checksum


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-zip", type=Path, default=ROOT / "downloads/JARVIS-Windows.zip")
    parser.add_argument("--base-checksum", type=Path, default=ROOT / "downloads/JARVIS-Windows.sha256")
    parser.add_argument("--output-zip", type=Path, required=True)
    arguments = parser.parse_args()
    repack(arguments.base_zip, arguments.base_checksum, arguments.output_zip)

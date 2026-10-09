"""Assemble a portable Windows x64 app, verifying upstream package hashes."""
import base64
import concurrent.futures
import gzip
import hashlib
import io
import json
import re
import shutil
import subprocess
import tarfile
import tempfile
import urllib.request
import zipfile
from pathlib import Path

from package_download import create_download, file_sha256, trim_python_runtime, trim_qt

ROOT = Path(__file__).resolve().parent
RELEASE = ROOT / "dist/JARVIS-Windows"


def get_json(url):
    with urllib.request.urlopen(url, timeout=45) as response:
        raw = response.read()
    return json.loads(gzip.decompress(raw) if raw[:2] == b"\x1f\x8b" else raw)


def verify_source_wheel(package, metadata, upstream):
    """Verify installed source files of srt's locally built wheel against its sdist."""
    if metadata["Name"].lower() != "srt":
        raise ValueError("Only srt's source-only distribution may use a local wheel")
    published = next(file for file in upstream["urls"] if file["packagetype"] == "sdist")
    with urllib.request.urlopen(published["url"], timeout=45) as response:
        source_archive = response.read()
    expected = published["digests"]["sha256"]
    if hashlib.sha256(source_archive).hexdigest() != expected:
        raise ValueError("srt source archive failed checksum verification")
    with tarfile.open(fileobj=io.BytesIO(source_archive), mode="r:gz") as source:
        entries = {}
        for member in source.getmembers():
            if member.isfile() and "/" in member.name:
                entries[member.name.split("/", 1)[1]] = source.extractfile(member).read()
    for name in package.namelist():
        if name.endswith("/") or ".dist-info/" in name or ".data/scripts/" in name:
            continue
        relative = name
        if ".data/" in relative:
            tail = relative.split(".data/", 1)[1]
            if not tail.startswith(("purelib/", "platlib/")):
                continue
            relative = tail.split("/", 1)[1]
        if relative not in entries or package.read(name) != entries[relative]:
            raise ValueError(f"Local srt wheel differs from its verified source: {name}")
    return {"source": published["url"], "source_sha256": expected,
            "verification": "Installed Python files match the verified official sdist"}


def verify_wheel(path):
    with zipfile.ZipFile(path) as package:
        metadata_name = next(n for n in package.namelist() if n.endswith(".dist-info/METADATA"))
        from email.parser import BytesParser
        metadata = BytesParser().parsebytes(package.read(metadata_name))
    name, version = metadata["Name"], metadata["Version"]
    actual = file_sha256(path)
    upstream = get_json(f"https://pypi.org/pypi/{name}/{version}/json")
    published = next((file for file in upstream["urls"] if file["filename"] == path.name), None)
    if published:
        if actual != published["digests"]["sha256"]:
            raise ValueError(f"Checksum mismatch for {path.name}")
        source = published["url"]
    elif name.lower() == "srt":
        with zipfile.ZipFile(path) as package:
            source_details = verify_source_wheel(package, metadata, upstream)
        return {"name": name, "version": version, "filename": path.name,
                "sha256": actual, **source_details}
    else:
        raise ValueError(f"No published artifact found for {path.name}")
    return {"name": name, "version": version, "filename": path.name,
            "sha256": actual, "source": source}


def verify_requirements(records):
    versions = {}
    for record in records:
        name = re.sub(r"[-_.]+", "-", record["name"]).lower()
        if name in versions:
            raise ValueError(f"Multiple wheels for {name}; use a fresh --wheel-dir")
        versions[name] = record["version"]
    for line in (ROOT / "requirements.txt").read_text(encoding="utf-8").splitlines():
        match = re.match(r"([\w.-]+)(?:\[[^]]+\])?==([^\s;]+)", line.strip())
        if match:
            name, expected = match.groups()
            name = re.sub(r"[-_.]+", "-", name).lower()
            if versions.get(name) != expected:
                raise ValueError(f"Missing Windows wheel for {name}=={expected}")


def build(wheel_directory=None, output_directory=None):
    wheel_directory = Path(wheel_directory or ROOT / "wheels")
    output_directory = Path(output_directory or ROOT / "downloads")
    (ROOT / "dist").mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".jarvis-build-", dir=ROOT / "dist") as staging:
        release = Path(staging) / "JARVIS-Windows"
        release.mkdir()
        assemble(release, wheel_directory)
        output, checksum = create_download(release, output_directory)
        if RELEASE.exists():
            shutil.rmtree(RELEASE)
        shutil.move(str(release), RELEASE)
    print(f"Created {output} ({output.stat().st_size / 1024 / 1024:.1f} MiB)")
    print("SHA256:", checksum)


def assemble(release, wheel_directory):
    cache = ROOT / ".build-cache"
    cache.mkdir(exist_ok=True)
    registration = get_json("https://api.nuget.org/v3/registration5-gz-semver2/python/3.12.10.json")
    catalog = get_json(registration["catalogEntry"])
    runtime_archive = cache / "python.3.12.10.nupkg"
    if not runtime_archive.exists():
        with urllib.request.urlopen(registration["packageContent"], timeout=60) as response:
            runtime_archive.write_bytes(response.read())
    expected = catalog["packageHash"]
    actual = base64.b64encode(hashlib.sha512(runtime_archive.read_bytes()).digest()).decode()
    if catalog["packageHashAlgorithm"].upper() != "SHA512" or actual != expected:
        raise ValueError("Official Python runtime failed checksum verification")
    runtime = release / "runtime"
    runtime.mkdir(exist_ok=True)
    with zipfile.ZipFile(runtime_archive) as package:
        for name in package.namelist():
            if name.startswith("tools/") and not name.endswith("/"):
                target = runtime / name[len("tools/"):]
                if not target.resolve().is_relative_to(runtime.resolve()):
                    raise ValueError("Unsafe runtime archive path")
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(package.read(name))
    wheels = sorted(wheel_directory.glob("*.whl"))
    if not wheels:
        raise RuntimeError("Windows dependency wheels are missing")
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        records = list(pool.map(verify_wheel, wheels))
    verify_requirements(records)
    site = runtime / "Lib/site-packages"
    site.mkdir(parents=True, exist_ok=True)
    for wheel in wheels:
        with zipfile.ZipFile(wheel) as package:
            for info in package.infolist():
                name = info.filename
                if name.endswith("/"):
                    continue
                if ".data/" in name:
                    tail = name.split(".data/", 1)[1]
                    if tail.startswith(("purelib/", "platlib/")):
                        name = tail.split("/", 1)[1]
                    else:
                        continue
                target = site / name
                if not target.resolve().is_relative_to(site.resolve()):
                    raise ValueError("Unsafe wheel path")
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(package.read(info))
    compiler = ROOT / ".toolchain/usr/bin/x86_64-w64-mingw32-gcc-posix"
    objdump = compiler.with_name("x86_64-w64-mingw32-objdump")
    if not compiler.is_file() or not objdump.is_file():
        raise RuntimeError("Windows launcher compiler/PE inspection tool unavailable")
    qt_trim = trim_qt(site, objdump)
    python_trim = trim_python_runtime(runtime, objdump)
    for folder in ["jarvis", "tests", "docs", "third_party"]:
        if (ROOT / folder).is_dir():
            shutil.copytree(ROOT / folder, release / folder,
                            ignore=shutil.ignore_patterns("__pycache__", ".pytest_cache"))
    source_files = [ROOT / name for name in [
        "main.py", "requirements.txt", "requirements-dev.txt", "README.md", "VALIDATION.md",
        "launcher.c", "build_windows.py", "package_download.py", "prepare_brain_runtime.py", "jarvis.ico",
    ]]
    source_files += sorted(ROOT.glob("*.cmd")) + sorted(ROOT.glob("*.ps1"))
    for file in source_files:
        shutil.copy2(file, release / file.name)
    subprocess.run([str(compiler), "-municode", "-mwindows", "-Os", "-static", "-s",
                    "-Wl,--no-insert-timestamp", str(ROOT / "launcher.c"),
                    "-o", str(release / "JARVIS.exe"), "-lshell32"], check=True)
    source_hashes = {
        file.relative_to(release).as_posix(): file_sha256(file)
        for file in sorted(release.rglob("*"))
        if file.is_file() and "runtime" not in file.relative_to(release).parts
    }
    (release / "package-manifest.json").write_text(json.dumps({
        "python": {"version": "3.12.10", "source": registration["packageContent"],
                   "sha512": expected, "checksum_source": registration["catalogEntry"]},
        "packages": records, "qt_trim": qt_trim, "python_trim": python_trim,
        "source_files_sha256": source_hashes,
    }, indent=2))


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wheel-dir", type=Path, default=ROOT / "wheels")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "downloads")
    arguments = parser.parse_args()
    build(arguments.wheel_dir, arguments.output_dir)

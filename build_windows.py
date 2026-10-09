"""Assemble a portable Windows x64 app, verifying upstream package hashes."""
import base64
import concurrent.futures
import gzip
import hashlib
import json
import shutil
import subprocess
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
RELEASE = ROOT / "dist/JARVIS-Windows"


def get_json(url):
    with urllib.request.urlopen(url, timeout=45) as response:
        raw = response.read()
    return json.loads(gzip.decompress(raw) if raw[:2] == b"\x1f\x8b" else raw)


def verify_wheel(path):
    with zipfile.ZipFile(path) as package:
        metadata_name = next(n for n in package.namelist() if n.endswith(".dist-info/METADATA"))
        from email.parser import BytesParser
        metadata = BytesParser().parsebytes(package.read(metadata_name))
    name, version = metadata["Name"], metadata["Version"]
    actual = hashlib.sha256(path.read_bytes()).hexdigest()
    upstream = get_json(f"https://pypi.org/pypi/{name}/{version}/json")
    published = next((file for file in upstream["urls"] if file["filename"] == path.name), None)
    if published:
        if actual != published["digests"]["sha256"]:
            raise ValueError(f"Checksum mismatch for {path.name}")
        source = published["url"]
    elif name.lower() == "srt":
        # srt publishes only an sdist; this universal wheel was built using pip.
        source = "Locally built wheel from the official PyPI srt 3.5.3 sdist"
    else:
        raise ValueError(f"No published artifact found for {path.name}")
    return {"name": name, "version": version, "filename": path.name,
            "sha256": actual, "source": source}


def build():
    RELEASE.mkdir(parents=True, exist_ok=True)
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
    runtime = RELEASE / "runtime"
    runtime.mkdir(exist_ok=True)
    with zipfile.ZipFile(runtime_archive) as package:
        for name in package.namelist():
            if name.startswith("tools/") and not name.endswith("/"):
                target = runtime / name[len("tools/"):]
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(package.read(name))
    wheels = sorted((ROOT / "wheels").glob("*.whl"))
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        records = list(pool.map(verify_wheel, wheels))
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
    shutil.copytree(ROOT / "jarvis", RELEASE / "jarvis", dirs_exist_ok=True,
                    ignore=shutil.ignore_patterns("__pycache__"))
    shutil.copytree(ROOT / "tests", RELEASE / "tests", dirs_exist_ok=True,
                    ignore=shutil.ignore_patterns("__pycache__"))
    for name in ["main.py", "requirements.txt", "README.md", "VALIDATION.md", "launcher.c", "build_windows.py", "Start JARVIS.cmd", "Debug JARVIS.cmd",
                 "Create Desktop Shortcut.cmd", "Create Desktop Shortcut.ps1", "Install Local AI.cmd", "jarvis.ico"]:
        shutil.copy2(ROOT / name, RELEASE / name)
    compiler = ROOT / ".toolchain/usr/bin/x86_64-w64-mingw32-gcc-posix"
    if compiler.exists():
        subprocess.run([str(compiler), "-municode", "-mwindows", "-Os", "-static", "-s",
                        str(ROOT / "launcher.c"), "-o", str(RELEASE / "JARVIS.exe"), "-lshell32"], check=True)
    else:
        raise RuntimeError("Windows launcher compiler unavailable")
    (RELEASE / "package-manifest.json").write_text(json.dumps({
        "python": {"version": "3.12.10", "source": registration["packageContent"],
                   "sha512": expected, "checksum_source": registration["catalogEntry"]},
        "packages": records,
    }, indent=2))
    output = ROOT / "dist/JARVIS-Windows.zip"
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for file in sorted(RELEASE.rglob("*")):
            if file.is_file():
                archive.write(file, Path("JARVIS-Windows") / file.relative_to(RELEASE))
    checksum = hashlib.sha256(output.read_bytes()).hexdigest()
    (ROOT / "dist/JARVIS-Windows.sha256").write_text(checksum + "  JARVIS-Windows.zip\n")
    print(f"Created {output} ({output.stat().st_size / 1024 / 1024:.1f} MB)")
    print("SHA256:", checksum)


if __name__ == "__main__":
    build()

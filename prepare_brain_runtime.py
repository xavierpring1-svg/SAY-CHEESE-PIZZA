"""Reproduce the optional, verified Windows local-conversation runtime.

The desktop app performs this same setup automatically on first use. This
utility is for packagers and provenance inspection; the model is deliberately
not included in the application ZIP.
"""
import argparse
import json
from pathlib import Path
import urllib.request

from jarvis.brain import (RUNTIME_DIGEST_SOURCE, RUNTIME_FILENAME, RUNTIME_SHA256,
                          RUNTIME_SIZE, install_runtime, runtime_valid)


def check_upstream_metadata():
    request = urllib.request.Request(RUNTIME_DIGEST_SOURCE,
                                     headers={"User-Agent": "JarvisDesktop-packager"})
    with urllib.request.urlopen(request, timeout=30) as response:
        release = json.load(response)
    assets = [item for item in release.get("assets", [])
              if item.get("name") == RUNTIME_FILENAME]
    if len(assets) != 1:
        raise RuntimeError("The pinned official runtime asset is unavailable.")
    asset = assets[0]
    if asset.get("size") != RUNTIME_SIZE or asset.get("digest") != "sha256:" + RUNTIME_SHA256:
        raise RuntimeError("The official runtime metadata differs from the pinned checksum.")
    return {"metadata_url": RUNTIME_DIGEST_SOURCE, "asset": RUNTIME_FILENAME,
            "size": RUNTIME_SIZE, "sha256": RUNTIME_SHA256}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--app-runtime", type=Path, required=True,
                        help="Already-verified portable Python/Qt runtime directory")
    parser.add_argument("--archive", type=Path, help="Reuse a checksum-verified cached official ZIP")
    parser.add_argument("--check-upstream-metadata", action="store_true")
    args = parser.parse_args()
    if args.check_upstream_metadata:
        print(json.dumps(check_upstream_metadata(), indent=2))
    result = install_runtime(args.output, app_runtime=args.app_runtime,
                             archive=args.archive, status=print)
    if not runtime_valid(result):
        raise RuntimeError("The prepared runtime could not be verified.")
    print(f"Verified runtime prepared at {result}")

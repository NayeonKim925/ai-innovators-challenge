#!/usr/bin/env python3
"""Download and safely extract the pinned public causRCA dataset and source.

The manifest is versioned in Git; all downloaded artifacts are deliberately ignored.
Run once before `scripts/prepare_causrca.py`. Use `--offline` to verify existing
artifacts without network access.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import stat
import urllib.request
import zipfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = ROOT / "data" / "manifests" / "causrca.json"
MAX_EXTRACTED_BYTES = 512 * 1024 * 1024


def load_manifest(path: Path = MANIFEST_PATH) -> dict[str, Any]:
    manifest = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(manifest, dict) or not isinstance(manifest.get("dataset"), dict):
        raise ValueError(f"Invalid causRCA manifest: {path}")
    return manifest


def digest(path: Path, algorithm: str) -> str:
    hasher = hashlib.new(algorithm)
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def download(url: str, target: Path) -> None:
    if target.exists():
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(target.suffix + ".partial")
    request = urllib.request.Request(
        url, headers={"User-Agent": "manufacturing-investigation-mvp/0.1"}
    )
    with urllib.request.urlopen(request, timeout=90) as response, temporary.open("wb") as output:
        while chunk := response.read(1024 * 1024):
            output.write(chunk)
    temporary.replace(target)


def safe_extract(archive: Path, destination: Path, strip_prefix: str | None = None) -> None:
    """Extract without path traversal, symlinks, or silent overwrite of different files."""
    destination = destination.resolve()
    with zipfile.ZipFile(archive) as bundle:
        entries = [entry for entry in bundle.infolist() if not entry.is_dir()]
        if sum(entry.file_size for entry in entries) > MAX_EXTRACTED_BYTES:
            raise ValueError(f"Archive exceeds extraction limit: {archive}")
        for entry in entries:
            if stat.S_ISLNK(entry.external_attr >> 16):
                raise ValueError(f"Refusing symlink in archive: {entry.filename}")
            name = entry.filename
            if strip_prefix:
                if not name.startswith(strip_prefix):
                    raise ValueError(f"Unexpected archive prefix: {entry.filename}")
                name = name[len(strip_prefix) :]
            if not name:
                continue
            target = (destination / name).resolve()
            if not target.is_relative_to(destination):
                raise ValueError(f"Archive path traversal rejected: {entry.filename}")
            content = bundle.read(entry)
            if target.exists():
                if target.read_bytes() != content:
                    raise ValueError(f"Refusing to overwrite a modified file: {target}")
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)


def bootstrap(offline: bool = False) -> dict[str, str]:
    manifest = load_manifest()
    dataset = manifest["dataset"]
    upstream = manifest["upstream"]
    downloads = ROOT / "data" / "raw" / "causrca" / "downloads"
    dataset_archive = downloads / dataset["archive_name"]
    upstream_archive = downloads / upstream["archive_name"]

    if not offline:
        download(dataset["url"], dataset_archive)
        download(upstream["url"], upstream_archive)
    if not dataset_archive.is_file() or not upstream_archive.is_file():
        raise FileNotFoundError("Missing causRCA archives. Re-run without --offline.")
    if digest(dataset_archive, "md5") != dataset["publisher_md5"]:
        raise ValueError("causRCA dataset MD5 differs from the publisher manifest")

    raw_root = ROOT / "data" / "raw" / "causrca"
    safe_extract(dataset_archive, raw_root)
    safe_extract(
        upstream_archive,
        ROOT / "third_party" / "causRCA",
        f"causRCA-{upstream['commit']}/",
    )
    return {
        "dataset_archive_sha256": digest(dataset_archive, "sha256"),
        "upstream_archive_sha256": digest(upstream_archive, "sha256"),
        "raw_data": str(raw_root),
        "upstream_source": str(ROOT / "third_party" / "causRCA"),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--offline", action="store_true", help="Verify local archives without downloading"
    )
    args = parser.parse_args()
    print(json.dumps(bootstrap(offline=args.offline), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

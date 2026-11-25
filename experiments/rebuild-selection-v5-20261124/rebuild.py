#!/usr/bin/env python3
"""Rebuild a linux/amd64 OCI image tar by overlaying changed runtime files.

This avoids needing a running Docker daemon: it takes a verified base image tar
(OCI layout + Docker manifest.json), adds one gzip layer containing the changed
files, updates the OCI config/manifest/index and Docker manifest consistently,
and writes a new tar with a reproducible SHA-256.
"""
import argparse
import gzip
import hashlib
import io
import json
import shutil
import tarfile
import tempfile
from datetime import datetime, timezone
from pathlib import Path


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def read_json(root: Path, rel: str):
    return json.loads((root / rel).read_text(encoding="utf-8"))


def write_json(root: Path, rel: str, obj):
    data = (json.dumps(obj, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")
    (root / rel).write_bytes(data)
    return digest(data), len(data)


def write_blob(root: Path, data: bytes):
    d = digest(data)
    path = root / "blobs" / "sha256" / d
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return d, len(data)


def refresh_source_manifest(context: Path):
    """Regenerate context/source-files.json file hashes from the context tree."""
    path = context / "source-files.json"
    old = json.loads(path.read_text(encoding="utf-8"))
    files = {}
    for p in sorted(context.rglob("*")):
        if p.is_file() and p != path:
            files[p.relative_to(context).as_posix()] = hashlib.sha256(p.read_bytes()).hexdigest()
    old["files"] = files
    path.write_text(json.dumps(old, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return old


def make_layer(context: Path, overlays, created: str):
    """Return (uncompressed tar bytes, gzipped bytes) for the overlay layer."""
    raw = io.BytesIO()
    with tarfile.open(fileobj=raw, mode="w") as tf:
        for src_rel, container_rel in overlays:
            src = context / src_rel
            if not src.is_file():
                raise FileNotFoundError(src)
            info = tf.gettarinfo(str(src), arcname=container_rel)
            info.uid = info.gid = 0
            info.uname = info.gname = ""
            info.mtime = 0
            with src.open("rb") as fh:
                tf.addfile(info, fh)
    raw_bytes = raw.getvalue()
    gz = io.BytesIO()
    with gzip.GzipFile(fileobj=gz, mode="wb", mtime=0, filename="") as fh:
        fh.write(raw_bytes)
    return raw_bytes, gz.getvalue()


def repack(root: Path, out: Path):
    out.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(out, "w") as tf:
        for p in sorted(root.rglob("*")):
            if p.is_file():
                info = tf.gettarinfo(str(p), arcname=p.relative_to(root).as_posix())
                info.uid = info.gid = 0
                info.uname = info.gname = ""
                info.mtime = 0
                with p.open("rb") as fh:
                    tf.addfile(info, fh)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-tar", type=Path, required=True)
    ap.add_argument("--context", type=Path, required=True)
    ap.add_argument("--output", type=Path, required=True)
    ap.add_argument("--tag", required=True)
    ap.add_argument("--sampler-path", default="unknown")
    ap.add_argument("--training-url", default="unknown")
    ap.add_argument("--source-sha", default="unknown")
    ap.add_argument("--notes", default="")
    args = ap.parse_args()

    created = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    with tempfile.TemporaryDirectory(prefix="raci-image-") as tmp:
        root = Path(tmp)
        with tarfile.open(args.base_tar) as tf:
            tf.extractall(root)

        source_manifest = refresh_source_manifest(args.context)
        overlays = [
            ("app/contest_submission.py", "app/contest_submission.py"),
            ("app/rac_hpo/contest/stage3_controls.py", "app/rac_hpo/contest/stage3_controls.py"),
            # New in v5: the shared decision-payload builder imported by the runtime.
            ("app/rac_hpo/contest/sampler.py", "app/rac_hpo/contest/sampler.py"),
            ("source-files.json", "app/source-files.json"),
        ]
        raw_layer, gz_layer = make_layer(args.context, overlays, created)
        layer_digest, layer_size = write_blob(root, gz_layer)
        diff_id = "sha256:" + digest(raw_layer)

        index = read_json(root, "index.json")
        desc = index["manifests"][0]
        old_manifest_digest = desc["digest"].split(":", 1)[1]
        manifest = read_json(root, f"blobs/sha256/{old_manifest_digest}")
        config_digest = manifest["config"]["digest"].split(":", 1)[1]
        config = read_json(root, f"blobs/sha256/{config_digest}")
        old_config_digest = config_digest

        config["rootfs"]["diff_ids"].append(diff_id)
        config["history"].append({
            "created": created,
            "created_by": "COPY selection-contract runtime files # rebuild-image-20261124",
            "comment": args.notes or "selection-contract runtime overlay",
        })
        new_config_bytes = (json.dumps(config, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")
        new_config_digest, new_config_size = write_blob(root, new_config_bytes)

        manifest["config"] = {
            "mediaType": "application/vnd.oci.image.config.v1+json",
            "digest": "sha256:" + new_config_digest,
            "size": new_config_size,
        }
        manifest["layers"].append({
            "mediaType": "application/vnd.oci.image.layer.v1.tar+gzip",
            "digest": "sha256:" + layer_digest,
            "size": layer_size,
        })
        new_manifest_bytes = (json.dumps(manifest, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")
        new_manifest_digest, new_manifest_size = write_blob(root, new_manifest_bytes)

        desc["digest"] = "sha256:" + new_manifest_digest
        desc["size"] = new_manifest_size
        desc.setdefault("annotations", {})
        desc["annotations"]["io.containerd.image.name"] = "docker.io/library/" + args.tag
        desc["annotations"]["org.opencontainers.image.ref.name"] = args.tag.split(":")[-1]
        write_json(root, "index.json", index)

        docker_manifest = read_json(root, "manifest.json")
        entry = docker_manifest[0]
        entry["Config"] = f"blobs/sha256/{new_config_digest}"
        entry["RepoTags"] = [args.tag]
        entry["Layers"].append(f"blobs/sha256/{layer_digest}")
        write_json(root, "manifest.json", docker_manifest)

        repack(root, args.output)

    archive_bytes = args.output.stat().st_size
    archive_sha = hashlib.sha256(args.output.read_bytes()).hexdigest()
    validation = {
        "image_tag": args.tag,
        "image_id": "sha256:" + new_manifest_digest,
        "parent_image_id": "sha256:" + old_manifest_digest,
        "parent_config_id": "sha256:" + old_config_digest,
        "platform": "linux/amd64",
        "archive_sha256": archive_sha,
        "archive_bytes": archive_bytes,
        "overlay_layer_sha256": "sha256:" + layer_digest,
        "overlay_layer_bytes": layer_size,
        "overlay_diff_id": diff_id,
        "created": created,
        "sampler_path": args.sampler_path,
        "training_record_url": args.training_url,
        "source_sampler_path": args.source_sha,
        "source_files": source_manifest["files"],
        "tests": {"status": "pending"},
        "notes": args.notes,
    }
    (args.output.parent / "build-validation.json").write_text(
        json.dumps(validation, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: validation[k] for k in (
        "image_tag", "image_id", "parent_image_id", "archive_sha256", "archive_bytes")}, ensure_ascii=False))


if __name__ == "__main__":
    main()

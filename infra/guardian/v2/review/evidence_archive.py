"""Lossless Guardian raw logs: deterministic gzip, immutable provenance, restore.

Pack only unprotected .txt/.xml/.diff under infra/guardian/v2/evidence. Original
logical paths and bytes remain recoverable; historical hash/command manifests
are NOT rewritten. Restore into a new directory, never overwrite source files.
"""

import argparse
import gzip
import hashlib
import io
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
PREFIX = Path("infra/guardian/v2/evidence")
INDEX = PREFIX / "raw-archive-index.json"


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def compressed(raw):
    output = io.BytesIO()
    with gzip.GzipFile(
        filename="", mode="wb", compresslevel=9, mtime=0, fileobj=output
    ) as f:
        f.write(raw)
    return output.getvalue()


def git(root, *args):
    p = subprocess.run(["git", *args], cwd=root, capture_output=True, text=True)
    return p.stdout.strip() if p.returncode == 0 else None


def metadata(root, path):
    refs, commands, generated, source_commits = [], [], [], []
    candidates = [path.with_name(path.stem + "-command.json")]
    candidates += [
        path.parent / n
        for n in (
            "commands.json",
            "native-commands.json",
            "before-commands.json",
            "after-commands.json",
        )
    ]
    for source in candidates:
        if not source.is_file():
            continue
        refs.append(str(source.relative_to(root)))
        data = json.loads(source.read_text())
        for row in data if isinstance(data, list) else [data]:
            if not isinstance(row, dict):
                continue
            name = row.get("output", row.get("log", row.get("name", row.get("label"))))
            if (
                len(data) == 1
                or name in (path.name, path.stem)
                or source == candidates[0]
            ):
                if "command" in row:
                    commands.append(row["command"])
                if "generatedAtUTC" in row:
                    generated.append(row["generatedAtUTC"])
                if "sourceCommit" in row:
                    source_commits.append(row["sourceCommit"])
    commit = git(root, "log", "-1", "--format=%H", "--", str(path.relative_to(root)))
    return dict(
        sourceCommit=commit,
        sourceBlob=git(root, "rev-parse", commit + ":" + str(path.relative_to(root)))
        if commit
        else None,
        sourceCommitTime=git(root, "show", "-s", "--format=%cI", commit)
        if commit
        else None,
        knownCollectionCommands=commands,
        knownGeneratedAtUTC=generated or None,
        knownImplementationCommits=source_commits or None,
        archivedAtCommit=git(root, "rev-parse", "HEAD"),
        metadataSources=refs,
        note="Unknown collection time is null; commit time is not log generation time.",
    )


def pack(root=ROOT):
    root = Path(root)
    protected = json.loads(
        (root / "contracts/v0.5/durable-live-2/protected-files.json").read_text()
    )["files"]
    index = root / INDEX
    doc = (
        json.loads(index.read_text())
        if index.exists()
        else dict(
            format="gzip-level9-mtime0-emptyfilename-os255",
            createdAtUTC=datetime.now(timezone.utc).isoformat(),
            archivedFromCommit=git(root, "rev-parse", "HEAD"),
            files={},
        )
    )
    selected = sorted(
        p
        for p in (root / PREFIX).rglob("*")
        if p.is_file() and p.suffix in (".txt", ".xml", ".diff")
    )
    # Entire selection is checked before mutation. Protected paths require an
    # exact Agent4 authorization; this tool provides no override switch.
    if any(str(p.relative_to(root)) in protected for p in selected):
        raise ValueError("protected source: Agent4 exact authorization required")
    for p in selected:
        logical = str(p.relative_to(root))
        if (
            p.is_symlink()
            or logical in doc["files"]
            or p.with_name(p.name + ".gz").exists()
        ):
            raise ValueError("source/archive collision")
    for p in selected:
        raw = p.read_bytes()
        archive = p.with_name(p.name + ".gz")
        blob = compressed(raw)
        assert gzip.decompress(blob) == raw
        with archive.open("xb") as f:
            f.write(blob)
        assert gzip.decompress(archive.read_bytes()) == raw
        doc["files"][str(p.relative_to(root))] = dict(
            archive=str(archive.relative_to(root)),
            rawSHA256=sha(raw),
            rawBytes=len(raw),
            archiveSHA256=sha(blob),
            provenance=metadata(root, p),
        )
        # Persist recovery metadata before removing the plain representation.
        index.write_text(json.dumps(doc, indent=2, sort_keys=True) + "\n")
        p.unlink()
    return len(selected)


def contents(root, doc):
    for logical, row in doc["files"].items():
        for name in (logical, row["archive"]):
            path = Path(name)
            if (
                path.is_absolute()
                or ".." in path.parts
                or not path.is_relative_to(PREFIX)
            ):
                raise ValueError("invalid archive path")
        path = root / row["archive"]
        if path.is_symlink():
            raise ValueError("symlink archive")
        blob = path.read_bytes()
        if sha(blob) != row["archiveSHA256"]:
            raise ValueError("archive hash mismatch")
        raw = gzip.decompress(blob)
        if len(raw) != row["rawBytes"] or sha(raw) != row["rawSHA256"]:
            raise ValueError("restored hash mismatch")
        yield logical, raw


def verify(root=ROOT):
    root = Path(root)
    doc = json.loads((root / INDEX).read_text())
    return sum(1 for _ in contents(root, doc))


def restore(destination, root=ROOT):
    root, destination = Path(root), Path(destination)
    doc = json.loads((root / INDEX).read_text())
    # Validate all bytes before creating any restored files; refuse existing
    # destinations to avoid replacing original evidence or following symlinks.
    rows = list(contents(root, doc))
    destination.mkdir(parents=True, exist_ok=False)
    for logical, raw in rows:
        path = destination / logical
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("xb") as f:
            f.write(raw)
        assert sha(path.read_bytes()) == doc["files"][logical]["rawSHA256"]
    return len(rows)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("pack", "verify", "restore"))
    parser.add_argument("--destination", type=Path)
    args = parser.parse_args()
    if args.operation == "restore":
        if args.destination is None:
            parser.error("restore requires --destination (new directory)")
        count = restore(args.destination)
    else:
        count = pack() if args.operation == "pack" else verify()
    print(json.dumps(dict(operation=args.operation, verifiedFiles=count)))


if __name__ == "__main__":
    main()

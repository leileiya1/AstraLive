import json

import pytest

from infra.guardian.v2.review.evidence_archive import (
    INDEX,
    PREFIX,
    compressed,
    pack,
    restore,
    sha,
    verify,
)


def source(tmp_path):
    root = tmp_path / "source"
    path = root / PREFIX / "failure.txt"
    path.parent.mkdir(parents=True)
    raw = b"FAILED original test   \r\nsecret-free data\t\n\n\n"
    path.write_bytes(raw)
    protected = root / "contracts/v0.5/durable-live-2/protected-files.json"
    protected.parent.mkdir(parents=True)
    protected.write_text('{"files": {}}')
    return root, path, raw, protected


def test_exact_bytes_and_deterministic_archive(tmp_path):
    root, path, raw, _ = source(tmp_path)
    assert compressed(raw) == compressed(raw)
    assert pack(root) == 1 and not path.exists()
    assert verify(root) == 1
    assert restore(tmp_path / "restored", root) == 1
    assert (tmp_path / "restored" / path.relative_to(root)).read_bytes() == raw
    doc = json.loads((root / INDEX).read_text())
    assert doc["files"][str(path.relative_to(root))]["rawSHA256"] == sha(raw)
    with pytest.raises(FileExistsError):
        restore(tmp_path / "restored", root)


def test_protected_file_refuses_before_any_replacement(tmp_path):
    root, path, raw, protected = source(tmp_path)
    protected.write_text(
        json.dumps(dict(files={str(path.relative_to(root)): sha(raw)}))
    )
    with pytest.raises(ValueError, match="protected"):
        pack(root)
    assert path.read_bytes() == raw and not path.with_name(path.name + ".gz").exists()


def test_tampered_archive_refuses_restore_before_destination_creation(tmp_path):
    root, path, _, _ = source(tmp_path)
    pack(root)
    path.with_name(path.name + ".gz").write_bytes(b"tampered")
    destination = tmp_path / "restored"
    with pytest.raises(ValueError, match="archive hash"):
        restore(destination, root)
    assert not destination.exists()


def test_known_collection_metadata_is_preserved(tmp_path):
    root, path, _, _ = source(tmp_path)
    command = ["python", "-m", "pytest", "inert-example"]
    (path.parent / "final-check-commands.json").write_text(
        json.dumps(
            [
                dict(
                    log=path.name,
                    command=command,
                    sourceCommit="known-fixed-test-pin",
                    generatedAtUTC="2026-10-19T00:00:00+00:00",
                )
            ]
        )
    )
    pack(root)
    doc = json.loads((root / INDEX).read_text())
    meta = doc["files"][str(path.relative_to(root))]["provenance"]
    assert meta["knownCollectionCommands"] == [command]
    assert meta["knownImplementationCommits"] == ["known-fixed-test-pin"]
    assert meta["knownGeneratedAtUTC"] == ["2026-10-19T00:00:00+00:00"]

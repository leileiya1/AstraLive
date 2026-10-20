# Exact original log recovery

Original `.txt`, `.xml` and `.diff` evidence under this directory's `evidence/`
is now represented by adjacent `.gz` files. This fixes full-PR whitespace checks
without altering the original bytes, discarding failures, changing attributes
or weakening validators. Old text links are logical paths in the archive index;
the original immutable PR11 commits also retain the plain historical files.

`evidence/raw-archive-index.json` records each original logical path, SHA256 and
byte length, archive SHA256, known source commit/blob/commit time, collection
commands and generation times, and references to the original command metadata.
Unknown generation times are explicitly null. A source commit time is not
presented as a collection time. Existing historical JSON hash/command manifests
remain unchanged and verify against restored files.

The representation is gzip level9, `mtime=0`, empty filename and OS255. Repacking
the same bytes is deterministic. No protected evidence was selected. The pack
tool checks the complete selection against the current protected inventory and
refuses protected files, existing archives, duplicate index paths and symlinks;
there is no override or protected-hash refresh.

Verify every compressed file and the exact restored byte hashes:

```sh
.venv-guardian/bin/python infra/guardian/v2/review/evidence_archive.py verify
```

Restore all original logical paths below a **new, absent** destination:

```sh
.venv-guardian/bin/python infra/guardian/v2/review/evidence_archive.py restore \
  --destination /tmp/astralive-evidence-restored-new
```

All archive bytes and uncompressed hashes are verified before the destination
is created. The script refuses an existing destination. It does not overwrite
the checkout. A single log can also be read with `gzip -dc path.txt.gz`; compare
its SHA256 to `rawSHA256` in the index. Ordinary archive verification is not
physical media or fencing acceptance.

Migration verification compares all136 raw files from blocked commit
`9b969d099b7a3b6b85f3595d26c36fb953d47263` byte-for-byte with their gzip restorations.
The recovery test additionally validates all198 entries in the prior Owner
evidence manifest. Original LEASE_LOST, RTMP tail mismatch, setup failures,
development errors and old whitespace failures are retained exactly. Current
run logs use the same lossless representation and include known UTC collection
times, commands and tested commit pins.

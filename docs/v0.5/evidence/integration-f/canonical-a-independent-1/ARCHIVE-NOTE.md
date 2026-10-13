# Evidence archive boundary

Raw review result, manifest, probe and logs are retained unchanged. The review's exported source tree and stopped temporary PostgreSQL data directory are intentionally excluded from this evidence tree. They are execution workspace copies, not additional acceptance results.

Recreate the source with `git archive c07658836c489105d33d56650c45c775152a351e` and the retained independent probe. Create a fresh owned PostgreSQL cluster using the commands recorded in the review. The original independent reviewer workspace remains available at the path in README; this cleanup did not remove original regression tests, reviewer logs or the pinned source from Git history.

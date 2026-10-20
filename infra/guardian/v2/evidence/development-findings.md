# Development probes before recorded acceptance

These are development failures/corrections, not omitted final gate failures.
Their original console output remains in this work session's tool records;
separate raw stdout files were not captured at that stage. All recorded final
commands and all54/67/69-case v2 runs are preserved separately and passed.

- Consume initially tried an absent Artifact factSetHash field, preventing the
  Commit pause test from reaching its barrier. Corrected to the frozen canonical
  hash of factDependencies. Current Authority identity tests retain strict checks.
- Direct libav FFV1 decode probe returned avcodec_open2 InvalidDataError until
  decoder width/height/pixel format were supplied. The final tests verify exact
  decoded bytes and original nonzero PTS, without any padding/clock rewrite.
- CPU continuation mock Evidence lacked predecessor checkpoint IDs; the frozen
  validator correctly rejected it. Added a clearly synthetic predecessor to
  the mock envelope; production validation was not weakened.
- An early backlog test assumed two sinks while the contract fixture configured
  one. The final test explicitly provisions two CPU sinks and asserts both the
  unblocked sink's real decoded output and the paused sink's postStop rejection.
- Darwin rejected pytest's long AF_UNIX path. Test-only IPC now uses its own
  short /tmp directory, removed by fixture finalizers; no shared socket reused.
- A wrong-channel test initially sent an incomplete Media request, so schema
  rejection preceded channel checks. It now sends a valid Renew identity;
  actual IPC tests additionally exercise independent connection bindings.
- The first local Stage route spelling omitted /bootstrap. It was corrected
  to the frozen route and an exact seven-route/role comparison was added.
- Consume fsync and Stop persistence initially shared an I/O mutex. Immutable
  independently named records removed that dependency. The final test requires
  Stop to finish before the paused Consume fsync is released.
- A killed multiprocessing RLock owner could otherwise block forever. The
  implementation now irreversibly poisons admission on bounded acquisition
  failure, and a genuine SIGKILL-while-owning-lock test verifies that behavior.

The file/directory EIO injection tests are explicitly distinct from the later
real kernel EBADF descriptor-fault tests and SIGKILL durability tests. No host
power-cut or physical storage-device failure claim is made.

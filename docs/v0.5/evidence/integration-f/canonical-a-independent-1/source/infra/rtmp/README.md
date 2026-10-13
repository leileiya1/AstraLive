# Local RTMP ingest

This isolated MediaMTX service exists only for integration and acceptance tests. It is not part of the Runtime and has no platform-specific logic.

```bash
docker compose -f infra/rtmp/compose.yaml up -d
ffprobe -v error -show_streams -show_format -of json rtmp://127.0.0.1:1935/live/astralive-test
docker compose -f infra/rtmp/compose.yaml down
```

The test stream name is a fake value. Real platform URLs or stream keys must never be committed or written to evidence.

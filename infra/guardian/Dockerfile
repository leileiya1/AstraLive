FROM bluenviron/mediamtx:1.21.1 AS ingest
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY output_guardian/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt && useradd -u 22005 -M guardian
COPY --from=ingest /mediamtx /usr/local/bin/mediamtx
COPY output_guardian /app/output_guardian
# Existing aiortc tracks are reused only inside the Guardian process.
COPY runtime/app /app/runtime/app
USER 22005:22005
ENTRYPOINT ["python", "-m", "output_guardian.supervisor", "--config", "/run/guardian/config.json"]

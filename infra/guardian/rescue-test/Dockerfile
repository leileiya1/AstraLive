# Linux CPU test image for the Output Guardian suites. TEST ONLY: no service,
# no published port, no credentials. PostgreSQL and MediaMTX run privately
# inside the container on loopback; run it with --network none.
#
# Build context: `git archive HEAD output_guardian runtime tests contracts
#   astralive_contracts backend/db/migrations infra/guardian scripts`
FROM bluenviron/mediamtx:1.21.1 AS ingest

FROM python:3.12-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 LC_ALL=C.UTF-8 LANG=C.UTF-8
RUN apt-get update \
 && apt-get install -y --no-install-recommends ca-certificates curl gnupg \
 && install -d /usr/share/postgresql-common/pgdg \
 && curl -fsSL https://www.postgresql.org/media/keys/ACCC4CF8.asc \
      -o /usr/share/postgresql-common/pgdg/apt.postgresql.org.asc \
 && echo "deb [signed-by=/usr/share/postgresql-common/pgdg/apt.postgresql.org.asc] https://apt.postgresql.org/pub/repos/apt bookworm-pgdg main" \
      > /etc/apt/sources.list.d/pgdg.list \
 && apt-get update \
 && apt-get install -y --no-install-recommends postgresql-17 \
 && apt-get purge -y curl gnupg && apt-get autoremove -y \
 && rm -rf /var/lib/apt/lists/*
COPY --from=ingest /mediamtx /usr/local/bin/mediamtx
WORKDIR /src
COPY output_guardian/requirements.txt output_guardian/requirements-test.txt /tmp/
RUN pip install --no-cache-dir -r /tmp/requirements.txt -r /tmp/requirements-test.txt \
      aiohttp==3.14.5 asyncpg==0.32.0 av==17.1.0 numpy==2.5.4 aiortc==1.15.0 \
      psutil==7.2.2 httpx==0.28.1 pydantic==2.14.1 pytest==9.1.1 pytest-asyncio==1.4.0 \
      jsonschema==4.26.0
COPY . /src
RUN useradd -u 22099 -m tester && chown -R tester /src
USER tester
ENV GUARDIAN_TEST_PG_BIN=/usr/lib/postgresql/17/bin \
    GUARDIAN_TEST_MEDIAMTX=/usr/local/bin/mediamtx
ENTRYPOINT ["python", "-m", "pytest", "-p", "no:cacheprovider"]
CMD ["output_guardian/tests", "-q", "-rfEs"]

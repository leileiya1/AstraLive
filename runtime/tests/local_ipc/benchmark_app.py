"""Benchmark-only wrapper over actual Runtime: missing Session means no media work.
Server timing uses one monotonic clock; it includes ASGI routing, token, parsing,
validation, and Session lookup. It excludes providers (none are called).
"""
import time
from app.main import app

@app.middleware("http")
async def benchmark_timing(request, call_next):
    begin = time.perf_counter_ns()
    response = await call_next(request)
    response.headers['Server-Timing'] = f'app;dur={(time.perf_counter_ns()-begin)/1e6:.6f}'
    return response

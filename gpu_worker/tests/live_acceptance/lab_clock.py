"""Accepted product paired clock with an isolated acceptance evidence journal."""
import os,pathlib
from gpu_worker.validated.paired_rtmp import PairedRTMPMediaOutput as ProductClock
class PairedRTMPMediaOutput(ProductClock):
    def __init__(self,settings):
        super().__init__(settings,(pathlib.Path(os.environ['SOULX_EXPERIMENT_DIR'])/'integration/rtmp-paired-clock.jsonl').open('a',buffering=1))

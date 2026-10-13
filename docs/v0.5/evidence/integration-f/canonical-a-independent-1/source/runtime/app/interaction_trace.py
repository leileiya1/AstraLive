"""Content-free per-process monotonic spans. No remote wall-clock subtraction."""
import logging
import json
import time
from collections import OrderedDict

log = logging.getLogger(__name__)

class InteractionTrace:
    def __init__(self, trace_id, session_id, utterance_id, clock=time.monotonic):
        self.ids = dict(traceId=trace_id, sessionId=session_id, utteranceId=utterance_id)
        self.clock = clock
        self.origin = clock()
        self.points = {}
        self.media = {}

    def mark(self, stage, boundary='runtime instrumentation'):
        if stage in self.points:
            return
        self.points[stage] = (self.clock() - self.origin) * 1000
        record = dict(self.ids, stage=stage, elapsedMs=self.points[stage], clockDomain='runtime_monotonic', boundary=boundary)
        log.info('interaction_trace %s', json.dumps(record))

    def annotate_media(self, **values):
        allowed = {'generationId', 'speechMarker', 'firstVideoPTSUS', 'speechOriginSample'}
        for key, value in values.items():
            if key in allowed and type(value) is int and 0 <= value < 2**63:
                self.media.setdefault(key, value)

    def summary(self):
        # Sample on the response clock. An observer's request/response interval
        # bounds alignment uncertainty; never subtract remote wall timestamps.
        return dict(self.ids, clockDomain='runtime_monotonic',
                    clockOriginAgeMs=(self.clock()-self.origin)*1000,
                    points=dict(self.points), media=dict(self.media))

# bounded, content-free operational trace cache, inspectable via authenticated control API
traces = OrderedDict()
def retain(trace):
    traces[(trace.ids['sessionId'], trace.ids['utteranceId'])] = trace
    while len(traces) > 256:
        traces.popitem(last=False)

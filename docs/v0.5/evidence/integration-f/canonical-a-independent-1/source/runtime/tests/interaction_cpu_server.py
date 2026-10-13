"""TEST ONLY: formal BoundSessionManager + actual SQL binding/Redis, fake providers.
Never imported by production. The fake bundle cannot report REAL.
"""
import os
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import uvicorn
from app.main import create_app
from app.providers import MockLLMProvider, MockTTSProvider, MockAvatarEngine, MockMediaOutput, VideoFrame
from app.interaction_trace import traces
from app.session import RuntimeFailure

class SyntheticAvatar(MockAvatarEngine):
    """Explicit RGB test frame, not SoulX inference."""
    async def push_audio(self, chunk):
        await super().push_audio(chunk)
        return [VideoFrame(chunk.generation_id, chunk.sequence*40000, 2, 2, bytes([40,80,120])*4)]

app = create_app(factories=(MockLLMProvider, MockTTSProvider, SyntheticAvatar, MockMediaOutput))
app.state.manager.bundle_builder = lambda packet, sid, media, errors: (MockLLMProvider, MockTTSProvider, SyntheticAvatar, MockMediaOutput)

reject_next = False
original_speak = app.state.manager.speak
async def injectable_speak(sid, item):
    global reject_next
    if reject_next:
        reject_next = False
        raise RuntimeFailure('RUNTIME_OVERLOADED', 'FAKE rejection', 429)
    await original_speak(sid, item)
app.state.manager.speak = injectable_speak
@app.post('/internal/test/reject-next')
async def reject():
    global reject_next
    reject_next = True
    return {'fake': True}

# Observe genuine CPU calls/trace counts through protected test-only endpoints.
@app.get('/internal/test/interaction')
async def diagnostics():
    return {'fixture': 'CPU_MOCK_NOT_REAL', 'sessions': len(app.state.manager.sessions), 'leases': len(app.state.manager.leases), 'traces': [t.summary() for t in traces.values()]}

if __name__ == '__main__':
    uvicorn.run(app, host='127.0.0.1', port=int(sys.argv[1]), log_level='warning')

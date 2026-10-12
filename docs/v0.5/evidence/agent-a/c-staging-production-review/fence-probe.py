import asyncio,json
from types import SimpleNamespace
from app.narration_segments import SegmentExecutor
async def main():
 ex=object.__new__(SegmentExecutor);ex.pose_task=None;ex.closed=False
 async def record(*args):pass
 class Timeline:
  sealed=False
  journal=SimpleNamespace(record=record)
  def fence_now(self,reason):self.sealed=True
 ex.timeline=Timeline();entered=asyncio.Event();resume=asyncio.Event()
 async def fail(command,attempt):raise RuntimeError("injected post-handoff sink failure")
 async def cleanup(reason):entered.set();await resume.wait()
 ex._execute=fail;ex._cancel_staging=cleanup
 task=asyncio.create_task(ex._execute_guarded({},None));await entered.wait()
 result={"source":"b9dd24614ee70c770a69f287f724f6bb1ff851fd","publicationFencedBeforeCleanupAwait":ex.timeline.sealed,"scope":"actual SegmentExecutor exception-order probe; no real sink/media/GPU"}
 print(json.dumps(result),flush=True);resume.set()
 try:await task
 except RuntimeError:pass
asyncio.run(main())

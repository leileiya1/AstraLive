import json,pathlib
p=pathlib.Path(__file__).parent/'integration/public-dual-one-hour-20261009';summary=p/'summary.json'
if summary.exists():print(summary.read_text())
else:
 rows=[json.loads(x) for x in (p/'browser-events.jsonl').read_text().splitlines()]
 cycles=[x for x in rows if x['event']=='Cycle'];cp=[x for x in rows if x['event']=='Checkpoint'];force=[x for x in rows if x['event']=='FORCE_DisplayFence']
 leaks=[x for x in rows if x['event']=='BrowserFrameDisplayed' and force and x['browserMonotonic']>force[-1]['browserMonotonic'] and x['generation']<force[-1]['minimumGeneration']]
 print(json.dumps(dict(last_cycle=cycles[-1] if cycles else None,checkpoints=[x['requestedSeconds'] for x in cp],old_generation_displayed_after_force=len(leaks),last_event_browser_s=rows[-1]['browserMonotonic']),ensure_ascii=False))

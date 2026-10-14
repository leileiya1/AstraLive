"""Actual browser JS, controlled clocks/stats: oracle tests, not real RTP/GPU."""
import json
import os
from pathlib import Path
import unittest

from playwright.async_api import async_playwright


class GoldenAudioPreflightTests(unittest.IsolatedAsyncioTestCase):
    async def test_initial_missing_report_and_real_stall_rejection(self):
        html = Path(os.environ.get('GOLDEN_AUDIO_PREFLIGHT_HTML',
                    str(Path(__file__).parent/'fixtures/golden_browser.html'))).read_text()
        cases = [('late-first-report', True), ('initial-report', True),
                 ('missing-report', False), ('late-insufficient-window', False),
                 ('context-stalled', False), ('decoded-stalled', False),
                 ('report-replaced', False), ('nonfinite-duration', False),
                 ('nonfinite-context', False), ('suspended', False),
                 ('ended-track', False), ('disabled-track', False)]
        async with async_playwright() as p:
            browser = await p.chromium.launch(channel='chrome', headless=True)
            try:
                page = await browser.new_page()
                for kind, expected in cases:
                    with self.subTest(kind=kind):
                        await page.set_content(html)
                        # Exercise the exact HTML function. No readiness field
                        # or synthesized audio bypasses its checks.
                        result = await page.evaluate("""async kind=>{
                          let time=0,calls=0;
                          Object.defineProperty(performance,'now',{configurable:true,value:()=>time});
                          window.requestAnimationFrame=callback=>{time+=50;Promise.resolve().then(()=>callback(time));};
                          ac={state:kind==='suspended'?'suspended':'running',
                            get currentTime(){return kind==='context-stalled'?0:kind==='nonfinite-context'?NaN:time/1000;},
                            getOutputTimestamp(){return {contextTime:this.currentTime,performanceTime:time};}};
                          audioActivation=Promise.resolve();audioSource={};
                          stream={getAudioTracks:()=>[{readyState:kind==='ended-track'?'ended':'live',enabled:kind!=='disabled-track',muted:false}]};
                          pc={getStats:async()=>{
                            const index=calls++,reports=new Map();
                            if(kind==='missing-report' || kind==='late-first-report'&&index===0 || kind==='late-insufficient-window'&&time<1450)return reports;
                            const id=kind==='report-replaced'?'report-'+index:'audio-report';
                            reports.set(id,{id,type:'inbound-rtp',kind:'audio',packetsReceived:index,
                              totalSamplesDuration:kind==='decoded-stalled'?0:kind==='nonfinite-duration'?Infinity:time/1000});
                            return reports;
                          }};
                          return await goldenAudioReady();
                        }""", kind)
                        self.assertEqual(result['ready'], expected, json.dumps(result))
                        if kind == 'late-first-report':
                            self.assertFalse(result['initialInboundAvailable'])
                            self.assertGreater(result['baselineWaitMs'], 0)
                            self.assertGreaterEqual(result['decodedAudioDeltaSeconds'], .1)
                            self.assertLessEqual(result['after']['at']-result['started']['at'], 1500)
            finally:
                await browser.close()


if __name__ == '__main__':
    unittest.main()

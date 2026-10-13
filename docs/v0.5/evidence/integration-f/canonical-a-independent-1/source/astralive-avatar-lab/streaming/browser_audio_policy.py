"""Authorize only output selection in an isolated acceptance Chrome profile.
The CDP connection stays open: disconnecting it revokes temporary permission
and can invalidate the concrete output pin. No microphone is opened/granted.
"""
import pathlib,time
from cpu_cdp import CDP

def prepare_output_policy(profile,origin,timeout=10):
 deadline=time.monotonic()+timeout;profile=pathlib.Path(profile)
 while not(profile/'DevToolsActivePort').exists():
  if time.monotonic()>deadline:raise TimeoutError('Chrome debugging endpoint unavailable')
  time.sleep(.05)
 port,path=(profile/'DevToolsActivePort').read_text().splitlines();client=CDP('ws://127.0.0.1:'+port+path)
 try:
  target=next(x for x in client.call('Target.getTargets')['targetInfos']if x['type']=='page');session=client.call('Target.attachToTarget',{'targetId':target['targetId'],'flatten':True})['sessionId'];client.call('Page.navigate',{'url':origin},session)
  while client.call('Runtime.evaluate',{'expression':'location.origin','returnByValue':True},session)['result'].get('value')!=origin:
   if time.monotonic()>deadline:raise TimeoutError('Chrome page origin not committed')
   time.sleep(.05)
  client.call('Browser.setPermission',{'permission':{'name':'speaker-selection'},'setting':'granted','origin':origin,'browserContextId':target['browserContextId']})
  return client
 except BaseException:client.close();raise

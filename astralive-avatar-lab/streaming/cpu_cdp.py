"""Small stdlib CDP client for disposable CPU-test Chrome profiles only."""
import base64,json,os,socket,struct,urllib.request,urllib.parse
class CDP:
 def __init__(self,url):
  u=urllib.parse.urlsplit(url);self.s=socket.create_connection((u.hostname,u.port),timeout=10);self.f=self.s.makefile('rb');self.seq=0
  key=base64.b64encode(os.urandom(16)).decode();self.s.sendall((f'GET {u.path} HTTP/1.1\r\nHost: {u.hostname}:{u.port}\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n').encode());status=self.f.readline();assert b'101' in status,status
  while self.f.readline()!=b'\r\n':pass
 def read(self,n):
  b=self.f.read(n)
  if len(b)!=n:raise EOFError('CDP socket closed')
  return b
 def call(self,method,params=None,session=None):
  self.seq+=1;d={'id':self.seq,'method':method,'params':params or {}}
  if session:d['sessionId']=session
  b=json.dumps(d).encode();mask=os.urandom(4);header=bytes([0x81,0x80|len(b)]) if len(b)<126 else bytes([0x81,0xfe])+struct.pack('!H',len(b));self.s.sendall(header+mask+bytes(x^mask[i%4]for i,x in enumerate(b)))
  while True:
   a,z=self.read(2);size=z&127
   if size==126:size=struct.unpack('!H',self.read(2))[0]
   elif size==127:size=struct.unpack('!Q',self.read(8))[0]
   m=self.read(4)if z&128 else None;body=self.read(size)
   if m:body=bytes(x^m[i%4]for i,x in enumerate(body))
   if a&15==8:raise EOFError('CDP close')
   if a&15!=1:continue
   d=json.loads(body)
   if d.get('id')==self.seq:
    if 'error'in d:raise RuntimeError(d['error'])
    return d.get('result',{})
 def close(self):self.f.close();self.s.close()

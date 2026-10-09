import json,struct
MAX_HEADER=16384
MAX_PAYLOAD=2097152

def read_exact(sock,n):
    out=bytearray()
    while len(out)<n:
        chunk=sock.recv(n-len(out))
        if not chunk:raise EOFError('worker connection closed')
        out.extend(chunk)
    return bytes(out)

def receive(sock):
    h,p=struct.unpack('!II',read_exact(sock,8))
    if h>MAX_HEADER or p>MAX_PAYLOAD:raise ValueError('oversize packet')
    header=json.loads(read_exact(sock,h))
    if not isinstance(header,dict):raise ValueError('invalid header')
    return header,read_exact(sock,p)

def send(sock,header,payload=b''):
    h=json.dumps(header,separators=(',',':')).encode()
    if len(h)>MAX_HEADER or len(payload)>MAX_PAYLOAD:raise ValueError('oversize packet')
    sock.sendall(struct.pack('!II',len(h),len(payload))+h+payload)

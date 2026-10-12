import json,hashlib,sys
from app.durability_client import canonical,timeline_canonical
out=[]
for v in json.load(open(sys.argv[1])):
 try: value=(timeline_canonical if v["timeline"] else canonical)(json.loads(v["raw"]));accepted=True;digest="sha256:"+hashlib.sha256(value).hexdigest()
 except ValueError: accepted=False;digest=""
 assert accepted==v["valid"],v["name"]
 out.append({"name":v["name"],"accepted":accepted,"hash":digest})
print(json.dumps(out))

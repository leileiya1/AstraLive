"""Independent strict wire / generated DTO parity; no services or media claims."""
import base64
import copy
import dataclasses
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import traceback
import unittest

from astralive_contracts import durable_live_v2 as w
from astralive_contracts.durable_live_v2 import codec
from jsonschema import Draft202012Validator

ROOT=Path(__file__).resolve().parents[1]
CONTRACT=ROOT/'contracts/v0.5/durable-live-2'
SCHEMA=json.loads((CONTRACT/'schema.json').read_text())

def raw(v):return json.dumps(v,ensure_ascii=False,separators=(',',':')).encode()
def load(p):return json.loads((CONTRACT/p).read_text())

def all_fixtures():
    rows=[]
    for f in ('examples/protocol.json','examples/receiver-protocol.json'):
        for message in load(f):
            op=w.OPERATIONS[message['operationId']]
            rows.extend([(op.request_schema,message['request']),(op.response_schema,message['response'])])
    rows.extend((o['schemaRef'].split('/')[-1],o['value']) for o in load('examples/objects.json'))
    rows.append(('AnswerLifecycleTrace',load('examples/grant-renewal-trace.json')))
    for message in load('examples/receiver-trace.json')['messages']:
        op=w.OPERATIONS[message['operationId']]
        rows.extend([(op.request_schema,message['request']),(op.response_schema,message['response'])])
    for scenario in load('examples/receiver-stop-trace.json')['scenarios']:
        for message in scenario['bootstrapMessages']+scenario['operations']:
            op=w.OPERATIONS[message['operationId']]
            rows.append((op.request_schema,message['request']))
            rows.append(('ReceiverErrorResponse',message['error']) if 'error'in message else (op.response_schema,message['response']))
    return rows

class WireTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory(prefix='astralive-wire-interop-');cls.binary=Path(cls.temp.name)/'wirecheck'
        subprocess.run(['go','build','-o',str(cls.binary),'./internal/durablelivev2/wire/testdata/interop'],cwd=ROOT/'backend',check=True,capture_output=True)
    @classmethod
    def tearDownClass(cls):cls.temp.cleanup()
    def go(self,rows):
        payload=b''.join(raw({**row,'Body':base64.b64encode(row.get('raw',b'')).decode(),'raw':None})+b'\n' for row in rows)
        result=subprocess.run([str(self.binary)],input=payload,capture_output=True,check=True)
        return [json.loads(line) for line in result.stdout.splitlines()]
    def test_all_fixtures_typed_roundtrip_and_reference_schema(self):
        rows=all_fixtures();results=self.go([dict(Schema=name,raw=raw(value)) for name,value in rows])
        for (name,value),result in zip(rows,results):
            with self.subTest(schema=name):
                Draft202012Validator({'$defs':SCHEMA['$defs'],'$ref':'#/$defs/'+name}).validate(value)
                obj=w.decode(name,raw(value));self.assertNotIsInstance(obj,dict)
                self.assertTrue(result['OK'],result['Error']);self.assertEqual(json.loads(w.encode(obj)),value)
                self.assertEqual(w.encode(obj),base64.b64decode(result['Body']))
    def test_every_definition_is_registered_and_has_a_valid_typed_witness(self):
        cases={}
        def visit(sp,value):
            if '$ref'in sp:
                name=sp['$ref'].split('/')[-1];cases.setdefault(name,value);visit(SCHEMA['$defs'][name],value)
            elif 'anyOf'in sp:
                if value is not None:visit(next(x for x in sp['anyOf'] if x.get('type')!='null'),value)
            elif sp.get('type')=='object':
                for field,child in sp['properties'].items():visit(child,value[field])
            elif sp.get('type')=='array':
                for child in value:visit(sp['items'],child)
        for name,value in all_fixtures():cases.setdefault(name,value);visit(SCHEMA['$defs'][name],value)
        def minimal(s):
            if '$ref'in s:return minimal(SCHEMA['$defs'][s['$ref'].split('/')[-1]])
            if 'const'in s:return s['const']
            if 'enum'in s:return s['enum'][0]
            if 'anyOf'in s:return None
            if s.get('type')=='object':return {f:minimal(v) for f,v in s['properties'].items()}
            if s.get('type')=='array':return [minimal(s['items']) for _ in range(s.get('minItems',0))]
            if s.get('type')=='integer':return max(0,s.get('minimum',0))
            if s.get('type')=='boolean':return False
            if s.get('pattern')=='^[0-9a-f]{64}$':return 'a'*64
            if s.get('format')=='date-time':return '2026-10-17T00:00:00Z'
            return 'value'
        for name,s in SCHEMA['$defs'].items():
            if name not in cases:cases[name]=minimal(s)
        self.assertEqual(set(SCHEMA['$defs']),set(codec.MODELS)-{'AnswerLifecycleTraceHandoffsItem'})
        result=self.go([dict(Schema=name,raw=raw(cases[name])) for name in SCHEMA['$defs']])
        for name,r in zip(SCHEMA['$defs'],result):
            with self.subTest(schema=name):self.assertTrue(r['OK']);self.assertIsNotNone(w.decode(name,raw(cases[name])))
    def test_13_golden_vectors(self):
        vectors=load('examples/hash-vectors.json');self.assertEqual(len(vectors),13)
        results=self.go([dict(Mode='canonical',raw=raw(v['value'])) for v in vectors])
        for vector,result in zip(vectors,results):
            self.assertTrue(result['OK']);self.assertEqual(w.canonical_json(vector['value']).decode(),vector['canonicalUtf8'])
            self.assertEqual(w.digest(vector['value']),vector['sha256']);self.assertEqual(result['Digest'],vector['sha256'])
            self.assertEqual(base64.b64decode(result['Body']),w.canonical_json(vector['value']))
    def test_required_nullable_missing_and_type_mutations_cross_language(self):
        rows=[]
        # Every property in every object definition encountered in all fixtures:
        # remove it, add unknown field, and assign a plainly wrong JSON kind.
        for name,value in all_fixtures():
            if not isinstance(value,dict):continue
            mutated=copy.deepcopy(value);mutated['unapprovedField']='A'*43;rows.append((name,mutated))
            for field in value:
                missing=copy.deepcopy(value);missing.pop(field);rows.append((name,missing))
                wrong=copy.deepcopy(value);wrong[field]={};rows.append((name,wrong))
        # {} is a valid value only for an open/empty object; there are none here.
        results=self.go([dict(Schema=name,raw=raw(v)) for name,v in rows])
        for (name,value),result in zip(rows,results):
            with self.subTest(schema=name):
                self.assertFalse(result['OK'])
                with self.assertRaises(w.WireError):w.decode(name,raw(value))
    def test_38_operation_role_target_route_method_and_version_checks(self):
        fixtures=load('examples/protocol.json')+load('examples/receiver-protocol.json');cases=[];expected=[]
        for fixture in fixtures:
            op=w.OPERATIONS[fixture['operationId']]
            context=dict(role=op.roles[0],target=op.target,method=op.method,route_template=op.path)
            for change in ({},{'role':'BROWSER'},{'target':'PUBLIC'},{'method':'GET'},{'route_template':'/guardian/v1/media'}):
                ctx=context|change;cases.append(dict(Mode='request',Operation=op.id,Role=ctx['role'],Target=ctx['target'],Method=ctx['method'],Route=ctx['route_template'],raw=raw(fixture['request'])));expected.append(not change)
                if change:
                    with self.assertRaises(w.WireError):w.decode_request(op.id,raw(fixture['request']),**ctx)
                else:
                    obj=w.decode_request(op.id,raw(fixture['request']),**ctx);self.assertNotIsInstance(obj,dict)
                    self.assertEqual(json.loads(w.encode_request(op.id,obj,**ctx)),fixture['request'])
            for field in ('contractRevision','receiverRevision','schemaVersion'):
                if field in fixture['request']:
                    bad=copy.deepcopy(fixture['request']);bad[field]='old-version';cases.append(dict(Schema=op.request_schema,raw=raw(bad)));expected.append(False)
                    with self.assertRaises(w.WireError):w.decode(op.request_schema,raw(bad))
        self.assertEqual([r['OK'] for r in self.go(cases)],expected)
    def test_secret_diagnostics_and_invalid_json_never_echo_payload(self):
        fixture=next(r for r in load('examples/receiver-protocol.json') if r['operationId']=='ReceiverConsume')
        ticket=fixture['request']['consumeTicket'];obj=w.decode('ReceiverConsumeRequest',raw(fixture['request']))
        self.assertNotIn(ticket,repr(obj));self.assertNotIn(ticket,str(obj));self.assertNotIn(ticket,repr(obj.consumeTicket));self.assertNotIn(ticket,f'{obj.consumeTicket}')
        with self.assertRaises(TypeError):json.dumps({'ticket':obj.consumeTicket})
        result=self.go([dict(Schema='ReceiverConsumeRequest',raw=raw(fixture['request']))])[0]
        self.assertNotIn(ticket,result['Diagnostic']);self.assertIn(ticket,w.encode(obj).decode())
        for body in (b'{"secret":"'+ticket.encode()+b'",',raw(fixture['request'])[:-1]+b',"extra":"'+ticket.encode()+b'"}'):
            try:w.decode('ReceiverConsumeRequest',body)
            except w.WireError:self.assertNotIn(ticket,traceback.format_exc())
            else:self.fail('invalid input accepted')
    def test_json_lexical_boundaries(self):
        bad=[b'1.0',b'1e0',b'NaN',b'Infinity',b'-Infinity',b'9007199254740992',b'-9007199254740992',b'"\xff"',b'"\\ud800"',b'"\\udc00"',b'{"a":0,"\\u0061":1}',b'{} {}',b'\xef\xbb\xbf{}','{} '.encode('utf-16'),b'"unescaped\x00"',b'['*129+b'0'+b']'*129]
        results=self.go([dict(Mode='canonical',raw=x) for x in bad])
        for body,result in zip(bad,results):
            self.assertFalse(result['OK'])
            with self.assertRaises(w.WireError):codec.parse(body)
        good=[b'-0',b'9007199254740991',b'"\\ud83d\\ude00"',raw({'😀':'\u2028\u2029<&/'})]
        results=self.go([dict(Mode='canonical',raw=x) for x in good])
        for body,r in zip(good,results):self.assertTrue(r['OK']);self.assertEqual(w.canonical_json(codec.parse(body)),base64.b64decode(r['Body']))
    def test_programmatic_dto_is_closed_immutable_and_validated(self):
        value=load('examples/objects.json')[0]
        model=w.decode(value['schemaRef'].split('/')[-1],raw(value['value']))
        with self.assertRaises((AttributeError,TypeError)):model.unapproved='bad'
        self.assertFalse(hasattr(model,'unapproved'))
        with self.assertRaises(w.WireError):w.ReceiverTiming(remainingGrantMs=True,remainingProofMs=100,safetyMarginMs=100)
        with self.assertRaises(w.WireError):w.ID(12)
        with self.assertRaises(w.WireError):w.Epoch(True)
        self.assertEqual(codec.decode('ReceiverTiming',b'{"remainingGrantMs":0,"remainingProofMs":0,"safetyMarginMs":100}').remainingGrantMs,0)
    def test_conditional_authorization_and_stream_states(self):
        cases=[]
        for name,value in all_fixtures():
            sp=SCHEMA['$defs'][name]
            if 'allOf'not in sp or not isinstance(value,dict):continue
            for field in value:
                if type(value[field]) in (bool,int) or field in ('productId','previousArtifactHash','state','turnType'):
                    for replacement in (None,False,True,0,1,'UNKNOWN'):
                        candidate=copy.deepcopy(value);candidate[field]=replacement
                        cases.append((name,candidate))
        results=self.go([dict(Schema=n,raw=raw(v)) for n,v in cases])
        for (name,value),result in zip(cases,results):
            oracle=Draft202012Validator({'$defs':SCHEMA['$defs'],'$ref':'#/$defs/'+name})
            valid=oracle.is_valid(value)
            self.assertEqual(result['OK'],valid,(name,result['Error']))
            if valid:w.decode(name,raw(value))
            else:
                with self.assertRaises(w.WireError):w.decode(name,raw(value))
    def test_operation_control_media_limits_and_status_mapping(self):
        fixture=next(r for r in load('examples/receiver-protocol.json') if r['operationId']=='ReceiverConsume')
        op=w.OPERATIONS['ReceiverConsume'];valid=raw(fixture['request'])
        padded=valid+b' '*(op.max_body_bytes-len(valid))
        ctx=dict(role=op.roles[0],target=op.target,method=op.method,route_template=op.path)
        w.decode_request(op.id,padded,**ctx)
        cases=[dict(Mode='request',Operation=op.id,Role=ctx['role'],Target=ctx['target'],Method=ctx['method'],Route=ctx['route_template'],raw=b) for b in (padded,padded+b' ')]
        self.assertEqual([r['OK'] for r in self.go(cases)],[True,False])
        with self.assertRaises(w.WireError):w.decode_request(op.id,padded+b' ',**ctx)
        error={'requestId':'request','code':'GRANT_TICKET_INVALID'}
        self.assertEqual(w.decode_response(op.id,raw(error),status=403).code,'GRANT_TICKET_INVALID')
        with self.assertRaises(w.WireError):w.decode_response(op.id,raw(error),status=409)
        results=self.go([dict(Mode='response',Operation=op.id,Status=status,raw=raw(error)) for status in (403,409)])
        self.assertEqual([r['OK'] for r in results],[True,False])
        for fixture in load('examples/protocol.json')+load('examples/receiver-protocol.json'):
            op=w.OPERATIONS[fixture['operationId']]
            obj=w.decode_response(op.id,raw(fixture['response']),status=op.success_status)
            self.assertEqual(json.loads(w.encode_response(op.id,obj,status=op.success_status)),fixture['response'])
        media=next(r for r in load('examples/receiver-protocol.json') if r['operationId']=='ReceiverMedia')
        mop=w.OPERATIONS['ReceiverMedia'];mbody=raw(media['request'])
        mbody+=b' '*(mop.max_body_bytes-len(mbody))
        mctx=dict(role=mop.roles[0],target=mop.target,method=mop.method,route_template=mop.path)
        w.decode_request(mop.id,mbody,**mctx)
        with self.assertRaises(w.WireError):w.decode_request(mop.id,mbody+b' ',**mctx)
        media_results=self.go([dict(Mode='request',Operation=mop.id,Role=mop.roles[0],Target=mop.target,Method=mop.method,Route=mop.path,raw=b) for b in (mbody,mbody+b' ')])
        self.assertEqual([r['OK'] for r in media_results],[True,False])
        too_large=b' '*(w.codec.MAX_BODY_BYTES+1)
        self.assertFalse(self.go([dict(Schema='ID',raw=too_large)])[0]['OK'])
        with self.assertRaises(w.WireError):w.decode('ID',too_large)
    def test_chinese_answer_text_and_descriptor_hash_negative_cases(self):
        value=next(row['value'] for row in load('examples/objects.json') if row['name']=='AnswerUnit1')
        valid=w.decode('AnswerArtifact',raw(value));w.verify_answer_artifact_hashes(valid)
        rows=[value]
        for field,replacement in [('answerText',value['answerText']+'改。'),('answerTextHash','0'*64),('artifactHash','0'*64)]:
            changed=copy.deepcopy(value);changed[field]=replacement;rows.append(changed)
            dto=w.decode('AnswerArtifact',raw(changed))
            with self.assertRaisesRegex(w.WireError,'ANSWER_CONFLICT'):w.verify_answer_artifact_hashes(dto)
        self.assertEqual([r['OK'] for r in self.go([dict(Mode='artifact',raw=raw(v)) for v in rows])],[True,False,False,False])
    def test_generator_determinism_and_check(self):
        cmd=['python3',str(ROOT/'scripts/durable-live/generate_v2_wire.py')]
        subprocess.run(cmd,check=True,capture_output=True)
        paths=[ROOT/'backend/internal/durablelivev2/wire',ROOT/'astralive_contracts/durable_live_v2']
        def generated():return {str(p):hashlib.sha256(p.read_bytes()).hexdigest() for folder in paths for p in folder.iterdir() if p.suffix in ('.py','.go','.json') and not p.name.endswith('_test.go')}
        first=generated();subprocess.run(cmd,check=True,capture_output=True);self.assertEqual(first,generated())
        subprocess.run(cmd+['--check'],check=True,capture_output=True)
    def test_generator_refuses_drift_and_detects_hand_edits(self):
        import shutil
        with tempfile.TemporaryDirectory(prefix='astralive-wire-drift-') as tmp:
            root=Path(tmp)
            for p in load('manifest.json')['files']:
                (root/p).parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(ROOT/p,root/p)
            (root/'contracts/v0.5/durable-live-2/manifest.json').write_bytes((CONTRACT/'manifest.json').read_bytes())
            shutil.copytree(ROOT/'scripts/durable-live/templates',root/'scripts/durable-live/templates')
            cmd=['python3',str(ROOT/'scripts/durable-live/generate_v2_wire.py'),'--root',str(root)]
            subprocess.run(cmd,check=True,capture_output=True)
            extra=root/'astralive_contracts/durable_live_v2/unmanaged.py';extra.write_text('pass\n')
            rejected=subprocess.run(cmd+['--check'],capture_output=True);self.assertNotEqual(rejected.returncode,0);self.assertIn(b'Unmanaged',rejected.stderr);extra.unlink()
            target=root/'astralive_contracts/durable_live_v2/models.py';target.write_bytes(target.read_bytes()+b'\n# manual drift\n')
            self.assertNotEqual(subprocess.run(cmd+['--check'],capture_output=True).returncode,0)
            before=target.read_bytes()
            for rel in load('manifest.json')['files']:
                source=root/rel;original=source.read_bytes();source.write_bytes(original+b' ')
                rejected=subprocess.run(cmd,capture_output=True)
                self.assertNotEqual(rejected.returncode,0);self.assertIn(b'FROZEN_FILE_DRIFT',rejected.stderr)
                self.assertEqual(target.read_bytes(),before);self.assertEqual(source.read_bytes(),original+b' ')
                source.write_bytes(original)
            manifest=root/'contracts/v0.5/durable-live-2/manifest.json';manifest.write_bytes(manifest.read_bytes()+b' ')
            rejected=subprocess.run(cmd,capture_output=True);self.assertNotEqual(rejected.returncode,0);self.assertIn(b'FROZEN_MANIFEST_DRIFT',rejected.stderr)


if __name__=='__main__':unittest.main()

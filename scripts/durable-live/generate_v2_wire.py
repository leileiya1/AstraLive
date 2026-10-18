#!/usr/bin/env python3
"""Deterministic, offline v2 DTO generation. Never edits a frozen input.

Requires Python >=3.12 stdlib and gofmt from the project's Go toolchain.
"""
import argparse
import copy
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

FROZEN = 'c7fd46209d3cbc6f58541dba8b4e1c85609c823e'
DIGEST = '3c0c317ed00f6fa4d2cf15ef3f61fc002d4bb22bf02d53ee9f1b407458bb28b1'
MANIFEST_HASH = '34931c2f539a4ca13f77e79356baac2d0bb9793c06a14fce3911dcf92979a1ad'
BASE = 'contracts/v0.5/durable-live-2'
GO = 'backend/internal/durablelivev2/wire'
PYTHON = 'astralive_contracts/durable_live_v2'
KEYWORDS = {'$schema','$id','title','description','$defs','$ref','type','properties','required',
            'additionalProperties','anyOf','allOf','if','then','else','const','enum','items',
            'minimum','maximum','minItems','maxItems','uniqueItems','minLength','maxLength',
            'pattern','format','contentEncoding'}

def sha(b): return hashlib.sha256(b).hexdigest()
def canonical(v): return json.dumps(v,sort_keys=True,ensure_ascii=False,separators=(',',':')).encode()
def q(v): return json.dumps(v,ensure_ascii=False)


def verify(root):
    raw=(root/BASE/'manifest.json').read_bytes()
    if sha(raw)!=MANIFEST_HASH: raise ValueError('FROZEN_MANIFEST_DRIFT')
    m=json.loads(raw)
    if len(m['files'])!=22 or m['normativeDigest']!=DIGEST or sha(canonical(m['files']))!=DIGEST:
        raise ValueError('FROZEN_DIGEST_DRIFT')
    for path,expected in m['files'].items():
        if sha((root/path).read_bytes())!=expected: raise ValueError('FROZEN_FILE_DRIFT')
    return m

def supported(s,defs):
    if not isinstance(s,dict) or set(s)-KEYWORDS: raise ValueError('UNSUPPORTED_SCHEMA_KEYWORD')
    if '$ref' in s and (not s['$ref'].startswith('#/$defs/') or s['$ref'].split('/')[-1] not in defs): raise ValueError('UNSUPPORTED_REF')
    if 'type' in s and s['type'] not in ('object','array','string','integer','boolean','null'): raise ValueError('UNSUPPORTED_TYPE')
    if s.get('format') not in (None,'date-time') or s.get('contentEncoding') not in (None,'base64'): raise ValueError('UNSUPPORTED_ANNOTATION')
    if 'anyOf' in s:
        if len(s['anyOf'])!=2 or sum(x.get('type')=='null' for x in s['anyOf'])!=1: raise ValueError('UNSUPPORTED_UNION')
    for key,value in s.items():
        if key in ('properties','$defs'):
            for child in value.values(): supported(child,defs)
        elif key in ('items','if','then','else'): supported(value,defs)
        elif key in ('anyOf','allOf'):
            for child in value:supported(child,defs)

def resolved(defs,s):return resolved(defs,defs[s['$ref'].split('/')[-1]]) if '$ref' in s else s

def name(field):
    value=field[0].upper()+field[1:]
    value=re.sub(r'Ids(?=$|[A-Z])','IDs',value)
    return re.sub(r'Id(?=$|[A-Z])','ID',value)

def go_type(s,owner,field,enums):
    if '$ref' in s:return s['$ref'].split('/')[-1]
    if 'anyOf' in s:return '*'+go_type(next(x for x in s['anyOf'] if x.get('type')!='null'),owner,field,enums)
    if 'enum' in s:
        n=owner+name(field);enums[n]=s['enum'];return n
    t=s.get('type')
    if t=='array':return '[]'+go_type(s['items'],owner,field+'Item',enums)
    if t in ('string','integer','boolean'):return {'string':'string','integer':'int64','boolean':'bool'}[t]
    if isinstance(s.get('const'),str):return 'string'
    if type(s.get('const')) is bool:return 'bool'
    if type(s.get('const')) is int:return 'int64'
    raise ValueError('UNSUPPORTED_GO_FIELD')

def py_type(s):
    if '$ref' in s:return s['$ref'].split('/')[-1]
    if 'anyOf' in s:return py_type(next(x for x in s['anyOf'] if x.get('type')!='null'))+' | None'
    if s.get('type')=='array':return 'tuple['+py_type(s['items'])+', ...]'
    if 'enum' in s:return 'Literal['+', '.join(repr(x) for x in s['enum'])+']'
    if 'const' in s:return 'Literal['+repr(s['const'])+']'
    return {'string':'str','integer':'int','boolean':'bool'}[s['type']]


def outputs(root):
    m=verify(root);s=json.loads((root/BASE/'schema.json').read_bytes());defs=s['$defs']
    if len(defs)!=132:raise ValueError('DEFINITION_COVERAGE_DRIFT')
    supported(s,defs)
    for d in defs.values():
        if d.get("type")=="object" and (d.get("additionalProperties") is not False or set(d.get("required",()))!=set(d.get("properties",{}))):
            raise ValueError("UNSUPPORTED_OPTIONAL_OR_OPEN_OBJECT")
    protocols=[json.loads((root/BASE/f).read_bytes()) for f in ('protocol.json','receiver-protocol.json')]
    if [len(p['operations']) for p in protocols]!=[25,13]:raise ValueError('OPERATION_COVERAGE_DRIFT')
    operations=[]
    for p in protocols:
        for o in p['operations']:
            codes=p.get('httpErrors',p.get('errorCodes'))
            operations.append(dict(id=o['operationId'],method=o['method'],path=o['path'],target=o['target'],roles=o['roles'],request=o['requestSchema'].split('/')[-1],response=o['responseSchema'].split('/')[-1],error=o.get('errorSchema','#/$defs/Error').split('/')[-1],status=o['successStatus'],errors={k:codes[k] for k in o['errorCodes']},limit=p['maxBodyBytes'] if 'maxBodyBytes'in p else (p['maxMediaBodyBytes'] if o['operationId']=='ReceiverMedia' else p['maxControlBodyBytes'])))
    if len({o['id'] for o in operations})!=38:raise ValueError('DUPLICATE_OPERATION')
    original_names=list(defs)
    normalized=copy.deepcopy(defs); helpers={}; inline_paths={}
    def lift(sp, prefix, path):
        if sp.get('type')=='object':
            for field, child in list(sp['properties'].items()):
                sp['properties'][field]=lift(child,prefix+name(field),path+['properties',field])
        elif sp.get('type')=='array':
            child=sp['items']
            if child.get('type')=='object':
                helper=prefix+'Item'
                if helper in defs or helper in helpers:raise ValueError('INLINE_NAME_COLLISION')
                helpers[helper]=lift(child,helper,path+['items']);inline_paths[helper]=path+['items'];sp['items']={'$ref':'#/$defs/'+helper}
            else:sp['items']=lift(child,prefix+'Item',path+['items'])
        elif 'anyOf' in sp:
            for i,child in enumerate(sp['anyOf']):sp['anyOf'][i]=lift(child,prefix,path+['anyOf',i])
        return sp
    for n,d in list(normalized.items()):lift(d,n,['$defs',n])
    normalized.update(helpers);defs=normalized
    header='// Code generated by generate_v2_wire.py; DO NOT EDIT.\n// Source '+FROZEN+' / '+DIGEST+'\n'
    pyheader='# Code generated by generate_v2_wire.py; DO NOT EDIT.\n# Source '+FROZEN+' / '+DIGEST+'\n'
    out={}
    for directory in (GO,PYTHON):out[directory+'/schema.json']=(root/BASE/'schema.json').read_bytes()
    schema_hash=m['files'][BASE+'/schema.json']
    templates=root/'scripts/durable-live/templates'
    go_paths='map[string][]string{'+','.join(q(n)+':{'+','.join(q(x) for x in path)+'}' for n,path in inline_paths.items())+'}'
    out[GO+'/codec_generated.go']=(header+(templates/'v2_codec.go.tmpl').read_text().replace('@SCHEMA_HASH@',schema_hash).replace('@INLINE_PATHS@',go_paths)).encode()
    out[PYTHON+'/codec.py']=(pyheader+(templates/'v2_codec.py.tmpl').read_text().replace('@SCHEMA_HASH@',schema_hash).replace('@INLINE_PATHS@',repr(inline_paths))).encode()
    lines=[header,'package wire','import ("fmt"; "log/slog")',f'const FrozenCommit = {q(FROZEN)}',f'const NormativeDigest = {q(DIGEST)}','const ContractRevision = "durable-live-2"','const ReceiverRevision = "receiver-1"','const SchemaVersion = "0.5"']
    enums={}
    for n,d in defs.items():
        if '$ref' in d:lines.append(f'type {n} = {d["$ref"].split("/")[-1]}');continue
        if d.get('type')=='object':
            lines.append('type '+n+' struct {')
            for f,sp in d['properties'].items():lines.append(name(f)+' '+go_type(sp,n,f,enums)+' `json:"'+f+'"`')
            lines.append('}')
        else:lines.append('type '+n+' '+{'string':'string','integer':'int64'}[d['type']])
        lines += [f'func ({n}) wireMessage() {{}}',f'func (v {n}) LogValue() slog.Value {{ return slog.StringValue(v.String()) }}',f'func ({n}) SchemaName() string {{ return {q(n)} }}',f'func (v {n}) MarshalJSON() ([]byte,error) {{ return marshalNamed({q(n)},v) }}',f'func (v *{n}) UnmarshalJSON(b []byte) error {{ return unmarshalNamed({q(n)},b,v) }}',f'func (v {n}) String() string {{ return {q(n+"{redacted}")} }}',f'func (v {n}) GoString() string {{ return v.String() }}',f'func (v {n}) Format(s fmt.State, verb rune) {{ fmt.Fprint(s,v.String()) }}']
    for n,values in enums.items():
        if not all(type(x) is str for x in values):raise ValueError('UNSUPPORTED_ENUM')
        lines.append('type '+n+' string')
        for value in values:lines.append('const '+n+re.sub('[^A-Za-z0-9]','_',value)+' '+n+' = '+q(value))
    lines.append('var factories = map[string]func() Message {')
    for n in defs:lines.append(q(n)+': func() Message { return new('+n+') },')
    lines.append('}')
    lines.append('func SchemaNames() []string { return []string{'+','.join(q(n) for n in original_names)+'} }')
    for n in defs:lines.append(f'func Decode{n}(raw []byte) (*{n},error) {{ v:=new({n});if err:=unmarshalNamed({q(n)},raw,v);err!=nil{{return nil,err}};return v,nil }}')
    out[GO+'/types_generated.go']='\n'.join(lines).encode()+b'\n'
    lines=[pyheader,'from __future__ import annotations','from dataclasses import dataclass','from typing import Literal','from .codec import WireModel, SecretString, scalar, MODELS',f'FROZEN_COMMIT = {FROZEN!r}',f'NORMATIVE_DIGEST = {DIGEST!r}','CONTRACT_REVISION = "durable-live-2"','RECEIVER_REVISION = "receiver-1"','SCHEMA_VERSION = "0.5"']
    # Primitive classes must be registered before object classes are used.
    for n,d in defs.items():
        if d.get('type') in ('string','integer'):
            base='SecretString' if n=='ReceiverConsumeTicket' else ('str' if d['type']=='string' else 'int')
            lines += [f'class {n}({base}):','    __slots__ = ()',f'    def __new__(cls, value): return scalar({n!r}, value)',f'MODELS[{n!r}] = {n}']
    for n,d in defs.items():
        if '$ref' in d:
            lines += [f'{n} = {d["$ref"].split("/")[-1]}',f'MODELS[{n!r}] = {n}'];continue
        if d.get('type')!='object':continue
        lines += ['@dataclass(frozen=True, slots=True, repr=False)',f'class {n}(WireModel):']
        for f,sp in d['properties'].items():lines.append('    '+f+': '+py_type(sp))
        lines += [f'MODELS[{n!r}] = {n}']
    lines.append('__all__ = '+repr(list(defs)+['FROZEN_COMMIT','NORMATIVE_DIGEST','CONTRACT_REVISION','RECEIVER_REVISION','SCHEMA_VERSION']))
    out[PYTHON+'/models.py']='\n'.join(lines).encode()+b'\n'
    roles=sorted({r for o in operations for r in o['roles']});targets=sorted({o['target'] for o in operations})
    gl=[header,'package wire','type Role string','type Target string','type OperationID string','type Operation struct { ID OperationID; Method,Path string; Target Target; Roles []Role; RequestSchema,ResponseSchema,ErrorSchema string; SuccessStatus,MaxBodyBytes int; ErrorCodes map[string]int }']
    for role in roles:gl.append('const Role'+''.join(x.title() for x in role.split('_'))+' Role = '+q(role))
    for target in targets:gl.append('const Target'+target.title()+' Target = '+q(target))
    for o in operations:gl += ['const Op'+o['id']+' OperationID = '+q(o['id']),'const Path'+o['id']+' = '+q(o['path'])]
    gl.append('var operationTable = map[OperationID]Operation {')
    for o in operations:
        gl.append('Op'+o['id']+': {ID:Op'+o['id']+',Method:'+q(o['method'])+',Path:Path'+o['id']+',Target:Target('+q(o['target'])+'),Roles:[]Role{'+','.join('Role('+q(r)+')' for r in o['roles'])+'},RequestSchema:'+q(o['request'])+',ResponseSchema:'+q(o['response'])+',ErrorSchema:'+q(o['error'])+',SuccessStatus:'+str(o['status'])+',MaxBodyBytes:'+str(o['limit'])+',ErrorCodes:map[string]int{'+','.join(q(k)+':'+str(v) for k,v in o['errors'].items())+'}},')
    gl += ['}', 'func LookupOperation(id OperationID)(Operation,bool) { op,ok:=operationTable[id]; if !ok{return Operation{},false};op.Roles=append([]Role(nil),op.Roles...);codes:=map[string]int{};for k,v:=range op.ErrorCodes{codes[k]=v};op.ErrorCodes=codes;return op,true }','func OperationIDs() []OperationID { return []OperationID{'+','.join('Op'+o['id'] for o in operations)+'} }']
    out[GO+'/operations_generated.go']='\n'.join(gl).encode()+b'\n'
    pl=[pyheader,'from dataclasses import dataclass','from typing import Mapping','from types import MappingProxyType','from . import codec','@dataclass(frozen=True, slots=True)','class Operation:','    id: str','    method: str','    path: str','    target: str','    roles: tuple[str, ...]','    request_schema: str','    response_schema: str','    error_schema: str','    success_status: int','    max_body_bytes: int','    error_codes: Mapping[str, int]','    @property','    def error_statuses(self): return frozenset(self.error_codes.values())']
    for role in roles:pl.append('ROLE_'+role+' = '+repr(role))
    for target in targets:pl.append('TARGET_'+target+' = '+repr(target))
    for o in operations:pl += ['OP_'+o['id'].upper()+' = '+repr(o['id']),'PATH_'+o['id'].upper()+' = '+repr(o['path'])]
    pl.append('OPERATIONS = MappingProxyType({')
    for o in operations:pl.append(repr(o['id'])+': Operation('+','.join(repr(x) for x in [o['id'],o['method'],o['path'],o['target'],tuple(o['roles']),o['request'],o['response'],o['error'],o['status'],o['limit']])+', MappingProxyType('+repr(o['errors'])+')),')
    pl += ['})','codec.OPERATIONS = OPERATIONS']
    pl.append('__all__ = '+repr(['Operation','OPERATIONS']+['ROLE_'+r for r in roles]+['TARGET_'+t for t in targets]+[x for o in operations for x in ('OP_'+o['id'].upper(),'PATH_'+o['id'].upper())]))
    out[PYTHON+'/operations.py']='\n'.join(pl).encode()+b'\n'
    out[PYTHON+'/__init__.py']=(pyheader+'from .models import *\nfrom .operations import *\nfrom .codec import WireError, WireModel, decode, encode, decode_request, decode_response, encode_request, encode_response, verify_answer_artifact_hashes, canonical_json, digest\n').encode()
    for path in list(out):
        if path.endswith('.go'):out[path]=subprocess.run(['gofmt'],input=out[path],capture_output=True,check=True).stdout
    for directory in (GO,PYTHON):
        hashes={p[len(directory)+1:]:sha(b) for p,b in out.items() if p.startswith(directory+'/')}
        out[directory+'/generated-manifest.json']=json.dumps(dict(frozenCommit=FROZEN,normativeDigest=DIGEST,files=hashes),indent=2).encode()+b'\n'
    return out


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--check',action='store_true');parser.add_argument('--root',type=Path,default=Path(__file__).resolve().parents[2]);args=parser.parse_args()
    try:result=outputs(args.root)
    except (OSError,ValueError,KeyError,subprocess.CalledProcessError) as exc:
        print('Generation refused: '+(str(exc) if type(exc) is ValueError else type(exc).__name__),file=sys.stderr);return 1
    for directory in (GO,PYTHON):
        folder=args.root/directory
        if folder.exists():
            for file in folder.iterdir():
                path=str(file.relative_to(args.root))
                if file.suffix in ('.py','.go') and not file.name.endswith('_test.go') and path not in result:
                    print('Unmanaged generated module: '+path,file=sys.stderr);return 1
    different=[p for p,b in result.items() if not (args.root/p).is_file() or (args.root/p).read_bytes()!=b]
    if args.check:
        if different:print('Generated output drift: '+', '.join(different),file=sys.stderr);return 1
    else:
        for p,b in result.items():target=args.root/p;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(b)
    print(('CHECK' if args.check else 'GENERATED')+' 132 definitions / 38 operations; '+DIGEST);return 0
if __name__=='__main__':raise SystemExit(main())

"""Generate the additive OpenAPI specification without touching frozen v1.1 specs."""
import json
from pathlib import Path

def obj(props,required=None):return {'type':'object','additionalProperties':False,'properties':props,'required':required if required is not None else list(props)}
def string(**kw):return {'type':'string',**kw}
def integer(lo=1,hi=None):return {'type':'integer','minimum':lo,**({'maximum':hi} if hi is not None else {})}
def ref(name):return {'$ref':f'#/components/schemas/{name}'}
s={
 'Kind':string(enum=['LLM','TTS','AVATAR','GPU_WORKER','LIVE_PLATFORM']),
 'LLMConfig':obj({'model':string(pattern=r'^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$'),'maxTokens':integer(1,8192),'temperature':{'type':'number','minimum':0,'maximum':2}},['model','maxTokens']),
 'CompatibleLLMConfig':obj({'model':string(),'maxTokens':integer(1,8192),'temperature':{'type':'number','minimum':0,'maximum':2},'endpoint':string(format='uri')},['model','maxTokens','endpoint']),
 'TTSConfig':obj({'voiceId':string(enum=['xiao_ya']),'speed':{'type':'number','minimum':.5,'maximum':2},'modelRef':string(enum=['xiaoya-default'])}),
 'AvatarConfig':obj({'avatarRef':string(),'workerProfileId':string()},['avatarRef']),
 'WorkerConfig':obj({'workerRef':string()}),
 'LiveConfig':obj({'platform':string()}),
 'ProviderConfig':{'oneOf':[ref(n) for n in ['LLMConfig','CompatibleLLMConfig','TTSConfig','AvatarConfig','WorkerConfig','LiveConfig']]},
 'Scope':obj({'tenantId':string(),'userId':string()}),
 'Policy':obj({'maxQueue':integer(1,100),'failurePolicy':string(enum=['STOP'])}),
 'VersionInput':obj({'expectedVersion':integer()}),
 'CredentialInput':obj({'expectedVersion':integer(),'secret':string(minLength=1,maxLength=4096,writeOnly=True)}),
 'Settings':obj({'version':integer(0),'policy':ref('Policy'),'effect':string(enum=['NEXT_SESSION'])}),
 'SettingsInput':obj({'expectedVersion':integer(0),'policy':ref('Policy')}),
 'Me':obj({'identity':ref('Scope'),'contractVersion':string(enum=['0.3.0'])}),
 'Error':obj({'code':string(),'message':string(),'details':obj({}),'requestId':string(),'timestamp':string(format='date-time')}),
}
s['Profile']=obj({'profileId':string(),'kind':ref('Kind'),'name':string(),'provider':string(),'config':ref('ProviderConfig'),'version':integer(),'enabled':{'type':'boolean'},'isDefault':{'type':'boolean'},'credentialConfigured':{'type':'boolean'},'verification':string(enum=['UNTESTED','VERIFIED','FAILED']),'errorCode':string(),'health':string(enum=['UNKNOWN','UP','DOWN']),'updatedAt':string(format='date-time')})
s['CreateProfile']=obj({'kind':ref('Kind'),'name':string(minLength=1,maxLength=128),'provider':string(),'config':ref('ProviderConfig'),'secret':string(minLength=1,maxLength=4096,writeOnly=True)},['kind','name','provider','config'])
s['UpdateProfile']=obj({'expectedVersion':integer(),'name':string(minLength=1,maxLength=128),'config':ref('ProviderConfig')})
s['Binding']=obj({'bindingId':string(),'contractVersion':string(enum=['0.3.0']),'profiles':{'type':'array','items':ref('Profile')},'settings':ref('Settings'),'expiresAt':string(format='date-time')})
paths={}
def operation(path,method,result,body=None,status='200',internal=False,auth='cookie'):
 schema=obj({'code':string(enum=['OK']),'message':string(),'data':result,'requestId':string(),'timestamp':string(format='date-time')})
 op={'operationId':method+'_'+path.replace('/','_').replace('{','').replace('}',''),'security':[{auth:[]}],'responses':{status:{'description':'Success','content':{'application/json':{'schema':schema}}},'default':{'description':'Static redacted error','content':{'application/json':{'schema':ref('Error')}}}}}
 if body:op['requestBody']={'required':True,'content':{'application/json':{'schema':body}}}
 if '{' in path:op['parameters']=[{'name':path.split('{')[1].split('}')[0],'in':'path','required':True,'schema':string()}]
 if not internal and method!='get':op.setdefault('parameters',[]).append({'name':'Origin','in':'header','required':True,'schema':string()})
 paths.setdefault(path,{})[method]=op
base='/api/v0.3/config'
operation(base+'/me','get',ref('Me'))
operation(base+'/profiles','get',{'type':'array','items':ref('Profile')})
operation(base+'/profiles','post',ref('Profile'),ref('CreateProfile'),'201')
operation(base+'/profiles/{profileId}','put',ref('Profile'),ref('UpdateProfile'))
operation(base+'/profiles/{profileId}','delete',obj({}),ref('VersionInput'))
operation(base+'/profiles/{profileId}/credential','put',ref('Profile'),ref('CredentialInput'))
operation(base+'/profiles/{profileId}/credential','delete',ref('Profile'),ref('VersionInput'))
for action in ['test','default','disable']:operation(base+'/profiles/{profileId}/'+action,'post',ref('Profile'),ref('VersionInput'))
operation(base+'/settings','get',ref('Settings'))
operation(base+'/settings','put',ref('Settings'),ref('SettingsInput'))
b='/internal/v0.3'
operation(b+'/config-sessions','post',obj({'token':string(),'expiresInSeconds':integer()}),ref('Scope'),'201',True,'identity')
operation(b+'/config-sessions','delete',obj({}),obj({'token':string()}),internal=True,auth='identity')
operation(b+'/provider-bindings','post',ref('Binding'),ref('Scope'),'201',True,'worker')
operation(b+'/provider-bindings/{bindingId}/resolve','post',obj({'binding':ref('Binding'),'credentials':{'type':'object','additionalProperties':string()}}),ref('Scope'),internal=True,auth='worker')
operation(b+'/provider-bindings/{bindingId}','delete',obj({}),ref('Scope'),internal=True,auth='worker')
operation(b+'/worker-health','post',obj({}),obj({'tenantId':string(),'userId':string(),'profileId':string(),'expectedVersion':integer(),'health':string(enum=['UP','DOWN'])}),internal=True,auth='worker')
doc={'openapi':'3.0.3','info':{'title':'AstraLive User Configuration','version':'0.3.0'},'paths':paths,'components':{'schemas':s,'securitySchemes':{'cookie':{'type':'apiKey','in':'cookie','name':'astralive_config_session'},'identity':{'type':'http','scheme':'bearer'},'worker':{'type':'http','scheme':'bearer'}}}}
Path(__file__).with_name('schema.json').write_text(json.dumps(doc,ensure_ascii=False,indent=2)+'\n')

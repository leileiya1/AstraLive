"""Frozen additive personal-media contract; does not change v1.1 or config 0.3.0."""
import json
import re
from pathlib import Path


def obj(properties, required=None):
    return {'type': 'object', 'additionalProperties': False, 'properties': properties,
            'required': list(properties) if required is None else required}


def text(**kw):
    return {'type': 'string', **kw}


def integer(low=1, high=None):
    return {'type': 'integer', 'minimum': low, **({'maximum': high} if high is not None else {})}


def ref(name):
    return {'$ref': '#/components/schemas/' + name}


def array(name):
    return {'type': 'array', 'items': ref(name)}


ID = text(minLength=1, maxLength=128, pattern=r'^[A-Za-z0-9][A-Za-z0-9_-]*$')
SHA = text(pattern=r'^[a-f0-9]{64}$')
TIME = text(format='date-time')
BOOL = {'type': 'boolean'}
NAME = text(minLength=1, maxLength=128)
PURPOSES = ['AVATAR_PHOTO', 'VOICE_REFERENCE', 'NORMALIZED_PHOTO', 'NORMALIZED_AUDIO', 'AVATAR_PREVIEW', 'VOICE_PREVIEW']
ERRORS = ['NONE', 'INVALID_ARGUMENT', 'UNAUTHORIZED', 'FORBIDDEN', 'RESOURCE_NOT_FOUND',
          'CONFIG_VERSION_CONFLICT', 'ASSET_NOT_READY', 'ASSET_IN_USE', 'ASSET_REJECTED',
          'UPLOAD_EXPIRED', 'UPLOAD_SIZE_MISMATCH', 'UPLOAD_HASH_MISMATCH', 'QUOTA_EXCEEDED',
          'CONSENT_REQUIRED', 'CAPABILITY_UNSUPPORTED', 'PROCESSOR_UNAVAILABLE', 'WORKER_NOT_READY',
          'JOB_CLAIM_EXPIRED', 'JOB_CANCELLED', 'JOB_TIMEOUT', 'BINDING_EXPIRED', 'OUTPUT_INVALID', 'INTERNAL_ERROR',
          'PHOTO_SIZE_INVALID', 'PHOTO_FORMAT_INVALID', 'PHOTO_DIMENSIONS_INVALID', 'PHOTO_DECODE_FAILED',
          'FACE_CHECK_UNAVAILABLE', 'FACE_CHECK_FAILED', 'PHOTO_REQUIRES_ONE_FACE', 'PHOTO_FACE_NOT_FRONTAL',
          'PHOTO_FACE_TOO_SMALL', 'PHOTO_FACE_BLURRED', 'PHOTO_FACE_CROP_CLIPPED',
          'REFERENCE_AUDIO_SIZE_INVALID', 'REFERENCE_TEXT_REQUIRED', 'REFERENCE_AUDIO_FORMAT_INVALID',
          'REFERENCE_AUDIO_STREAMS_INVALID', 'REFERENCE_AUDIO_DURATION_INVALID', 'REFERENCE_AUDIO_RATE_CHANGED',
          'REFERENCE_AUDIO_DECODE_FAILED', 'REFERENCE_AUDIO_TOO_QUIET', 'REFERENCE_AUDIO_CLIPPED', 'PROVIDER_TEST_FAILED']
s = {
    'Scope': obj({'tenantId': text(minLength=1), 'userId': text(minLength=1)}),
    'ErrorCode': text(enum=ERRORS),
    'Error': obj({'code': ref('ErrorCode'), 'message': text(), 'details': obj({}), 'requestId': text(), 'timestamp': TIME}),
    'VersionInput': obj({'expectedVersion': integer()}),
    'ConsentInput': obj({'accepted': text(enum=['PERSONAL_MEDIA_PROCESSING_V1']), 'rightsConfirmed': {'type': 'boolean', 'enum': [True]}}),
    'ConsentReceipt': obj({'policyVersion': text(enum=['PERSONAL_MEDIA_PROCESSING_V1']), 'acceptedAt': TIME}),
    'Asset': obj({'assetId': ID, 'purpose': text(enum=PURPOSES), 'state': text(enum=['STAGED', 'UPLOADED', 'VALIDATING', 'READY', 'REJECTED', 'DELETING', 'DELETED']),
                  'version': integer(), 'byteLength': integer(0, 20971520), 'sha256': SHA, 'mediaType': text(),
                  'preprocessingVersion': text(), 'sourceAssetId': ID, 'errorCode': ref('ErrorCode'), 'createdAt': TIME,
                  'consent': ref('ConsentReceipt')},
                 ['assetId', 'purpose', 'state', 'version', 'byteLength', 'sha256', 'mediaType', 'preprocessingVersion', 'errorCode', 'createdAt', 'consent']),
    'PhotoUpload': obj({'purpose': text(enum=['AVATAR_PHOTO']), 'byteLength': integer(1, 10485760), 'sha256': SHA,
                       'mediaType': text(enum=['image/jpeg', 'image/png', 'image/webp']), 'consent': ref('ConsentInput')}),
    'AudioUpload': obj({'purpose': text(enum=['VOICE_REFERENCE']), 'byteLength': integer(1, 20971520), 'sha256': SHA,
                       'mediaType': text(enum=['audio/wav', 'audio/mpeg', 'audio/ogg', 'audio/webm', 'audio/mp4', 'audio/flac']), 'referenceText': text(minLength=1, maxLength=1000), 'consent': ref('ConsentInput')}),
    'CreateUpload': {'oneOf': [ref('PhotoUpload'), ref('AudioUpload')]},
    'UploadTicket': obj({'uploadId': ID, 'asset': ref('Asset'), 'expiresAt': TIME}),
    'XiaoYaVoiceConfig': obj({'provider': text(enum=['xiaoya']), 'voiceId': text(enum=['xiao_ya']), 'modelRef': text(enum=['xiaoya-default']),
                             'speed': {'type': 'number', 'enum': [1]}, 'volume': {'type': 'number', 'enum': [1]}}),
    'ReferenceVoiceConfig': obj({'provider': text(enum=['cosyvoice']), 'modelRef': ID, 'referenceAssetId': ID,
                                'referenceText': text(minLength=1, maxLength=1000), 'speed': {'type': 'number', 'enum': [1]},
                                'volume': {'type': 'number', 'minimum': 0, 'maximum': 2}}),
    'VoiceConfig': {'oneOf': [ref('XiaoYaVoiceConfig'), ref('ReferenceVoiceConfig')]},
    'AvatarConfig': obj({'provider': text(enum=['soulx_lite']), 'photoAssetId': ID, 'workerProfileId': ID,
                        'modelRef': text(enum=['soulx-flashhead-lite']), 'preprocessingVersion': text(enum=['photo-face512-v1'])}),
    'ProfileState': text(enum=['CREATED', 'VALIDATING', 'PREPARING', 'READY', 'FAILED', 'DISABLED', 'DELETED']),
    'CreateAvatarProfile': obj({'name': NAME, 'config': ref('AvatarConfig')}),
    'UpdateAvatarProfile': obj({'expectedVersion': integer(), 'name': NAME, 'config': ref('AvatarConfig')}),
    'CreateVoiceProfile': obj({'name': NAME, 'config': ref('VoiceConfig')}),
    'UpdateVoiceProfile': obj({'expectedVersion': integer(), 'name': NAME, 'config': ref('VoiceConfig')}),
    'Readiness': obj({'mode': text(enum=['REAL', 'SIMULATION']), 'checkedAt': TIME, 'modelRevision': text(minLength=1, maxLength=128),
                      'preprocessingVersion': text(minLength=1, maxLength=128), 'inputSHA256': SHA, 'cacheId': ID,
                      'workerProfileVersion': integer(), 'warmupFrames': integer(3), 'encoderReady': BOOL}),
    'AvatarProfile': obj({'avatarProfileId': ID, 'name': NAME, 'version': integer(), 'state': ref('ProfileState'), 'enabled': BOOL,
                         'isDefault': BOOL, 'config': ref('AvatarConfig'), 'normalizedPhotoAssetId': ID, 'readiness': ref('Readiness'),
                         'errorCode': ref('ErrorCode'), 'createdAt': TIME, 'updatedAt': TIME},
                        ['avatarProfileId', 'name', 'version', 'state', 'enabled', 'isDefault', 'config', 'errorCode', 'createdAt', 'updatedAt']),
    'VoiceCapabilities': obj({'referenceAudio': BOOL, 'incrementalPCM': BOOL, 'speed': BOOL, 'volume': BOOL}),
    'VoiceProfile': obj({'voiceProfileId': ID, 'name': NAME, 'version': integer(), 'state': ref('ProfileState'), 'enabled': BOOL,
                        'isDefault': BOOL, 'config': ref('VoiceConfig'), 'normalizedAudioAssetId': ID, 'capabilities': ref('VoiceCapabilities'),
                        'errorCode': ref('ErrorCode'), 'createdAt': TIME, 'updatedAt': TIME},
                       ['voiceProfileId', 'name', 'version', 'state', 'enabled', 'isDefault', 'config', 'capabilities', 'errorCode', 'createdAt', 'updatedAt']),
    'JobKind': text(enum=['VALIDATE_PHOTO', 'VALIDATE_AUDIO', 'PREPARE_AVATAR', 'PREVIEW_AVATAR', 'PREVIEW_VOICE']),
    'Job': obj({'jobId': ID, 'kind': ref('JobKind'), 'action': text(enum=['VALIDATE', 'PREPARE', 'PREVIEW']), 'state': text(enum=['QUEUED', 'RUNNING', 'SUCCEEDED', 'FAILED', 'CANCELLED']),
                'attempt': integer(0), 'profileVersion': integer(), 'errorCode': ref('ErrorCode'), 'outputAssetIds': {'type': 'array', 'items': ID},
                'createdAt': TIME, 'expiresAt': TIME}, ['jobId', 'kind', 'action', 'state', 'attempt', 'errorCode', 'outputAssetIds', 'createdAt', 'expiresAt']),
    'AvatarPreviewInput': obj({'expectedVersion': integer(), 'audioAssetId': ID}),
    'VoicePreviewInput': obj({'expectedVersion': integer(), 'text': text(minLength=1, maxLength=200)}),
    'Capabilities': obj({'contractVersion': text(enum=['0.3.1']), 'assetStorage': BOOL, 'photoValidation': BOOL, 'audioValidation': BOOL,
                         'avatarPreparation': BOOL, 'avatarPreview': BOOL, 'voicePreview': BOOL, 'xiaoya': ref('VoiceCapabilities'),
                         'cosyvoice': ref('VoiceCapabilities')}),
    'RevisionRef': obj({'profileId': ID, 'version': integer()}),
    'AssetDescriptor': obj({'assetId': ID, 'purpose': text(enum=PURPOSES), 'sha256': SHA, 'byteLength': integer(1, 20971520),
                            'mediaType': text(), 'preprocessingVersion': text(), 'sourceAssetId': ID},
                           ['assetId', 'purpose', 'sha256', 'byteLength', 'mediaType', 'preprocessingVersion']),
    'CaptureBinding': obj({'scope': ref('Scope'), 'sessionId': ID}),
    'PersonalBinding': obj({'bindingId': ID, 'sessionId': ID, 'contractVersion': text(enum=['0.3.1']),
                           'avatar': ref('RevisionRef'), 'voice': ref('RevisionRef'), 'providerBindingId': ID,
                           'assets': array('AssetDescriptor'), 'expiresAt': TIME}),
    'WorkerSelection': obj({'profileId': ID, 'version': integer(), 'workerRef': ID}),
    'ResolvedPersonalBinding': obj({'binding': ref('PersonalBinding'), 'avatar': ref('AvatarProfile'), 'voice': ref('VoiceProfile'), 'worker': ref('WorkerSelection')}),
    'BindingAccess': obj({'scope': ref('Scope')}),
    'ClaimInput': obj({'scope': ref('Scope'), 'workerRef': ID}),
    'JobClaim': obj({'job': ref('Job'), 'scope': ref('Scope'), 'claimToken': text(minLength=32), 'leaseExpiresAt': TIME,
                    'inputAssets': array('AssetDescriptor'), 'avatar': ref('AvatarProfile'), 'voice': ref('VoiceProfile'),
                    'previewText': text(minLength=1, maxLength=200), 'referenceText': text(minLength=1, maxLength=1000)},
                   ['job', 'scope', 'claimToken', 'leaseExpiresAt', 'inputAssets']),
    'OutputUploadInput': obj({'claimToken': text(minLength=32), 'attempt': integer(), 'purpose': text(enum=PURPOSES[2:]),
                             'byteLength': integer(1, 20971520), 'sha256': SHA, 'mediaType': text(enum=['image/png', 'audio/wav', 'video/mp4'])}),
    'OutputTicket': obj({'uploadId': ID, 'assetId': ID, 'expiresAt': TIME}),
    'ValidatedResult': obj({'kind': text(enum=['VALIDATE_PHOTO', 'VALIDATE_AUDIO']), 'outputAssetId': ID, 'preprocessingVersion': text(enum=['photo-face512-v1', 'reference-pcm16k-v1'])}),
    'PreparedResult': obj({'kind': text(enum=['PREPARE_AVATAR']), 'readiness': ref('Readiness')}),
    'PreviewResult': obj({'kind': text(enum=['PREVIEW_AVATAR', 'PREVIEW_VOICE']), 'outputAssetId': ID}),
    'SuccessResult': obj({'claimToken': text(minLength=32), 'attempt': integer(), 'state': text(enum=['SUCCEEDED']),
                          'result': {'oneOf': [ref('ValidatedResult'), ref('PreparedResult'), ref('PreviewResult')]}}),
    'FailureResult': obj({'claimToken': text(minLength=32), 'attempt': integer(), 'state': text(enum=['FAILED']),
                          'errorCode': text(enum=[e for e in ERRORS if e != 'NONE'])}),
    'JobResultInput': {'oneOf': [ref('SuccessResult'), ref('FailureResult')]},
}
paths = {}


def op(path, method, result=None, body=None, status='200', auth='cookie', binary=False, idempotent=False):
    response = {'description': 'Success'}
    if result is not None:
        response['content'] = {'application/json': {'schema': obj({'code': text(enum=['OK']), 'message': text(), 'data': result, 'requestId': text(), 'timestamp': TIME})}}
    entry = {'operationId': method + '_' + re.sub(r'[/{\}]', '_', path), 'security': [{auth: []}],
             'x-implementation-status': 'CONTRACT_ONLY',
             'responses': {status: response, 'default': {'description': 'Redacted error', 'content': {'application/json': {'schema': ref('Error')}}}}}
    params = [{'name': name, 'in': 'path', 'required': True, 'schema': ID} for name in re.findall(r'\{(.*?)\}', path)]
    if auth == 'cookie' and method != 'get':
        params.append({'name': 'Origin', 'in': 'header', 'required': True, 'schema': text()})
    if auth == 'processor' and (binary or '/outputs' in path):
        params.append({'name': 'X-Job-Claim', 'in': 'header', 'required': True, 'schema': text(minLength=32)})
    if idempotent:
        params.append({'name': 'Idempotency-Key', 'in': 'header', 'required': True, 'schema': ID})
    if params:
        entry['parameters'] = params
    if binary:
        entry['requestBody'] = {'required': True, 'content': {'application/octet-stream': {'schema': text(format='binary')}}}
    elif body:
        entry['requestBody'] = {'required': True, 'content': {'application/json': {'schema': body}}}
    paths.setdefault(path, {})[method] = entry
    return entry


base = '/api/v0.3/config'
op(base + '/personal-capabilities', 'get', ref('Capabilities'))
op(base + '/asset-uploads', 'post', ref('UploadTicket'), ref('CreateUpload'), '201', idempotent=True)
op(base + '/asset-uploads/{uploadId}/content', 'put', binary=True, status='204')
op(base + '/asset-uploads/{uploadId}/complete', 'post', ref('Job'), obj({}), '202')
op(base + '/asset-uploads/{uploadId}', 'delete', status='204')
op(base + '/assets', 'get', array('Asset'))
op(base + '/assets/{assetId}', 'get', ref('Asset'))
op(base + '/assets/{assetId}', 'delete', body=ref('VersionInput'), status='202')
entry = op(base + '/assets/{assetId}/preview', 'get')
entry['parameters'].append({'name': 'Range', 'in': 'header', 'required': False, 'schema': text()})
for code in ['200', '206']:
    entry['responses'][code] = {'description': 'Authenticated normalized image, audio or generated preview bytes',
                               'content': {mime: {'schema': text(format='binary')} for mime in ['image/png', 'audio/wav', 'video/mp4']}}
entry['responses']['416'] = {'description': 'Invalid or multiple range; Content-Range: bytes */length'}
for kind in ['Avatar', 'Voice']:
    resource = base + '/' + kind.lower() + '-profiles'
    param = kind.lower() + 'ProfileId'
    op(resource, 'get', array(kind + 'Profile'))
    op(resource, 'post', ref(kind + 'Profile'), ref('Create' + kind + 'Profile'), '201', idempotent=True)
    op(resource + '/{' + param + '}', 'get', ref(kind + 'Profile'))
    op(resource + '/{' + param + '}', 'put', ref(kind + 'Profile'), ref('Update' + kind + 'Profile'))
    op(resource + '/{' + param + '}', 'delete', body=ref('VersionInput'), status='204')
    for action in ['default', 'disable']:
        op(resource + '/{' + param + '}/' + action, 'post', ref(kind + 'Profile'), ref('VersionInput'))
    op(resource + '/{' + param + '}/prepare', 'post', ref('Job'), ref('VersionInput'), '202', idempotent=True)
    op(resource + '/{' + param + '}/preview', 'post', ref('Job'), ref(kind + 'PreviewInput'), '202', idempotent=True)
op(base + '/personal-jobs/{jobId}', 'get', ref('Job'))
op(base + '/personal-jobs/{jobId}', 'delete', ref('Job'))
b = '/internal/v0.3'
op(b + '/personal-session-bindings', 'post', ref('PersonalBinding'), ref('CaptureBinding'), '201', 'orchestrator', idempotent=True)
op(b + '/personal-session-bindings/{bindingId}', 'delete', body=ref('BindingAccess'), status='204', auth='orchestrator')
op(b + '/personal-session-bindings/{bindingId}/resolve', 'post', ref('ResolvedPersonalBinding'), ref('BindingAccess'), auth='orchestrator')
op(b + '/personal-session-bindings/{bindingId}/renew', 'post', ref('PersonalBinding'), ref('BindingAccess'), auth='orchestrator')
op(b + '/personal-session-bindings/{bindingId}/assets/{assetId}/content', 'get', auth='processor')['responses']['200'] = {
    'description': 'Binding-authorized immutable bytes; digest in X-Asset-SHA256; no filesystem paths',
    'content': {'application/octet-stream': {'schema': text(format='binary')}}}
op(b + '/personal-jobs/{jobId}/claim', 'post', ref('JobClaim'), ref('ClaimInput'), auth='processor')
op(b + '/personal-jobs/{jobId}/inputs/{assetId}/content', 'get', auth='processor')['responses']['200'] = {
    'description': 'Claim-authorized immutable bytes; X-Job-Claim header required',
    'content': {'application/octet-stream': {'schema': text(format='binary')}}}
paths[b + '/personal-jobs/{jobId}/inputs/{assetId}/content']['get']['parameters'].append(
    {'name': 'X-Job-Claim', 'in': 'header', 'required': True, 'schema': text(minLength=32)})
op(b + '/personal-jobs/{jobId}/heartbeat', 'post', ref('JobClaim'), obj({'claimToken': text(minLength=32), 'attempt': integer()}), auth='processor')
op(b + '/personal-jobs/{jobId}/outputs', 'post', ref('OutputTicket'), ref('OutputUploadInput'), '201', 'processor')
op(b + '/personal-output-uploads/{uploadId}/content', 'put', auth='processor', binary=True, status='204')
op(b + '/personal-jobs/{jobId}/result', 'post', ref('Job'), ref('JobResultInput'), auth='processor')
doc = {'openapi': '3.0.3', 'info': {'title': 'AstraLive Personal Avatar, Voice and AssetStorage', 'version': '0.3.1',
       'description': 'Frozen additive contracts. CONTRACT_ONLY paths must not be advertised as deployed handlers. See contracts/PERSONAL-ASSETS-HANDOFF.md.'},
       'paths': paths, 'components': {'schemas': s, 'securitySchemes': {
           'cookie': {'type': 'apiKey', 'in': 'cookie', 'name': 'astralive_config_session'},
           'orchestrator': {'type': 'http', 'scheme': 'bearer', 'description': 'Dedicated trusted control-plane identity, not browser or worker token'},
           'processor': {'type': 'http', 'scheme': 'bearer', 'description': 'Dedicated worker identity restricted to registered workerRef and role'}}}}
Path(__file__).with_name('schema.json').write_text(json.dumps(doc, ensure_ascii=False, indent=2) + '\n')

#!/usr/bin/env python3
"""Independent private CNY coverage evidence oracle; no production imports.

Inputs are actual safe SQL projections, not public DTOs or inferred semantics.
Returned coverage proves only recorded metadata and full server sink consumption.
It does not establish GPU execution, audience sound, human naturalness or Golden.
Timeline hashes are joined to actual SQL observations/receipts, not recomputed
from incomplete safe projections of the original authenticated command.
"""
import hashlib
import json
import re
from decimal import Decimal

MAX_INTEGER = 9007199254740991
HASH = re.compile(r'sha256:[0-9a-f]{64}\Z')
PRODUCT_KEYS = {'productId', 'name', 'description', 'price', 'currency', 'stock', 'sizes'}
TEMPLATES = {
    'price-subject-1': '本商品当前标价是人民币{{price}}元。',
    'price-answer-wording-1': '这款目前价格是人民币{{price}}元。',
}
POLICY_KEYS = {'policyRevision', 'sessionId', 'narrationId', 'runEpoch', 'productId',
               'productSnapshotHash', 'factVersion', 'targets'}
DECISION_KEYS = {'policy', 'interactionTurnId', 'phase', 'answerPreparedCommandId',
                 'answerPreparedObservationHash', 'answerSegmentId', 'answerTextHash',
                 'mappedFactIds', 'completionCommandId', 'completionProofHash',
                 'completedCheckpoint', 'appliedTargetSegmentIds'}
IDENTITY_KEYS = ('sessionId', 'runEpoch', 'timelineEpoch', 'generationId',
                 'segmentId', 'utteranceId', 'lane')


class CoverageAuditError(ValueError):
    def __init__(self, code, status='FAIL'):
        self.code, self.status = code, status
        super().__init__(code)


def require(condition, code):
    if not condition:
        raise CoverageAuditError(code)


def text_hash(text):
    require(type(text) is str, 'CANONICAL_INVALID_TEXT')
    return 'sha256:' + hashlib.sha256(text.encode('utf-8')).hexdigest()


def product_snapshot_hash(snapshot):
    require(type(snapshot) is dict and set(snapshot) == PRODUCT_KEYS and
            all(type(v) is str for v in snapshot.values()), 'CANONICAL_INVALID_PRODUCT_SNAPSHOT')
    # Go durability.Canonical: sorted UTF-8 keys, no Unicode/HTML escaping.
    encoded = json.dumps(snapshot, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode('utf-8')
    return 'sha256:' + hashlib.sha256(encoded).hexdigest()


def integer(value, minimum=1):
    require(type(value) is int and minimum <= value <= MAX_INTEGER, 'CANONICAL_INVALID_INTEGER')
    return value


def unique(rows, key):
    require(type(rows) is list, 'CANONICAL_MISSING_SQL_ARRAY')
    result = {}
    for row in rows:
        require(type(row) is dict and key in row and type(row[key]) is str and row[key], 'CANONICAL_MISSING_SQL_KEY')
        require(row[key] not in result, 'CANONICAL_DUPLICATE_SQL_KEY')
        result[row[key]] = row
    return result


def scope(row, narration, *, camel=False, run=True):
    names = {'session_id':'sessionId', 'tenant_id':'tenantId', 'user_id':'userId'}
    if run:
        names['run_epoch'] = 'runEpoch'
    for source, target in names.items():
        require(row[target if camel else source] == narration[source], 'CANONICAL_FOREIGN_SCOPE')


def observation(rows, command, operation, narration):
    found = [r for r in rows if r['command_id'] == command and r['operation'] == operation]
    require(len(found) == 1, 'CANONICAL_MISSING_OR_DUPLICATE_OBSERVATION')
    row = found[0]
    scope(row, narration)
    ack = row['response_json']
    require(HASH.fullmatch(row['observation_hash'] or '') is not None and
            ack['observationHash'] == row['observation_hash'] and ack['durable'] is True,
            'CANONICAL_OBSERVATION_HASH_OR_DURABILITY')
    require(type(ack['producerIncarnation']) is str and ack['producerIncarnation'], 'CANONICAL_MISSING_PRODUCER')
    integer(ack['receiptSeq'])
    return row, ack


def receipt(rows, command, operation, ack, narration):
    found = [r for r in rows if r['command_id'] == command and r['evidence_type'] == 'timeline_journal'
             and r['evidence_ref'] == operation]
    require(len(found) == 1, 'CANONICAL_MISSING_OR_DUPLICATE_JOURNAL_RECEIPT')
    row = found[0]
    scope(row, narration)
    integer(row['receipt_seq'])
    require(row['receipt_seq'] == ack['receiptSeq'] and row['producer_incarnation'] == ack['producerIncarnation']
            and row['observation_hash'] == ack['observationHash'] and row['state'] == ack['state'],
            'CANONICAL_RECEIPT_ACK_MISMATCH')


def completed_sinks(commit, required):
    require(commit['play_state'] == 'COMPLETED' and commit['installed_at'] and commit['completed_at'],
            'CANONICAL_UNCOMPLETED_ANSWER')
    require(type(required) is list and required and len(required) == len(set(required))
            and all(type(s) is str and s for s in required), 'CANONICAL_INVALID_REQUIRED_SINKS')
    require(commit['required_sinks'] == required and commit['descriptor_json']['requiredSinks'] == required,
            'CANONICAL_REQUIRED_SINK_MISMATCH')
    start, end = integer(commit['start_sample'], 0), integer(commit['end_sample'])
    rate = integer(commit['sample_rate'])
    require(start < end and end-start <= 8*rate, 'CANONICAL_INVALID_ANSWER_INTERVAL')
    seen = set()
    for r in commit['sink_receipts']:
        key = r['sinkId'], r['media']
        require(key not in seen, 'CANONICAL_DUPLICATE_SINK_RECEIPT')
        seen.add(key)
        require(r['identity'] == commit['identity_json'], 'CANONICAL_FOREIGN_SINK_IDENTITY')
        require(r['startSample'] == start and r['endSample'] == end and r['finalMarker'] is True
                and r['evidenceType'] == 'sink_consumed' and type(r['evidenceRef']) is str and r['evidenceRef'],
                'CANONICAL_PARTIAL_OR_UNPROVEN_SINK')
    require(seen == {(sink, media) for sink in required for media in ('audio', 'video')},
            'CANONICAL_MISSING_OR_FOREIGN_SINK')


def checkpoint_matches(p, commit, narration, answer_hash, required):
    identity = commit['identity_json']
    require(p['identity'] == {k:identity[k] for k in IDENTITY_KEYS}, 'CANONICAL_CHECKPOINT_IDENTITY')
    require(p['attemptId'] == commit['attempt_id'] and p['finalMarker'] is True
            and p['evidenceRef'] == commit['command_id']+':SEGMENT_COMPLETED'
            and p['factVersion'] == narration['plan_json']['factVersion'] and p['textHash'] == answer_hash
            and p['requiredSinks'] == required and p['audienceAudible'] is False,
            'CANONICAL_CHECKPOINT_BINDING')
    for name, sample in (('startPosition',commit['start_sample']), ('finalPosition',commit['end_sample'])):
        position = p[name]
        expected = {k:identity[k] for k in ('sessionId','runEpoch','timelineEpoch')}
        expected.update(sampleIndex=sample, sampleRate=commit['sample_rate'], ptsUs=sample*1000000//commit['sample_rate'])
        require(position == expected, 'CANONICAL_CHECKPOINT_POSITION')
    ranges = [{'sinkId':sink, 'audioStart':commit['start_sample'], 'audioEnd':commit['end_sample'],
               'videoStart':commit['start_sample'], 'videoEnd':commit['end_sample']} for sink in required]
    require(p['sinks'] == ranges, 'CANONICAL_CHECKPOINT_SINK_RANGES')


def validated_cny_price_coverage(narration_row, turn_rows, commit_rows, observation_rows,
                                 receipt_rows, answer_prepared_commands, *, product_snapshot):
    """Return only privately recorded and fully proven canonical target coverage.

    Old plans without policy yield {}, never a guessed semantic upgrade. Missing
    evidence, duplicate mappings, private forged fields and incomplete claims
    raise CoverageAuditError with a safe code, never raw record contents.
    """
    try:
        return _coverage(narration_row, turn_rows, commit_rows, observation_rows,
                         receipt_rows, answer_prepared_commands, product_snapshot)
    except CoverageAuditError:
        raise
    except (KeyError, TypeError, ValueError, IndexError, UnicodeError):
        raise CoverageAuditError('CANONICAL_MALFORMED_OR_MISSING_EVIDENCE') from None


def _coverage(narration, turn_rows, commit_rows, observations, receipts, prepared_commands, snapshot):
    plan = narration['plan_json']
    turns = unique(turn_rows, 'turn_id')
    policy = plan.get('_cnyPriceCoveragePolicy')
    decisions = [(row, row['document_json']['_cnyPriceCoverageDecision']) for row in turns.values()
                 if '_cnyPriceCoverageDecision' in row['document_json']]
    if policy is None:
        require(not decisions, 'CANONICAL_ORPHAN_DECISION_WITHOUT_POLICY')
        return {}
    require(set(policy) == POLICY_KEYS and policy['policyRevision'] == 'canonical-cny-price-1', 'CANONICAL_INVALID_POLICY')
    integer(narration['run_epoch'])
    for key in ('session_id', 'narration_id', 'tenant_id', 'user_id'):
        require(type(narration[key]) is str and narration[key], 'CANONICAL_INVALID_OWNER_OR_SCOPE')
    integer(policy['runEpoch'])
    require(plan['sessionId'] == policy['sessionId'] == narration['session_id']
            and plan['narrationId'] == policy['narrationId'] == narration['narration_id']
            and policy['runEpoch'] == narration['run_epoch']
            and plan['productId'] == policy['productId'] == snapshot['productId'], 'CANONICAL_FOREIGN_POLICY')
    version = product_snapshot_hash(snapshot)
    require(Decimal(snapshot['price']).is_finite(), 'CANONICAL_NONFINITE_PRICE')
    require(snapshot['currency'] == 'CNY' and snapshot['price']
            and plan['productSnapshotHash'] == plan['factVersion'] == policy['productSnapshotHash']
            == policy['factVersion'] == version, 'CANONICAL_CAPTURED_PRODUCT_MISMATCH')
    # The public projection may have state changes but cannot alter authored text.
    public = narration['document_json']['plan']
    for key in ('sessionId','narrationId','productId','productSnapshotHash','factVersion','requiredSinks'):
        require(public[key] == plan[key], 'CANONICAL_PUBLIC_PRIVATE_PLAN_MISMATCH')
    targets = policy['targets']
    require(type(targets) is list and len(targets) == 1, 'CANONICAL_DUPLICATE_OR_MISSING_TARGET')
    target = targets[0]
    require(set(target) == {'segmentId','textHash','factId','templateRevision'} and target['factId'] == 'price'
            and target['templateRevision'] in TEMPLATES, 'CANONICAL_INVALID_TEMPLATE')
    resolved = TEMPLATES[target['templateRevision']].replace('{{price}}', snapshot['price'])
    authored = unique(plan['segments'], 'segmentId')
    current = unique(public['segments'], 'segmentId')
    require(target['segmentId'] in authored and target['segmentId'] in current, 'CANONICAL_FOREIGN_TARGET')
    segment = authored[target['segmentId']]
    for s in (segment, current[target['segmentId']]):
        require(s['lane'] == 'NARRATION' and s['factIds'] == ['price'] and s['text'] == resolved
                and s['textHash'] == target['textHash'] == text_hash(resolved), 'CANONICAL_NONEXACT_TARGET_CLAIM')
    require(segment['status'] == 'PENDING', 'CANONICAL_TARGET_NOT_ORIGINALLY_PENDING')
    commits = unique(commit_rows, 'command_id')
    commands = unique(prepared_commands, 'commandId')
    coverage = {}
    for row, decision in decisions:
        require(set(decision).issubset(DECISION_KEYS) and decision['phase'] == 'FULFILLED'
                and decision['policy'] == policy, 'CANONICAL_UNFULFILLED_OR_FOREIGN_DECISION')
        scope(row, narration, run=False)
        require(row['narration_id'] == narration['narration_id'] and row['state'] == 'COMPLETED', 'CANONICAL_FOREIGN_OR_UNFINISHED_TURN')
        turn = row['document_json']
        require(turn['state'] == 'COMPLETED' and turn['interactionTurnId'] == row['turn_id'] == decision['interactionTurnId']
                and turn['capturedProductHash'] == version and turn['mappedNarrationFactIds'] == decision['mappedFactIds'] == ['price'], 'CANONICAL_TURN_MAPPING_MISMATCH')
        answer = turn['answer']
        answer_text = '这款目前价格是人民币'+snapshot['price']+'元。'
        answer_hash = text_hash(answer_text)
        require(answer['segmentId'] == decision['answerSegmentId'] and answer['status'] == 'COMPLETED'
                and answer['lane'] == 'AUDIENCE_ANSWER' and answer['factIds'] == turn['answerFactIds'] == ['price']
                and answer['text'] == turn['answerText'] == answer_text
                and answer['textHash'] == decision['answerTextHash'] == answer_hash, 'CANONICAL_NONEXACT_OR_UNCOMPLETED_ANSWER')
        pc = commands[decision['answerPreparedCommandId']]
        scope(pc, narration, camel=True)
        integer(pc['runEpoch'])
        require(pc['commandType'] == 'START_AUDIENCE_ANSWER' and pc['narrationId'] == narration['narration_id']
                and pc['interactionTurnId'] == row['turn_id'] and pc['answerText'] == answer_text
                and pc['factIds'] == ['price'] and pc['productSnapshotHash'] == version
                and type(pc['traceId']) is str and pc['traceId'], 'CANONICAL_PREPARED_COMMAND_MISMATCH')
        prep, pa = observation(observations, pc['commandId'], 'ANSWER_PREPARED', narration)
        require(pa['state'] == 'ready' and prep['observation_hash'] == decision['answerPreparedObservationHash']
                and prep['preparedProof'] == {'text':answer_text, 'factIds':['price'], 'productSnapshotHash':version}, 'CANONICAL_PREPARED_PROOF_MISMATCH')
        receipt(receipts, pc['commandId'], 'ANSWER_PREPARED', pa, narration)
        commit = commits[decision['completionCommandId']]
        scope(commit, narration)
        identity = commit['identity_json']
        for key in ('runEpoch', 'timelineEpoch', 'generationId'):
            integer(identity[key])
        require(type(identity['utteranceId']) is str and identity['utteranceId'], 'CANONICAL_INVALID_MEDIA_IDENTITY')
        require(identity['sessionId'] == narration['session_id'] and identity['runEpoch'] == narration['run_epoch']
                and identity['segmentId'] == commit['segment_id'] == answer['segmentId'] and identity['lane'] == 'AUDIENCE_ANSWER', 'CANONICAL_FOREIGN_ANSWER_COMMIT')
        desc = commit['descriptor_json']
        require(desc['textHash'] == answer_hash and desc['factIds'] == ['price'] and desc['factVersion'] == version
                and desc['finalMarker'] is True and desc['sampleCount'] == commit['end_sample']-commit['start_sample'], 'CANONICAL_DESCRIPTOR_MISMATCH')
        completed_sinks(commit, plan['requiredSinks'])
        _, installed = observation(observations, commit['command_id'], 'COMMIT_INSTALLED', narration)
        require(installed['state'] == 'committed', 'CANONICAL_UNINSTALLED_ANSWER')
        receipt(receipts, commit['command_id'], 'COMMIT_INSTALLED', installed, narration)
        completed, ca = observation(observations, commit['command_id'], 'SEGMENT_COMPLETED', narration)
        require(ca['state'] == 'completed' and ca['observationHash'] == commit['completion_hash'] == decision['completionProofHash']
                and ca['producerIncarnation'] == installed['producerIncarnation'] == pa['producerIncarnation']
                and ca['receiptSeq'] > installed['receiptSeq'], 'CANONICAL_COMPLETION_PROOF_MISMATCH')
        receipt(receipts, commit['command_id'], 'SEGMENT_COMPLETED', ca, narration)
        checkpoint_matches(decision['completedCheckpoint'], commit, narration, answer_hash, plan['requiredSinks'])
        applied = decision.get('appliedTargetSegmentIds') or []
        require(type(applied) is list and len(applied) == len(set(applied)) and set(applied).issubset({target['segmentId']}), 'CANONICAL_DUPLICATE_OR_FOREIGN_APPLIED_TARGET')
        for sid in applied:
            require(sid not in coverage, 'CANONICAL_DUPLICATE_TARGET_MAPPING')
            require(current[sid]['status'] == 'SATISFIED_BY_ANSWER', 'CANONICAL_UNAPPLIED_TARGET_STATUS')
            require(not any(c['segment_id'] == sid for c in commit_rows), 'CANONICAL_TARGET_ALREADY_COMMITTED')
            coverage[sid] = [row['turn_id']]
    require(current[target['segmentId']]['status'] != 'SATISFIED_BY_ANSWER' or target['segmentId'] in coverage,
            'CANONICAL_SATISFIED_TARGET_WITHOUT_PROOF')
    return coverage

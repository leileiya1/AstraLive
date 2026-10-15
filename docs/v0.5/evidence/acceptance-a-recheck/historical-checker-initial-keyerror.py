#!/usr/bin/env python3
"""Read-only consistency checks for retained source8f Stop component evidence.

No new live/GPU or full artifact PASS is asserted; the old bridge mismatch
and full oracle FAIL are REQUIRED to remain visible.
"""
import argparse
import hashlib
import json
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    relative = Path('docs/v0.5/evidence/integration-f/pose-stop-f-postmerge-1/short-stop-component-4')
    root = args.repo / relative
    files = {name: (root/name).read_bytes() for name in ['media/sql-proof.json', 'result.json', 'independent-full-audit.json']}
    sql = json.loads(files['media/sql-proof.json'])
    run_result = json.loads(files['result.json'])
    audit = json.loads(files['independent-full-audit.json'])
    checks = []

    def check(name, condition):
        checks.append({'name': name, 'pass': bool(condition)})

    session = sql['sessions'][0]
    run = sql['runs'][0]
    narration = sql['narrations'][0]
    doc = narration['document_json']
    check('one_session_ended', len(sql['sessions']) == 1 and session['status'] == 'ENDED')
    check('same_run_sealed', len(sql['runs']) == 1 and run['session_id'] == session['id'] and run['status'] == 'SEALED')
    check('matching_binding_released', sql['bindingRelease'] == [{'released': True, 'sessionId': session['id']}])
    check('narration_stopped_sticky_barrier', narration['state'] == doc['state'] == 'STOPPED' and doc['stopBarrier'] is True)
    check('positive_control_cleanup_receipt_retained', any(r['state'] == 'completed' and r['evidence_type'] == 'control_cleanup' for r in sql['receipts']))
    completed = [row for row in sql['commits'] if row['play_state'] == 'COMPLETED']
    tails = [row for row in sql['commits'] if row['play_state'] != 'COMPLETED']
    check('six_completed_commits_with_proof_hash', len(completed) == 6 and all(row['completion_hash'] for row in completed))
    check('one_unknown_tail_without_completion_hash', len(tails) == 1 and tails[0]['play_state'] == 'UNKNOWN' and tails[0]['completion_hash'] is None)
    check('unknown_tail_excluded_from_semantic_cursor', all(row['segment_id'] not in doc['cursor']['completedSegmentIds'] for row in tails))
    check('same_session_run_media', all(row['session_id'] == session['id'] and row['run_epoch'] == run['run_epoch'] for row in sql['commits']))
    mismatches = []
    for row in completed:
        for segment in sql['segments']:
            if segment['segment_id'] == row['segment_id'] and segment['document_json'].get('lane') == 'RESUME_BRIDGE':
                mismatches.append({'segmentId': segment['segment_id'], 'descriptorFactIds': row['descriptor_json']['factIds'],
                                   'sqlFactIds': segment['fact_ids'], 'sameProductVersion': row['descriptor_json']['factVersion'] == segment['product_version']})
    check('historical_bridge_null_mismatch_not_hidden', len(mismatches) >= 1 and all(x['descriptorFactIds'] == [] and x['sqlFactIds'] is None and x['sameProductVersion'] for x in mismatches))
    check('historical_full_artifact_audit_still_fail', audit['status'] == 'FAIL')
    check('historical_real_source_not_reassigned', run_result['source'] == '8f04a7567db2710547da2b313e027d1c76eed02e')
    check('input_bytes_unchanged', all((root/name).read_bytes() == raw for name, raw in files.items()))
    result = {'status': 'PASS' if all(x['pass'] for x in checks) else 'FAIL',
              'scope': 'historical SQL consistency ONLY; no new native execution, no proof of live no-replay or physical audibility',
              'historicalSource': run_result['source'], 'checks': checks, 'retainedBridgeMismatches': mismatches,
              'inputs': {str(relative/name): hashlib.sha256(raw).hexdigest() for name, raw in files.items()}}
    args.output.write_text(json.dumps(result, indent=2)+'\n')
    print(json.dumps({'status': result['status'], 'checks': len(checks), 'failed': [x['name'] for x in checks if not x['pass']]}))
    return int(result['status'] != 'PASS')


if __name__ == '__main__':
    raise SystemExit(main())

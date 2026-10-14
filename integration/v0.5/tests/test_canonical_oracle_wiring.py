"""F main-oracle wiring tests; synthetic SQL inputs are not live acceptance."""
import copy
import unittest

from test_canonical_coverage_audit import fixture
from test_real_golden_audit import audit


class CanonicalOracleWiringTests(unittest.TestCase):
    def case(self):
        args, snapshot = fixture()
        narration, turns, commits, observations, receipts, commands = args
        sql = {'observations':observations, 'receipts':receipts,
               'answerPreparedCommands':commands,
               'productSnapshots':[{**{k:narration[k] for k in
                   ('session_id','narration_id','run_epoch','tenant_id','user_id')},
                   'productSnapshot':snapshot}]}
        return sql, narration, turns, commits

    def test_original_sql_proof_authorizes_next_segment_without_substring(self):
        sql, n, turns, commits = self.case()
        row = turns[0]
        turn = row['document_json']
        question = '多少钱？'
        row.update(question=question, question_hash=audit.sha(question.encode()), source_ids=['comment'])
        turn.update(question=question, questionHash=row['question_hash'], sourceIds=['comment'])
        plan = n['document_json']['plan']
        plan['segments'].append({'segmentId':'next','beatId':'next-beat','status':'COMPLETED'})
        answer = commits[0]
        commits.append({'command_id':'next-command','segment_id':'next', 'attempt_id':'next-attempt', 'start_sample':16000,
                        'end_sample':32000, 'identity_json':{'lane':'NARRATION'}})
        refs = {'attempt':{'identity':{'interactionTurnId':'turn','lane':'AUDIENCE_ANSWER','beatId':'beat'}},
                'next-attempt':{'identity':{'beatId':'next-beat'}}}
        self.assertNotIn(plan['segments'][0]['text'], turn['answerText'])
        with self.assertRaises(audit.AuditFailure) as caught:
            audit.selected_turns(turns, commits, refs, plan, False)
        self.assertEqual(caught.exception.code, 'ANSWER_RESUMED_WRONG_NEXT_SEGMENT')
        coverage = audit.canonical_coverage_from_sql(sql, n, turns, commits)
        _, satisfied = audit.selected_turns(turns, commits, refs, plan, False, coverage)
        self.assertEqual(satisfied, {'target':['turn']})

    def test_missing_projection_keeps_not_verifiable(self):
        sql, n, turns, commits = self.case()
        del sql['answerPreparedCommands']
        with self.assertRaises(audit.AuditFailure) as caught:
            audit.canonical_coverage_from_sql(sql, n, turns, commits)
        self.assertEqual(caught.exception.status, 'NOT_VERIFIABLE')

    def test_duplicate_or_foreign_product_does_not_authorize_coverage(self):
        for mutation in ('duplicate', 'foreign'):
            sql, n, turns, commits = self.case()
            if mutation == 'duplicate':
                sql['productSnapshots'].append(copy.deepcopy(sql['productSnapshots'][0]))
            else:
                sql['productSnapshots'][0]['user_id'] = 'foreign'
            with self.assertRaises(audit.AuditFailure):
                audit.canonical_coverage_from_sql(sql, n, turns, commits)

    def test_changed_prepared_sql_is_rejected_by_main_oracle(self):
        sql, n, turns, commits = self.case()
        sql['observations'][0]['preparedProof']['text'] += '额外承诺。'
        with self.assertRaises(audit.AuditFailure) as caught:
            audit.canonical_coverage_from_sql(sql, n, turns, commits)
        self.assertEqual(caught.exception.code, 'CANONICAL_PREPARED_PROOF_MISMATCH')

    def test_old_record_has_no_semantic_upgrade_or_new_projection_requirement(self):
        _, n, turns, commits = self.case()
        n['plan_json'].pop('_cnyPriceCoveragePolicy')
        turns[0]['document_json'].pop('_cnyPriceCoverageDecision')
        self.assertEqual(audit.canonical_coverage_from_sql({}, n, turns, commits), {})


if __name__ == '__main__':
    unittest.main()

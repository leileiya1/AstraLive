"""Agent4 mapping/transport tests; no media or production enrollment."""
import copy
import json
import unittest

from astralive_contracts import durable_live_v2 as dto
from astralive_contracts.durable_live_v2.codec import SecretString
from runtime.app.receiver1.wire import GuardianWire
from runtime.app.receiver1.transport import Credential, TransportFailure
from tests.test_durable_live_v2_wire import all_fixtures, load, raw


class ReceiverWireTests(unittest.TestCase):
    def setUp(self): self.wire = GuardianWire()

    def test_all_official_messages_and_traces(self):
        for schema, value in all_fixtures():
            with self.subTest(schema=schema):
                got = self.wire.decode(schema, raw(value))
                self.wire.validate(schema, got)
                self.assertEqual(self.wire.canonical(got), dto.encode(dto.decode(schema, raw(value))))

    def test_thirteen_golden_vectors(self):
        vectors = load("examples/hash-vectors.json")
        self.assertEqual(len(vectors), 13)
        for v in vectors:
            self.assertEqual(self.wire.canonical(v['value']).decode(), v['canonicalUtf8'])
            self.assertEqual(self.wire.digest(v['value']), v['sha256'])

    def test_closed_objects_and_hostile_bytes(self):
        value = next(v for s,v in all_fixtures() if s == 'CommitReceiverConsumeRequest')
        data = raw(value)
        for bad in (data[:-1]+b',"requestId":"duplicate"}', data[:-1]+b',"role":"CONTROL"}',
                    data.replace(b'"receiver-1"', b'"receiver-0"'), b'\xff', b' '*262145):
            with self.assertRaises(dto.WireError): self.wire.decode('CommitReceiverConsumeRequest', bad)
        for field in value:
            missing = dict(value); missing.pop(field)
            with self.assertRaises(dto.WireError): self.wire.validate('CommitReceiverConsumeRequest', missing)
        value['expectedRegistrationRevision'] = True
        with self.assertRaises(dto.WireError): self.wire.validate('CommitReceiverConsumeRequest', value)

    def test_secret_remains_opaque_through_guardian_deepcopy(self):
        value = next(v for s,v in all_fixtures() if s == 'ReceiverConsumeRequest')
        got = self.wire.decode('ReceiverConsumeRequest', raw(value))
        ticket = got['consumeTicket']
        self.assertIsInstance(ticket, SecretString)
        self.assertIs(copy.deepcopy(ticket), ticket)
        self.assertNotIn(value['consumeTicket'], repr(copy.deepcopy(got)))
        with self.assertRaises(TypeError): json.dumps(got)
        self.assertEqual(self.wire.canonical(copy.deepcopy(got)), dto.canonical_json(value))

    def test_artifact_hash_tampering(self):
        a = copy.deepcopy(next(v for s,v in all_fixtures() if s == 'AnswerArtifact'))
        self.wire.validate_artifact(a)
        a['answerText'] += '篡改'
        with self.assertRaises(dto.WireError): self.wire.validate_artifact(a)

    def test_roles_routes_operation_and_versions(self):
        for msg in load('examples/receiver-protocol.json'):
            op = dto.OPERATIONS[msg['operationId']]
            good = dict(role=op.roles[0], target=op.target, method=op.method, route_template=op.path)
            self.wire.request(op.id, raw(msg['request']), **good)
            for key,value in [('role','UNTRUSTED'),('target','PUBLIC'),('method','GET'),('route_template','/guardian/v1/bind')]:
                bad = dict(good); bad[key] = value
                with self.assertRaises(dto.WireError): self.wire.request(op.id, raw(msg['request']), **bad)

    def test_process_credential_redaction(self):
        self.assertEqual(str(Credential(b'A'*43)), 'Credential(<redacted>)')
        for value in (b'', b'\r'*43, 'A'*43):
            with self.assertRaises(TransportFailure): Credential(value)


if __name__ == '__main__': unittest.main()

class TransportResourceTests(unittest.IsolatedAsyncioTestCase):
    async def test_cancelled_rpc_retains_bounded_admission_until_worker_finishes(self):
        import asyncio
        import threading
        from runtime.app.receiver1.transport import AuthorityTransport, ProcessIdentity
        class BlockingFixture(AuthorityTransport):
            def _call(self, operation, document, **kwargs):
                release.wait(1)
                return {'fixture': True}
        release = threading.Event()
        client = BlockingFixture('/unused', ProcessIdentity(1, 1, 'fixture'), Credential(b'A'*43))
        tasks = [asyncio.create_task(client.query_receiver_authority({})) for _ in range(16)]
        try:
            await asyncio.sleep(0.02)
            with self.assertRaises(TransportFailure): await client.query_receiver_authority({})
            tasks[0].cancel()
            await asyncio.gather(tasks[0], return_exceptions=True)
            with self.assertRaises(TransportFailure): await client.query_receiver_authority({})
        finally:
            release.set()
            await asyncio.gather(*tasks, return_exceptions=True)
        for _ in range(100):
            if client._pending._value == 16: break
            await asyncio.sleep(0.001)
        self.assertEqual(client._pending._value, 16)
        self.assertEqual(await client.query_receiver_authority({}), {'fixture': True})

"""Agent2's A/B/C minimal repros, verbatim actor operations; synthetic only."""
from tests.test_receiver_contracts import ReceiverContractTests, rx
x = ReceiverContractTests(); x.setUp()
q, _ = x.ready()
x.g.stop(x.p.control, rx.wire(x.c, runId=x.j.command['runId']))
ack = x.consume(q)
x.r.accept_ack(q, ack)
print('A:', ack['consumeAuthorized'], x.g.barrier_state, x.r.tts_starts)

x = ReceiverContractTests(); x.setUp()
q, _ = x.ready(); ack = x.consume(q); x.r.accept_ack(q, ack)
e = ack['consumption']['binding']['executionId']
original = x.b.snapshot
fired = []
def stop_after_read(peer, request):
    out = original(peer, request)
    if not fired:
        fired.append(True)
        x.p.stop()
    return out
x.b.snapshot = stop_after_read
print('B:', x.r.push_media(e, q['references']['permitId']))
print('B state:', x.g.barrier_state, x.g.media_count)

x = ReceiverContractTests(); x.setUp(); q, _ = x.ready()
original = x.b.snapshot; calls = []
def stop_at_last_query(peer, request):
    out = original(peer, request); calls.append(True)
    if len(calls) == 3:
        x.p.stop()
    return out
x.b.snapshot = stop_at_last_query
ack = x.consume(q)
print('C:', ack['consumeAuthorized'], x.g.barrier_state, len(x.g.local),
      x.b.registration['state'], len(x.b.latches))

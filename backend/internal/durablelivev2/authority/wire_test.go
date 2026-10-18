package authority

import (
	"strings"
	"testing"

	"astralive/backend/internal/durablelivev2/wire"
)

func peerFor(op wire.OperationID, role string) wire.RequestContext {
	v, _ := wire.LookupOperation(op)
	return wire.RequestContext{Role: wire.Role(role), Target: v.Target, Method: v.Method, RouteTemplate: v.Path}
}
func TestOfficialWireAdapterConsumptionAndStrictAdmission(t *testing.T) {
	f := newFixture(t, true)
	f.ready()
	peer := peerFor(wire.OpCommitReceiverConsume, f.guardian.Role)
	for _, raw := range [][]byte{append([]byte(`{"requestId":"duplicate",`), canon(f.consumeQ)[1:]...), []byte(strings.Replace(string(canon(f.consumeQ)), `"expectedRegistrationRevision":1`, `"expectedRegistrationRevision":1.0`, 1))} {
		if _, e := f.s.Handle(f.ctx, f.guardian, wire.OpCommitReceiverConsume, peer, raw); e == nil {
			t.Fatal("strict raw admission accepted")
		}
	}
	wrong := peer
	wrong.Role = wire.RoleControl
	if _, e := f.s.Handle(f.ctx, f.guardian, wire.OpCommitReceiverConsume, wrong, canon(f.consumeQ)); e == nil {
		t.Fatal("role escalation")
	}
	wrong = peer
	wrong.RouteTemplate = wire.PathQueryReceiverAuthority
	if _, e := f.s.Handle(f.ctx, f.guardian, wire.OpCommitReceiverConsume, wrong, canon(f.consumeQ)); e == nil {
		t.Fatal("route mismatch")
	}
	first, e := f.s.Handle(f.ctx, f.guardian, wire.OpCommitReceiverConsume, peer, canon(f.consumeQ))
	if e != nil {
		t.Fatal(e)
	}
	v, ok := first.(*wire.CommitReceiverConsumeResponse)
	if !ok || !v.ConsumeAuthorized || v.Consumption == nil {
		t.Fatal("wrong official DTO result")
	}
	again, e := f.s.Handle(f.ctx, f.guardian, wire.OpCommitReceiverConsume, peer, canon(f.consumeQ))
	if e != nil {
		t.Fatal(e)
	}
	v = again.(*wire.CommitReceiverConsumeResponse)
	if v.ConsumeAuthorized || v.Consumption != nil || v.ConsumeTiming != nil {
		t.Fatal("replayed typed authorization")
	}
	if f.count("dl05_receiver_consumptions") != 1 {
		t.Fatal("duplicate latch")
	}
}
func TestOfficialWireMetadataRolesAndHashes(t *testing.T) {
	f := newFixture(t, true)
	f.ready()
	q := f.q(Document{"commandId": f.cmd["commandId"], "runEpoch": int64(1)})
	if _, e := f.s.Handle(f.ctx, f.registrar, wire.OpQueryExecutionStatus, peerFor(wire.OpQueryExecutionStatus, f.registrar.Role), canon(q)); e == nil {
		t.Fatal("invented Registrar query permission")
	}
	a := clone(f.unit)
	a["answerTextHash"] = hash("wrong")
	if OfficialValidate("AnswerArtifact", a) == nil {
		t.Fatal("unverified artifact hash")
	}
	closed := New(f.s.DB)
	if _, e := closed.Call(f.ctx, f.runtime, "JournalPrepareAnswer", f.prepareQ); e == nil {
		t.Fatal("default verifier bypass")
	}
}

func TestRegistrarHistoricalReadbackAfterLostRegistrationACK(t *testing.T) {
	f := newFixture(t, true)
	reg, e := f.s.ReadRegistration(f.ctx, f.registrar, text(f.binding, "bootstrapId"))
	if e != nil || hash(reg) != hash(f.registration) {
		t.Fatal("lost ACK readback", e)
	}
	if _, e = f.s.ReadRegistration(f.ctx, f.guardian, text(f.binding, "bootstrapId")); e == nil {
		t.Fatal("Guardian repository privilege")
	}
	bad := f.registrar
	bad.Owner = "other-owner"
	if _, e = f.s.ReadRegistration(f.ctx, bad, text(f.binding, "bootstrapId")); e == nil {
		t.Fatal("cross-owner registration")
	}
	f.stop()
	reg, e = f.s.ReadRegistration(f.ctx, f.registrar, text(f.binding, "bootstrapId"))
	if e != nil || reg["state"] != "REVOKED" {
		t.Fatal(reg, e)
	}
	if strings.Contains(string(canon(reg)), "consumeTicket") {
		t.Fatal("readback capability")
	}
}

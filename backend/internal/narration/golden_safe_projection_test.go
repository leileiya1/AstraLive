package narration_test

import (
	"astralive/backend/internal/durability"
	"encoding/json"
	"strings"
	"testing"
)

// Actual PostgreSQL query execution and selective projection privacy. This
// fixture does not deliver the deliberately edited outbox command to Runtime.
func TestPostgresGoldenSafeProjection(t *testing.T) {
	ctx, p, _, c := setup(t)
	d, err := c.Start(ctx, "s", "trace", plan())
	if err != nil {
		t.Fatal(err)
	}
	queries := goldenProofQueries()
	for name, query := range queries {
		var raw []byte
		if err := p.QueryRow(ctx, query).Scan(&raw); err != nil {
			t.Fatalf("%s: %v", name, err)
		}
		var rows []map[string]json.RawMessage
		if err := json.Unmarshal(raw, &rows); err != nil {
			t.Fatalf("%s: %v", name, err)
		}
	}
	var raw []byte
	if err := p.QueryRow(ctx, queries["productSnapshots"]).Scan(&raw); err != nil {
		t.Fatal(err)
	}
	var snapshots []struct {
		NarrationID     string            `json:"narration_id"`
		TenantID        string            `json:"tenant_id"`
		UserID          string            `json:"user_id"`
		ProductSnapshot map[string]string `json:"productSnapshot"`
	}
	if err := json.Unmarshal(raw, &snapshots); err != nil {
		t.Fatal(err)
	}
	if len(snapshots) != 1 {
		t.Fatal("expected one owned snapshot")
	}
	s := snapshots[0]
	if s.NarrationID != d.Plan.ID || s.TenantID != "tenant" || s.UserID != "user" || len(s.ProductSnapshot) != 7 {
		t.Fatal("snapshot scope or projection mismatch")
	}
	encoded, err := json.Marshal(s.ProductSnapshot)
	if err != nil {
		t.Fatal(err)
	}
	hash, err := durability.Hash(encoded)
	if err != nil || hash != d.Plan.ProductHash {
		t.Fatal("snapshot differs from controller capture", err)
	}
	const sentinel = "synthetic-projection-secret-never-export"
	_, err = p.Exec(ctx, `UPDATE v05_outbox SET command_type='START_AUDIENCE_ANSWER',payload_envelope=jsonb_build_object('narrationId',$1::text,'bindingToken',$2::text,'payload',jsonb_build_object('interactionTurnId','turn-fixture','answerText','投影测试','factIds',jsonb_build_array('price'),'productSnapshotHash',$3::text,'providerCredential',$2::text)) WHERE session_id='s'`, d.Plan.ID, sentinel, hash)
	if err != nil {
		t.Fatal(err)
	}
	if err := p.QueryRow(ctx, queries["answerPreparedCommands"]).Scan(&raw); err != nil {
		t.Fatal(err)
	}
	if strings.Contains(string(raw), sentinel) || strings.Contains(string(raw), "bindingToken") || strings.Contains(string(raw), "providerCredential") || strings.Contains(string(raw), "payload") {
		t.Fatal("unselected payload leaked")
	}
	var commands []map[string]any
	if err := json.Unmarshal(raw, &commands); err != nil {
		t.Fatal(err)
	}
	if len(commands) != 1 || commands[0]["narrationId"] != d.Plan.ID || commands[0]["answerText"] != "投影测试" || commands[0]["productSnapshotHash"] != hash || commands[0]["tenantId"] != "tenant" || commands[0]["userId"] != "user" {
		t.Fatal("prepared command safe fields missing")
	}
	// A foreign owner cannot be exported as this narration's captured product.
	if _, err := p.Exec(ctx, `INSERT INTO config_principals VALUES('foreign','user'); UPDATE resource_owners SET tenant_id='foreign' WHERE kind='product' AND resource_id='p'`); err != nil {
		t.Fatal(err)
	}
	if err := p.QueryRow(ctx, queries["productSnapshots"]).Scan(&raw); err != nil {
		t.Fatal(err)
	}
	if string(raw) != "[]" {
		t.Fatal("foreign product projected")
	}
}

// F-owned offline evidence queries. No binding, vault, credentials or raw payload.
func goldenProofQueries() map[string]string {
	return map[string]string{
		"sessions":               `SELECT COALESCE(jsonb_agg(to_jsonb(s)),'[]') FROM live_sessions s`,
		"narrations":             `SELECT COALESCE(jsonb_agg(to_jsonb(n)),'[]') FROM v05_narrations n`,
		"segments":               `SELECT COALESCE(jsonb_agg(to_jsonb(s)),'[]') FROM v05_segments s`,
		"attempts":               `SELECT COALESCE(jsonb_agg(to_jsonb(a)),'[]') FROM v05_segment_attempts a`,
		"turns":                  `SELECT COALESCE(jsonb_agg(to_jsonb(t)),'[]') FROM v05_interaction_turns t`,
		"commits":                `SELECT COALESCE(jsonb_agg(to_jsonb(c)),'[]') FROM v05_timeline_commits c`,
		"receipts":               `SELECT COALESCE(jsonb_agg(to_jsonb(r)),'[]') FROM v05_receipts r`,
		"runs":                   `SELECT COALESCE(jsonb_agg(to_jsonb(r)),'[]') FROM v05_session_runs r`,
		"commandIdentities":      `SELECT COALESCE(jsonb_agg(jsonb_build_object('commandId',command_id,'sessionId',session_id,'runEpoch',run_epoch,'traceId',trace_id,'commandType',command_type,'narrationId',payload_envelope->'narrationId','segmentId',payload_envelope->'segmentId','lane',payload_envelope->'lane','timelineEpoch',payload_envelope->'timelineEpoch','beatId',payload_envelope->'payload'->'beatId','interactionTurnId',payload_envelope->'payload'->'interactionTurnId','attemptId',payload_envelope->'payload'->'attemptId','utteranceId',payload_envelope->'payload'->'utteranceId')),'[]') FROM v05_outbox WHERE command_type='COMMIT_SEGMENT'`,
		"answerPreparedCommands": `SELECT COALESCE(jsonb_agg(jsonb_build_object('commandId',command_id,'sessionId',session_id,'runEpoch',run_epoch,'traceId',trace_id,'commandType',command_type,'tenantId',tenant_id,'userId',user_id,'narrationId',payload_envelope->'narrationId','interactionTurnId',payload_envelope->'payload'->'interactionTurnId','answerText',payload_envelope->'payload'->'answerText','factIds',payload_envelope->'payload'->'factIds','productSnapshotHash',payload_envelope->'payload'->'productSnapshotHash')),'[]') FROM v05_outbox WHERE command_type='START_AUDIENCE_ANSWER'`,
		"productSnapshots":       `SELECT COALESCE(jsonb_agg(jsonb_build_object('narration_id',n.narration_id,'session_id',n.session_id,'run_epoch',n.run_epoch,'tenant_id',n.tenant_id,'user_id',n.user_id,'productSnapshot',jsonb_build_object('productId',p.id,'name',p.name,'description',p.description,'price',p.price::text,'currency',p.currency,'stock',p.stock::text,'sizes',array_to_string(p.sizes,'、')))),'[]') FROM v05_narrations n JOIN products p ON p.id=n.plan_json->>'productId' JOIN resource_owners o ON o.kind='product' AND o.resource_id=p.id AND o.tenant_id=n.tenant_id AND o.user_id=n.user_id`,
		"observations":           `SELECT COALESCE(jsonb_agg(jsonb_build_object('command_id',command_id,'operation',operation,'observation_hash',observation_hash,'response_json',response_json,'session_id',session_id,'run_epoch',run_epoch,'tenant_id',tenant_id,'user_id',user_id,'preparedProof',CASE WHEN operation='ANSWER_PREPARED' THEN jsonb_build_object('text',proof_json->'text','factIds',proof_json->'factIds','productSnapshotHash',proof_json->'productSnapshotHash') ELSE NULL END)),'[]') FROM v05_timeline_observations`,
		"bindingRelease":         `SELECT COALESCE(jsonb_agg(jsonb_build_object('sessionId',session_id,'released',released_at IS NOT NULL)),'[]') FROM session_provider_bindings`,
	}
}

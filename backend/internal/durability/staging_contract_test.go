package durability_test

import (
	"astralive/backend/internal/durability"
	"encoding/json"
	"os"
	"testing"
)

func TestStagingCanonicalGoldenVectors(t *testing.T) {
	raw, e := os.ReadFile("../../../docs/v0.5/staging-canonical-vectors.json")
	if e != nil {
		t.Fatal(e)
	}
	var vectors []struct {
		Projection json.RawMessage `json:"projection"`
		Canonical  string          `json:"canonical"`
		Hash       string          `json:"sha256"`
	}
	if e = json.Unmarshal(raw, &vectors); e != nil {
		t.Fatal(e)
	}
	for _, v := range vectors {
		canonical, e := durability.Canonical(v.Projection)
		if e != nil || string(canonical) != v.Canonical {
			t.Fatal(e, string(canonical), v.Canonical)
		}
		hash, e := durability.Hash(v.Projection)
		if e != nil || hash != v.Hash {
			t.Fatal(e, hash, v.Hash)
		}
	}
}

func TestStagingInstalledObservationHash(t *testing.T) {
	ctx, p, s := pg(t)
	r := seedNarration(t, ctx, p, s)
	c := mediaCommand(t, ctx, p, s, r, "seg1", "a1", 0)
	acceptStart(t, ctx, s, c, r.Token)
	_, generation, e := s.StartMedia(ctx, "s", c.CommandID, "runtime", 0)
	if e != nil {
		t.Fatal(e)
	}
	descriptor := map[string]any{"sampleCount": 640, "contentHash": "fixture-pcm-hash", "finalMarker": true, "requiredSinks": []string{"preview"}, "utteranceId": "useg1", "textHash": "text1", "factVersion": "facts1"}
	record(t, ctx, s, c, "SEGMENT_READY", map[string]any{"attemptId": "a1", "generationId": generation, "descriptor": descriptor})
	identity := durability.TimelineIdentity{SessionID: "s", RunEpoch: 1, TimelineEpoch: 1, GenerationID: generation, SegmentID: "seg1", UtteranceID: "useg1", Lane: "NARRATION"}
	commit := map[string]any{"identity": identity, "attemptId": "a1", "descriptor": descriptor, "start": 0, "end": 640, "command": c, "consumed": map[string]any{}, "completed": false, "completion_proof": nil}
	record(t, ctx, s, c, "COMMIT_INTENT", map[string]any{"commit": commit, "revision": 0})
	proof, _ := json.Marshal(map[string]any{"commit": commit})
	packet := durability.TimelineRecord{Operation: "COMMIT_INSTALLED", Command: c, Proof: proof, Producer: "runtime"}
	response, e := s.RecordTimeline(ctx, packet)
	if e != nil {
		t.Fatal(e)
	}
	var ack struct {
		Hash     string `json:"observationHash"`
		Producer string `json:"producerIncarnation"`
	}
	if e = json.Unmarshal(response, &ack); e != nil {
		t.Fatal(e)
	}
	raw, _ := json.Marshal(packet)
	expected, e := durability.TimelineHash(raw)
	if e != nil || ack.Hash != expected || ack.Producer != "runtime" {
		t.Fatal(e, ack.Hash, expected)
	}
	var stored string
	var saved []byte
	if e = p.QueryRow(ctx, `SELECT observation_hash,response_json FROM v05_timeline_observations WHERE command_id=$1 AND operation='COMMIT_INSTALLED'`, c.CommandID).Scan(&stored, &saved); e != nil {
		t.Fatal(e)
	}
	if stored != expected || !equalJSONTest(response, saved) {
		t.Fatal("ACK != authoritative stored observation", stored, expected)
	}
	duplicate, e := s.RecordTimeline(ctx, packet)
	if e != nil || !equalJSONTest(duplicate, response) {
		t.Fatal("duplicate changed ACK", e)
	}
}

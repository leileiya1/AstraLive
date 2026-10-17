// Trusted fixture timing/binding validator; NOT a production authorization service.
package main

import (
	"bytes"
	"encoding/json"
	"fmt"
	"os"
	"reflect"
	"time"
)

type row = map[string]any

func str(r row, k string) string { return r[k].(string) }
func at(r row, k string) time.Time {
	t, e := time.Parse(time.RFC3339Nano, str(r, k))
	if e != nil {
		panic(e)
	}
	return t
}
func need(ok bool, why string) {
	if !ok {
		panic(why)
	}
}
func main() {
	raw, e := os.ReadFile(os.Args[1])
	if e != nil {
		panic(e)
	}
	var trace struct {
		Grant            row   `json:"grant"`
		Consumption      row   `json:"consumption"`
		Observations     []row `json:"observations"`
		Permits          []row `json:"permits"`
		Handoffs         []row `json:"handoffs"`
		GlobalStartCount int   `json:"globalStartCount"`
		UnitGrantCount   int   `json:"unitGrantCount"`
	}
	d := json.NewDecoder(bytes.NewReader(raw))
	d.UseNumber()
	if e = d.Decode(&trace); e != nil {
		panic(e)
	}
	g, b := trace.Grant, trace.Consumption
	issued, consumed, deadline := at(g, "issuedAt"), at(b, "consumedAt"), at(g, "expiresAt")
	need(!consumed.Before(issued) && consumed.Before(deadline), "GRANT_EXPIRED")
	need(str(g, "authorizationScope") == "UNIT_START_ONCE", "wrong scope")
	need(g["grantId"] == b["grantId"], "grant identity")
	keys := []string{"tenantId", "ownerId", "runId", "commandId", "attemptId", "sessionId", "runEpoch", "producerIncarnation", "answerId", "artifactId", "artifactHash", "generationId"}
	for _, key := range keys {
		if value, ok := g[key]; ok {
			need(reflect.DeepEqual(value, b[key]), "grant binding")
		}
	}
	observations, permits := map[string]row{}, map[string]row{}
	for _, o := range trace.Observations {
		id := str(o, "observationId")
		need(observations[id] == nil, "duplicate observation")
		observations[id] = o
	}
	for _, p := range trace.Permits {
		id := str(p, "permitId")
		need(permits[id] == nil, "duplicate permit")
		permits[id] = p
	}
	first := observations[str(g, "factObservationId")]
	check := func(p row, t time.Time) row {
		o := observations[str(p, "factObservationId")]
		for _, r := range []row{p, o} {
			for _, key := range keys {
				need(reflect.DeepEqual(r[key], b[key]), "renewed identity mismatch")
			}
		}
		need(p["guardianIncarnation"] == b["guardianIncarnation"], "guardian restart")
		need(!t.Before(at(p, "issuedAt")) && t.Before(at(p, "expiresAt")), "permit expired")
		need(at(p, "expiresAt").Sub(at(p, "issuedAt")) <= time.Second, "unbounded permit")
		need(!t.Before(at(o, "verifiedAt")) && t.Before(at(o, "validUntil")), "FACT_EXPIRED")
		need(at(o, "validUntil").Sub(at(o, "verifiedAt")) <= 2*time.Second, "unbounded observation")
		for _, key := range []string{"productSnapshotVersion", "factSetHash"} {
			need(reflect.DeepEqual(o[key], first[key]), "facts changed")
		}
		return o
	}
	check(permits[str(g, "permitId")], consumed)
	previous := consumed
	for _, h := range trace.Handoffs {
		t := at(h, "at")
		need(!t.Before(previous) && h["executionId"] == b["executionId"], "execution changed")
		o := check(permits[str(h, "permitId")], t)
		need(o["observationId"] == h["factObservationId"], "observation mismatch")
		previous = t
	}
	need(trace.GlobalStartCount == 1 && trace.UnitGrantCount == 1, "repeated authorization")
	result := map[string]int64{"handoffs": int64(len(trace.Handoffs)), "lastOffsetMs": previous.Sub(issued).Milliseconds(), "initialConsumeWindowMs": deadline.Sub(issued).Milliseconds(), "globalStartCount": 1, "unitGrantCount": 1}
	if e = json.NewEncoder(os.Stdout).Encode(result); e != nil {
		panic(fmt.Sprint(e))
	}
}

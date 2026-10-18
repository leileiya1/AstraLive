package wire

import (
	"bytes"
	"encoding/json"
	"fmt"
	"log/slog"
	"strings"
	"testing"
)

func TestRequiredNullClearsAndFailedDecodeIsAtomic(t *testing.T) {
	h := Hash(strings.Repeat("a", 64))
	rev := Revision(1)
	v := JournalStartRequest{AnswerArtifactHash: &h, ExpectedAnswerRevision: &rev}
	old := v
	if json.Unmarshal([]byte(`{}`), &v) == nil {
		t.Fatal("missing fields accepted")
	}
	if v.AnswerArtifactHash != old.AnswerArtifactHash {
		t.Fatal("failed decode mutated target")
	}
	// Nullable presence belongs to the object: null cannot stand in for required
	// nonnullable scalar, even though encoding/json's default decoder permits it.
	var id ID
	if json.Unmarshal([]byte(`null`), &id) == nil {
		t.Fatal("null ID accepted")
	}
	if json.Unmarshal([]byte(`"id"`), &id) != nil || string(id) != "id" {
		t.Fatal("valid scalar rejected")
	}
}
func TestSecretDiagnostics(t *testing.T) {
	ticket := ReceiverConsumeTicket(strings.Repeat("A", 43))
	v := ReceiverConsumeRequest{ConsumeTicket: ticket}
	for _, out := range []string{fmt.Sprintf("%v", v), fmt.Sprintf("%+v", v), fmt.Sprintf("%#v", v), fmt.Sprintf("%q", v), fmt.Sprintf("%v", ticket), fmt.Sprintf("%#v", &ticket)} {
		if strings.Contains(out, string(ticket)) {
			t.Fatal("secret in diagnostics")
		}
	}
}
func TestOperationDescriptorsAreCopies(t *testing.T) {
	op, _ := LookupOperation(OpReceiverConsume)
	op.Roles[0] = "INVALID"
	op.ErrorCodes["FORBIDDEN"] = 200
	next, _ := LookupOperation(OpReceiverConsume)
	if next.Roles[0] == "INVALID" || next.ErrorCodes["FORBIDDEN"] == 200 {
		t.Fatal("mutable descriptor leaked")
	}
	if len(SchemaNames()) != 132 || len(OperationIDs()) != 38 {
		t.Fatal("coverage")
	}
}
func TestMalformedEscapesAndLexemes(t *testing.T) {
	for _, raw := range []string{`"\ud800"`, `"\udc00"`, `"\ud800x"`, `"\ud800\u0041"`, `1e0`, `1.0`, `NaN`, `9007199254740992`, `{} {}`, `{"a":1,"\u0061":2}`} {
		if _, e := CanonicalJSON([]byte(raw)); e == nil {
			t.Fatal("accepted invalid JSON domain")
		}
	}
	b, e := CanonicalJSON([]byte(`"\ud83d\ude00"`))
	if e != nil || string(b) != `"😀"` {
		t.Fatal("valid surrogate pair rejected")
	}
}

func TestStructuredLogsRedact(t *testing.T) {
	var b bytes.Buffer
	logger := slog.New(slog.NewJSONHandler(&b, nil))
	ticket := ReceiverConsumeTicket(strings.Repeat("B", 43))
	logger.Info("wire", "ticket", ticket, "message", ReceiverConsumeRequest{ConsumeTicket: ticket})
	if strings.Contains(b.String(), string(ticket)) {
		t.Fatal("slog leaked secret")
	}
}

func TestNullableZeroAndReaderBounds(t *testing.T) {
	receipt := ID("receipt")
	value := ReceiverConsumptionSummary{ReceiptID: &receipt}
	if err := json.Unmarshal([]byte(`{"state":"UNCONSUMED","receiptId":null}`), &value); err != nil {
		t.Fatal(err)
	}
	if value.ReceiptID != nil {
		t.Fatal("null retained old pointer")
	}
	b, err := json.Marshal(value)
	if err != nil || !bytes.Contains(b, []byte(`"receiptId":null`)) {
		t.Fatal("required null omitted")
	}
	ctx := RequestContext{Role: RoleRegisteredRuntime, Target: TargetGuardian, Method: "POST", RouteTemplate: PathReceiverConsume}
	if _, err := ReadRequest(OpReceiverConsume, ctx, strings.NewReader(strings.Repeat(" ", ControlBodyBytes+1))); err == nil || err.Error() != "BODY_TOO_LARGE" {
		t.Fatal("unbounded reader")
	}
	var nilMessage *ReceiverTiming
	if _, err := Encode(nilMessage); err == nil {
		t.Fatal("typed nil accepted")
	}
}

type forbiddenReader struct{}

func (forbiddenReader) Read([]byte) (int, error) { panic("read before metadata validation") }
func TestReaderRejectsWrongEndpointBeforeRead(t *testing.T) {
	if _, err := ReadRequest(OpReceiverConsume, RequestContext{}, forbiddenReader{}); err == nil {
		t.Fatal("invalid metadata accepted")
	}
}

type forgedMessage struct{ ReceiverTiming }

func (forgedMessage) SchemaName() string { return "not-a-frozen-schema" }
func TestEncodeRejectsForeignEmbeddedMessage(t *testing.T) {
	if _, err := Encode(forgedMessage{}); err == nil {
		t.Fatal("foreign embedded message accepted")
	}
}

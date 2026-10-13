package narration

// Private Go-owned metadata in existing JSON columns, never public DTO input.
// It is authored once before substitution; loading an old plan never upgrades it.
import (
	"context"
	"encoding/json"
	"reflect"
	"strings"

	"astralive/backend/internal/durability"
	"github.com/jackc/pgx/v5"
)

const canonicalPricePolicyKey = "_cnyPriceCoveragePolicy"
const canonicalPriceDecisionKey = "_cnyPriceCoverageDecision"
const canonicalPricePolicyRevision = "canonical-cny-price-1"

var canonicalPriceTemplateAllowlist = map[string]string{
	"本商品当前标价是人民币{{price}}元。": "price-subject-1",
	"这款目前价格是人民币{{price}}元。":  "price-answer-wording-1",
}

type canonicalPriceTarget struct {
	SegmentID        string `json:"segmentId"`
	TextHash         string `json:"textHash"`
	FactID           string `json:"factId"`
	TemplateRevision string `json:"templateRevision"`
}
type canonicalPricePolicy struct {
	Revision       string                 `json:"policyRevision"`
	SessionID      string                 `json:"sessionId"`
	NarrationID    string                 `json:"narrationId"`
	RunEpoch       int64                  `json:"runEpoch"`
	ProductID      string                 `json:"productId"`
	ProductHash    string                 `json:"productSnapshotHash"`
	ProductVersion string                 `json:"factVersion"`
	Targets        []canonicalPriceTarget `json:"targets"`
}
type canonicalPriceDecision struct {
	Policy                  canonicalPricePolicy `json:"policy"`
	TurnID                  string               `json:"interactionTurnId"`
	Phase                   string               `json:"phase"`
	PreparedCommandID       string               `json:"answerPreparedCommandId"`
	PreparedObservationHash string               `json:"answerPreparedObservationHash"`
	AnswerSegmentID         string               `json:"answerSegmentId"`
	AnswerTextHash          string               `json:"answerTextHash"`
	MappedFacts             []string             `json:"mappedFactIds"`
	CompletionCommandID     string               `json:"completionCommandId,omitempty"`
	CompletionProofHash     string               `json:"completionProofHash,omitempty"`
	CompletedCheckpoint     *Checkpoint          `json:"completedCheckpoint,omitempty"`
	AppliedTargets          []string             `json:"appliedTargetSegmentIds,omitempty"`
}

func singletonPrice(facts []string) bool { return len(facts) == 1 && facts[0] == "price" }

// Returned keys are exact resolved text; no whitespace, subject, numeric or
// semantic fuzziness, and no annotation can turn a custom sentence into policy.
func canonicalPriceTemplates(beats []BeatInput, facts map[string]string) map[string]string {
	out := map[string]string{}
	if facts["currency"] != "CNY" || facts["price"] == "" {
		return out
	}
	for _, beat := range beats {
		for _, stmt := range beat.Statements {
			if revision, ok := canonicalPriceTemplateAllowlist[stmt.Text]; ok && singletonPrice(stmt.FactIDs) {
				out[strings.ReplaceAll(stmt.Text, "{{price}}", facts["price"])] = revision
			}
		}
	}
	return out
}
func marshalCanonicalPlan(p Plan, run int64, enabled bool, templates map[string]string) ([]byte, error) {
	raw, err := json.Marshal(p)
	if err != nil {
		return nil, err
	}
	policy := canonicalPricePolicy{Revision: canonicalPricePolicyRevision, SessionID: p.SessionID, NarrationID: p.ID, RunEpoch: run, ProductID: p.ProductID, ProductHash: p.ProductHash, ProductVersion: p.ProductVersion}
	if enabled {
		for _, s := range p.Segments {
			if revision, ok := templates[s.Text]; ok && singletonPrice(s.FactIDs) && s.Lane == "NARRATION" && s.TextHash == Hash(s.Text) {
				policy.Targets = append(policy.Targets, canonicalPriceTarget{s.ID, s.TextHash, "price", revision})
			}
		}
	}
	if len(policy.Targets) == 0 {
		return raw, nil
	}
	if len(policy.Targets) != 1 {
		return nil, ErrConflict
	}
	var value map[string]json.RawMessage
	if err = json.Unmarshal(raw, &value); err != nil {
		return nil, err
	}
	value[canonicalPricePolicyKey], err = json.Marshal(policy)
	if err != nil {
		return nil, err
	}
	return json.Marshal(value)
}
func (c *Controller) canonicalPolicy(ctx context.Context, tx pgx.Tx, d Document) (*canonicalPricePolicy, error) {
	var raw []byte
	err := tx.QueryRow(ctx, `SELECT plan_json->'_cnyPriceCoveragePolicy' FROM v05_narrations WHERE narration_id=$1 AND session_id=$2 AND run_epoch=$3`, d.Plan.ID, d.Plan.SessionID, d.RunEpoch).Scan(&raw)
	if err != nil {
		return nil, err
	}
	if len(raw) == 0 || string(raw) == "null" {
		return nil, nil
	}
	var p canonicalPricePolicy
	if json.Unmarshal(raw, &p) != nil || p.Revision != canonicalPricePolicyRevision || p.SessionID != d.Plan.SessionID || p.NarrationID != d.Plan.ID || p.RunEpoch != d.RunEpoch || p.ProductID != d.Plan.ProductID || p.ProductHash != d.Plan.ProductHash || p.ProductVersion != d.Plan.ProductVersion || len(p.Targets) != 1 {
		return nil, ErrConflict
	}
	t := p.Targets[0]
	validTemplate := false
	for _, rev := range canonicalPriceTemplateAllowlist {
		validTemplate = validTemplate || t.TemplateRevision == rev
	}
	if !validTemplate || t.FactID != "price" {
		return nil, ErrConflict
	}
	found := false
	for _, s := range d.Plan.Segments {
		if s.ID == t.SegmentID {
			found = s.TextHash == t.TextHash && Hash(s.Text) == t.TextHash && singletonPrice(s.FactIDs) && s.Lane == "NARRATION"
		}
	}
	if !found {
		return nil, ErrConflict
	}
	return &p, nil
}
func (c *Controller) recordCanonicalPrepared(ctx context.Context, tx pgx.Tx, d Document, command durability.Command) error {
	p, err := c.canonicalPolicy(ctx, tx, d)
	if err != nil || p == nil {
		return err
	}
	if d.Turn == nil || d.Turn.Answer == nil || !singletonPrice(d.Turn.MappedNarrationFacts) || !singletonPrice(d.Turn.Answer.FactIDs) {
		return nil
	}
	run, err := c.Store.Current(ctx, tx, d.Plan.SessionID, false)
	if err != nil {
		return err
	}
	captured, err := c.capturedStaging(ctx, tx, run)
	if err != nil {
		return err
	}
	if !captured.Enabled {
		return ErrConflict
	}
	_, hash, facts, err := c.product(ctx, tx, d.Plan.SessionID)
	if err != nil {
		return err
	}
	text, ids := factAnswerForSpeech(d.Turn.Question, facts, true)
	if hash != p.ProductHash || facts["currency"] != "CNY" || !singletonPrice(ids) || text != d.Turn.Answer.Text || d.Turn.ProductHash != p.ProductHash {
		return ErrProduct
	}
	decision := canonicalPriceDecision{Policy: *p, TurnID: d.Turn.ID, Phase: "PREPARED", PreparedCommandID: command.CommandID, AnswerSegmentID: d.Turn.Answer.ID, AnswerTextHash: d.Turn.Answer.TextHash, MappedFacts: []string{"price"}}
	err = tx.QueryRow(ctx, `SELECT observation_hash FROM v05_receipts WHERE command_id=$1 AND session_id=$2 AND run_epoch=$3 AND evidence_type='timeline_journal' AND evidence_ref='ANSWER_PREPARED' ORDER BY receipt_seq DESC LIMIT 1`, command.CommandID, d.Plan.SessionID, d.RunEpoch).Scan(&decision.PreparedObservationHash)
	if err != nil || decision.PreparedObservationHash == "" {
		return ErrConflict
	}
	return c.writeCanonicalDecision(ctx, tx, d, decision, true)
}
func (c *Controller) writeCanonicalDecision(ctx context.Context, tx pgx.Tx, d Document, decision canonicalPriceDecision, prepared bool) error {
	raw, err := json.Marshal(decision)
	if err != nil {
		return err
	}
	var previous []byte
	err = tx.QueryRow(ctx, `SELECT t.document_json->'_cnyPriceCoverageDecision' FROM v05_interaction_turns t JOIN v05_narrations n ON n.narration_id=t.narration_id AND n.session_id=t.session_id AND n.tenant_id=t.tenant_id AND n.user_id=t.user_id WHERE t.turn_id=$1 AND n.narration_id=$2 AND n.session_id=$3 AND n.run_epoch=$4 FOR UPDATE OF t`, decision.TurnID, d.Plan.ID, d.Plan.SessionID, d.RunEpoch).Scan(&previous)
	if err != nil {
		return err
	}
	if len(previous) > 0 && string(previous) != "null" {
		var prior canonicalPriceDecision
		if json.Unmarshal(previous, &prior) != nil {
			return ErrConflict
		}
		if reflect.DeepEqual(prior, decision) {
			return nil
		}
		if prepared || prior.Phase != "PREPARED" || decision.Phase != "FULFILLED" {
			return ErrConflict
		}
		base := decision
		base.Phase = "PREPARED"
		base.CompletionCommandID = ""
		base.CompletionProofHash = ""
		base.CompletedCheckpoint = nil
		base.AppliedTargets = nil
		if !reflect.DeepEqual(prior, base) {
			return ErrConflict
		}
	} else if !prepared {
		return ErrConflict
	}
	tag, err := tx.Exec(ctx, `UPDATE v05_interaction_turns t SET document_json=jsonb_set(t.document_json,'{_cnyPriceCoverageDecision}',$5::jsonb) FROM v05_narrations n WHERE t.turn_id=$1 AND t.narration_id=n.narration_id AND t.session_id=n.session_id AND t.tenant_id=n.tenant_id AND t.user_id=n.user_id AND n.narration_id=$2 AND n.session_id=$3 AND n.run_epoch=$4`, decision.TurnID, d.Plan.ID, d.Plan.SessionID, d.RunEpoch, raw)
	if err != nil {
		return err
	}
	if tag.RowsAffected() != 1 {
		return ErrConflict
	}
	return nil
}
func (c *Controller) canonicalAnswerCoverage(ctx context.Context, tx pgx.Tx, d Document, command durability.Command, p Checkpoint) (*canonicalPriceDecision, map[string]string, error) {
	if d.Turn == nil || d.Turn.Answer == nil {
		return nil, nil, nil
	}
	if err := d.ValidateProof(*d.Turn.Answer, p); err != nil {
		return nil, nil, err
	}
	policy, err := c.canonicalPolicy(ctx, tx, d)
	if err != nil || policy == nil {
		return nil, nil, err
	}
	if d.Turn == nil || d.Turn.Answer == nil || !singletonPrice(d.Turn.MappedNarrationFacts) {
		return nil, nil, nil
	}
	if err = c.fresh(ctx, tx, d); err != nil {
		return nil, nil, err
	}
	var raw []byte
	err = tx.QueryRow(ctx, `SELECT document_json->'_cnyPriceCoverageDecision' FROM v05_interaction_turns WHERE turn_id=$1 AND narration_id=$2 AND session_id=$3`, d.Turn.ID, d.Plan.ID, d.Plan.SessionID).Scan(&raw)
	if err != nil {
		return nil, nil, err
	}
	if len(raw) == 0 || string(raw) == "null" {
		return nil, nil, nil
	}
	var decision canonicalPriceDecision
	if json.Unmarshal(raw, &decision) != nil || !reflect.DeepEqual(decision.Policy, *policy) || decision.TurnID != d.Turn.ID || decision.Phase != "PREPARED" || decision.PreparedCommandID == "" || decision.PreparedObservationHash == "" || decision.AnswerSegmentID != d.Turn.Answer.ID || decision.AnswerTextHash != d.Turn.Answer.TextHash || !singletonPrice(decision.MappedFacts) || !singletonPrice(d.Turn.Answer.FactIDs) || d.Turn.ProductHash != policy.ProductHash || d.Turn.Answer.TextHash != Hash(d.Turn.Answer.Text) {
		return nil, nil, ErrConflict
	}
	// Rebind recorded approval to the actual immutable original command and A
	// observation. A merely nonempty private reference is never authority.
	var prepared bool
	err = tx.QueryRow(ctx, `SELECT EXISTS(
 SELECT 1 FROM v05_timeline_observations obs JOIN v05_outbox o USING(command_id)
 JOIN v05_narrations n ON n.session_id=o.session_id AND n.run_epoch=o.run_epoch
 AND n.narration_id=o.payload_envelope->>'narrationId'
 WHERE o.command_id=$1 AND o.session_id=$2 AND o.run_epoch=$3 AND n.narration_id=$4
 AND o.tenant_id=n.tenant_id AND o.user_id=n.user_id
 AND obs.session_id=n.session_id AND obs.run_epoch=n.run_epoch AND obs.tenant_id=n.tenant_id AND obs.user_id=n.user_id
 AND obs.operation='ANSWER_PREPARED' AND obs.observation_hash=$5
 AND o.command_type='START_AUDIENCE_ANSWER'
 AND o.payload_envelope->'payload'->>'interactionTurnId'=$6
 AND o.payload_envelope->'payload'->>'answerText'=$7
 AND o.payload_envelope->'payload'->'factIds'='["price"]'::jsonb
 AND obs.proof_json->>'text'=$7 AND obs.proof_json->>'productSnapshotHash'=$8)`, decision.PreparedCommandID, d.Plan.SessionID, d.RunEpoch, d.Plan.ID, decision.PreparedObservationHash, d.Turn.ID, d.Turn.Answer.Text, policy.ProductHash).Scan(&prepared)
	if err != nil {
		return nil, nil, err
	}
	if !prepared {
		return nil, nil, ErrConflict
	}
	run, err := c.Store.Current(ctx, tx, d.Plan.SessionID, false)
	if err != nil {
		return nil, nil, err
	}
	captured, err := c.capturedStaging(ctx, tx, run)
	if err != nil {
		return nil, nil, err
	}
	if !captured.Enabled {
		return nil, nil, ErrConflict
	}
	_, _, facts, err := c.product(ctx, tx, d.Plan.SessionID)
	if err != nil {
		return nil, nil, err
	}
	text, ids := factAnswerForSpeech(d.Turn.Question, facts, true)
	if facts["currency"] != "CNY" || !singletonPrice(ids) || text != d.Turn.Answer.Text {
		return nil, nil, ErrProduct
	}
	coverage := map[string]string{}
	for _, target := range policy.Targets {
		for _, s := range d.Plan.Segments {
			if s.ID == target.SegmentID && s.Status == "PENDING" && s.Ordinal >= d.Cursor.NextOrdinal {
				coverage[s.ID] = target.TextHash
				decision.AppliedTargets = append(decision.AppliedTargets, s.ID)
			}
		}
	}
	decision.Phase = "FULFILLED"
	decision.CompletionCommandID = command.CommandID
	// A stores its exact canonical TimelineHash before invoking C projection.
	// Preserve that authoritative hash domain instead of hashing just the proof.
	err = tx.QueryRow(ctx, `SELECT completion_hash FROM v05_timeline_commits WHERE command_id=$1 AND session_id=$2 AND run_epoch=$3 AND play_state='COMPLETED'`, command.CommandID, d.Plan.SessionID, d.RunEpoch).Scan(&decision.CompletionProofHash)
	if err != nil || decision.CompletionProofHash == "" {
		return nil, nil, ErrConflict
	}
	decision.CompletedCheckpoint = &p
	return &decision, coverage, nil
}

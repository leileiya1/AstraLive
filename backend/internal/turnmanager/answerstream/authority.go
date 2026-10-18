package answerstream

import (
	domain "astralive/backend/internal/contentplan/answerstream"
	"astralive/backend/internal/durablelivev2/authority"
	"astralive/backend/internal/durablelivev2/wire"
	"astralive/backend/internal/ids"
	"context"
	"encoding/json"
	"errors"
	"sync"
	"time"
)

// AuthorityHandle has the exact Agent2 typed seam; it defines no new wire DTO.
// Production composition passes Store itself. Tests may wrap Store.Handle ONLY
// to discard an actual committed response and reproduce transport ACK loss.
type AuthorityHandle interface {
	Handle(context.Context, authority.Actor, wire.OperationID, wire.RequestContext, []byte) (wire.Message, error)
}

func CallAuthority(ctx context.Context, h AuthorityHandle, p authority.Actor, op wire.OperationID, q wire.Message) (wire.Message, error) {
	definition, ok := wire.LookupOperation(op)
	if !ok {
		return nil, ErrUnknown
	}
	metadata := wire.RequestContext{Role: wire.Role(p.Role), Target: wire.TargetBackend, Method: definition.Method, RouteTemplate: definition.Path}
	raw, err := wire.EncodeRequest(op, metadata, q)
	if err != nil {
		return nil, err
	}
	return h.Handle(ctx, p, op, metadata, raw)
}

// ReceiverProofs is still an unimplemented production dependency on Agent4/5.
// A success must mean the original ticket/ACK/once-TTS chain was verified; no
// enqueue/counter may substitute. Tests explicitly use a synthetic Receiver
// around REAL Backend CommitReceiverConsume, and registered synthetic Observer.
type ReceiverProofs interface {
	Consume(context.Context, domain.Artifact, wire.AnswerGrant, wire.ReceiverConsumeTicket, wire.ReceiverTiming, wire.AcquireOutputPermitResponse) error
	Playing(context.Context, domain.Artifact) (wire.Evidence, error)
	Drain(context.Context, domain.Artifact) (wire.Evidence, error)
	Aggregate(context.Context, domain.Summary) (wire.Evidence, error)
}
type pendingGrant struct {
	grant    wire.AnswerGrant
	ticket   wire.ReceiverConsumeTicket
	timing   wire.ReceiverTiming
	permit   wire.AcquireOutputPermitResponse
	deadline time.Time
}

func (p pendingGrant) String() string   { return "pendingGrant{redacted}" }
func (p pendingGrant) GoString() string { return p.String() }

// AuthorityAdapter is Backend-domain composition, not a public handler/Runtime
// SQL client. Mutable identities come only from authenticated composition data.
// Every answer write goes through typed Handle. SQL here is scoped READBACK of
// current CAS revisions; it never modifies an answer, receipt, latch or cursor.
type AuthorityAdapter struct {
	Store            *authority.Store
	Client           AuthorityHandle
	Runtime, Control authority.Actor
	Facts            *domain.AuthorityFacts
	Receiver         ReceiverProofs
	GuardianID       string
	mu               sync.Mutex
	attempted        map[string]bool
	pending          map[string]pendingGrant
	playingID        wire.ID
}

func (a *AuthorityAdapter) binding() domain.Binding { return a.Facts.Binding }
func (a *AuthorityAdapter) handle(ctx context.Context, p authority.Actor, name string, fields map[string]any) (wire.Message, error) {
	op, ok := wire.LookupOperation(wire.OperationID(name))
	if !ok {
		return nil, ErrUnknown
	}
	raw, err := json.Marshal(fields)
	if err != nil {
		return nil, err
	}
	q, err := wire.Decode(op.RequestSchema, raw)
	if err != nil {
		return nil, err
	}
	h := a.Client
	if h == nil {
		h = a.Store
	}
	return CallAuthority(ctx, h, p, op.ID, q)
}
func (a *AuthorityAdapter) base() map[string]any {
	b := a.binding()
	return map[string]any{"schemaVersion": "0.5", "contractRevision": "durable-live-2", "requestId": ids.New("stream_request"), "tenantId": b.Tenant, "ownerId": b.Owner, "runId": b.Run}
}
func (a *AuthorityAdapter) unitBase() map[string]any {
	q := a.base()
	b := a.binding()
	for k, v := range map[string]any{"commandId": b.Command, "attemptId": b.Attempt, "sessionId": b.Session, "runEpoch": b.Epoch, "producerIncarnation": b.Producer, "requestHash": b.RequestHash} {
		q[k] = v
	}
	return q
}
func (a *AuthorityAdapter) revisions(ctx context.Context) (inbox, answer, run int64, last string, err error) {
	b := a.binding()
	err = a.Store.DB.QueryRow(ctx, `SELECT i.revision,COALESCE(s.answer_revision,0),r.state_revision,t.last_checkpoint FROM dl05_runtime_inbox i JOIN dl05_runs r USING(run_id) JOIN dl05_attempts t ON t.command_id=i.command_id LEFT JOIN dl05_answer_streams s ON s.command_id=i.command_id WHERE i.command_id=$1 AND r.run_id=$2 AND r.tenant_id=$3 AND r.owner_id=$4`, b.Command, b.Run, b.Tenant, b.Owner).Scan(&inbox, &answer, &run, &last)
	return
}
func (a *AuthorityAdapter) Check(ctx context.Context, artifact domain.Artifact) error {
	if a.Store == nil || a.Facts == nil || a.Receiver == nil {
		return ErrNotReady
	}
	if artifact.Draft().Binding != a.binding() || a.Runtime.Tenant != a.Control.Tenant || a.Runtime.Owner != a.Control.Owner {
		return domain.ErrFacts
	}
	return a.Facts.Check(ctx, artifact)
}
func (a *AuthorityAdapter) Prepare(ctx context.Context, artifact domain.Artifact) error {
	for tries := 0; tries < 3; tries++ {
		i, r, _, _, err := a.revisions(ctx)
		if err != nil {
			return err
		}
		q, err := artifact.PrepareRequest(ids.New("prepare"), i, r)
		if err != nil {
			return err
		}
		h := a.Client
		if h == nil {
			h = a.Store
		}
		_, err = CallAuthority(ctx, h, a.Runtime, wire.OpJournalPrepareAnswer, q)
		if err == nil {
			return nil
		}
		if errors.Is(err, context.DeadlineExceeded) {
			return ErrPrepareUncertain
		}
		if err.Error() != "STATE_CONFLICT" {
			return err
		}
	}
	return ErrBusy
}
func (a *AuthorityAdapter) Start(ctx context.Context, artifact domain.Artifact, mode StartMode) error {
	if err := a.Check(ctx, artifact); err != nil {
		return err
	}
	d := artifact.Draft()
	if mode == First && d.Sequence != 1 || mode == Continuation && d.Sequence < 2 {
		return ErrUnknown
	}
	a.mu.Lock()
	if a.attempted == nil {
		a.attempted = map[string]bool{}
		a.pending = map[string]pendingGrant{}
	}
	if a.attempted[d.ID] {
		a.mu.Unlock()
		return ErrUnknown
	}
	if len(a.attempted) >= domain.MaxUnits {
		a.mu.Unlock()
		return domain.ErrLimit
	}
	a.attempted[d.ID] = true
	a.mu.Unlock()
	b := a.binding()
	q := a.base()
	q["sessionId"] = b.Session
	q["runEpoch"] = b.Epoch
	q["producerIncarnation"] = b.Producer
	q["guardianId"] = a.GuardianID
	q["answerArtifactId"] = d.ID
	pm, err := a.handle(ctx, a.Runtime, "AcquireOutputPermit", q)
	if err != nil {
		return err
	}
	permit := *pm.(*wire.AcquireOutputPermitResponse)
	i, r, _, _, err := a.revisions(ctx)
	if err != nil {
		return err
	}
	q = a.unitBase()
	q["permitId"] = permit.PermitID
	q["expectedAnswerRevision"] = r
	name := "JournalStart"
	if mode == First {
		q["expectedInboxRevision"] = i
		q["answerArtifactId"] = d.ID
		q["answerArtifactHash"] = artifact.Hash()
	} else {
		name = "JournalStartAnswerSegment"
		q["answerId"] = b.Answer
		q["artifactId"] = d.ID
		q["artifactHash"] = artifact.Hash()
	}
	sent := time.Now()
	response, err := a.handle(ctx, a.Runtime, name, q)
	if err != nil {
		return a.uncertain(err)
	}
	var p pendingGrant
	if mode == First {
		v := response.(*wire.JournalStartResponse)
		if !v.StartAuthorized || v.AnswerGrant == nil || v.ConsumeTicket == nil || v.ConsumeTiming == nil {
			return a.uncertain(ErrUnknown)
		}
		p = pendingGrant{grant: *v.AnswerGrant, ticket: *v.ConsumeTicket, timing: *v.ConsumeTiming, permit: permit}
	} else {
		v := response.(*wire.JournalStartAnswerSegmentResponse)
		if !v.SegmentStartAuthorized || v.Grant == nil || v.ConsumeTicket == nil || v.ConsumeTiming == nil {
			return a.uncertain(ErrUnknown)
		}
		p = pendingGrant{grant: *v.Grant, ticket: *v.ConsumeTicket, timing: *v.ConsumeTiming, permit: permit}
	}
	p.deadline = sent.Add(time.Duration(min(p.timing.RemainingGrantMs, p.timing.RemainingProofMs)-p.timing.SafetyMarginMs) * time.Millisecond)
	if !time.Now().Before(p.deadline) {
		return a.uncertain(ErrUnknown)
	}
	a.mu.Lock()
	a.pending[d.ID] = p
	a.mu.Unlock()
	return nil
}
func (a *AuthorityAdapter) ConsumeOnce(ctx context.Context, artifact domain.Artifact) error {
	a.mu.Lock()
	p, ok := a.pending[artifact.Draft().ID]
	delete(a.pending, artifact.Draft().ID)
	a.mu.Unlock()
	if !ok || !time.Now().Before(p.deadline) {
		return a.uncertain(ErrUnknown)
	}
	if err := a.Receiver.Consume(ctx, artifact, p.grant, p.ticket, p.timing, p.permit); err != nil {
		return a.uncertain(err)
	}
	if artifact.Draft().Sequence == 1 {
		evidence, err := a.Receiver.Playing(ctx, artifact)
		if err != nil {
			return a.uncertain(err)
		}
		cp := a.checkpoint("PLAYING", a.Runtime.Producer, 1, evidence)
		q := a.base()
		q["checkpoint"] = cp
		q["expectedRevision"] = nil
		if _, err = a.handle(ctx, a.Runtime, "ConfirmCheckpoint", q); err != nil {
			return a.uncertain(err)
		}
		a.mu.Lock()
		a.playingID = cp.CheckpointID
		a.mu.Unlock()
	}
	return nil
}
func (a *AuthorityAdapter) ConfirmDrain(ctx context.Context, artifact domain.Artifact) error {
	ev, err := a.Receiver.Drain(ctx, artifact)
	if err != nil {
		return err
	}
	for tries := 0; tries < 3; tries++ {
		_, r, _, _, err := a.revisions(ctx)
		if err != nil {
			return err
		}
		q := a.unitBase()
		d := artifact.Draft()
		q["answerId"] = d.Binding.Answer
		q["artifactId"] = d.ID
		q["artifactHash"] = artifact.Hash()
		q["expectedAnswerRevision"] = r
		q["idempotencyKey"] = "drain:" + d.ID
		q["evidence"] = ev
		if _, err = a.handle(ctx, a.Runtime, "JournalConfirmAnswerSegment", q); err == nil {
			return nil
		}
		if err.Error() != "STATE_CONFLICT" {
			return err
		}
	}
	return ErrBusy
}
func (a *AuthorityAdapter) Seal(ctx context.Context, s domain.Summary) error {
	for tries := 0; tries < 3; tries++ {
		_, r, _, _, err := a.revisions(ctx)
		if err != nil {
			return err
		}
		q, err := s.SealRequest(ids.New("seal"), r)
		if err != nil {
			return err
		}
		h := a.Client
		if h == nil {
			h = a.Store
		}
		_, err = CallAuthority(ctx, h, a.Runtime, wire.OpJournalSealAnswer, q)
		if err == nil {
			return nil
		}
		if err.Error() != "STATE_CONFLICT" {
			return err
		}
	}
	return ErrBusy
}
func (a *AuthorityAdapter) checkpoint(state, producer string, seq int64, ev wire.Evidence) wire.PlaybackCheckpoint {
	b := a.binding()
	return wire.PlaybackCheckpoint{SchemaVersion: "0.5", ContractRevision: "durable-live-2", TenantID: wire.ID(b.Tenant), OwnerID: wire.ID(b.Owner), RunID: wire.ID(b.Run), CheckpointID: wire.ID(ids.New("checkpoint")), EventID: wire.ID(ids.New("event")), AttemptID: wire.ID(b.Attempt), SessionID: wire.ID(b.Session), UtteranceID: wire.ID(b.Utterance), CommandID: wire.ID(b.Command), RunEpoch: wire.Epoch(b.Epoch), ProducerIncarnation: wire.ID(producer), ProducerSeq: seq, State: wire.PlaybackCheckpointState(state), OccurredAt: wire.Timestamp(time.Now().UTC().Format(time.RFC3339Nano)), Evidence: ev}
}

// Commit does not accept a synthesized completed flag. Backend allDrain and
// predecessor validation enforce sealed/contiguous/registered ranges, then the
// distinct CONTROL operation alone releases the existing business Slot.
func (a *AuthorityAdapter) Commit(ctx context.Context, s domain.Summary) error {
	ev, err := a.Receiver.Aggregate(ctx, s)
	if err != nil {
		return err
	}
	a.mu.Lock()
	playing := a.playingID
	a.mu.Unlock()
	ev.PredecessorCheckpointIDs = []wire.ID{playing}
	local := a.checkpoint("LOCAL_MEDIA_DRAINED", a.Runtime.Producer, 2, ev)
	q := a.base()
	q["checkpoint"] = local
	q["expectedRevision"] = nil
	if _, err = a.handle(ctx, a.Runtime, "ConfirmCheckpoint", q); err != nil {
		if errors.Is(err, context.DeadlineExceeded) || errors.Is(err, context.Canceled) {
			return a.uncertain(err)
		}
		return err
	}
	_, _, revision, _, err := a.revisions(ctx)
	if err != nil {
		return err
	}
	ev.EvidenceType = wire.EvidenceEvidenceType("BUSINESS_COMMIT")
	ev.PredecessorCheckpointIDs = []wire.ID{local.CheckpointID}
	complete := a.checkpoint("COMPLETED", a.Control.Incarnation, 1, ev)
	q = a.base()
	q["checkpoint"] = complete
	q["expectedRevision"] = revision
	_, err = a.handle(ctx, a.Control, "ConfirmCheckpoint", q)
	if err != nil {
		return a.uncertain(err)
	}
	return nil
}
func (a *AuthorityAdapter) uncertain(cause error) error {
	ctx, cancel := context.WithTimeout(context.Background(), 2*time.Second)
	defer cancel()
	_, _, revision, last, err := a.revisions(ctx)
	if err != nil {
		return errors.Join(ErrUnknown, cause, err)
	}
	b := a.binding()
	q := a.base()
	q["expectedRevision"] = revision
	q["runEpoch"] = b.Epoch
	q["attemptId"] = b.Attempt
	q["lastKnownState"] = last
	q["reasonCode"] = "STREAM_ACK_UNKNOWN"
	q["evidenceRef"] = "stream:unknown"
	q["idempotencyKey"] = "stream:unknown"
	_, err = a.handle(ctx, a.Control, "MarkExecutionUnknown", q)
	return errors.Join(ErrUnknown, cause, err)
}

var _ Executor = (*AuthorityAdapter)(nil)
var _ Completion = (*AuthorityAdapter)(nil)

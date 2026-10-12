package narration

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"strings"
	"time"

	"astralive/backend/internal/durability"
	"astralive/backend/internal/ids"
	"astralive/backend/internal/interaction"
	"github.com/jackc/pgx/v5"
)

func Enabled() (bool, error) {
	if _, ok := os.LookupEnv("ASTRALIVE_NARRATION_CONTINUITY_ENABLED"); ok {
		return false, fmt.Errorf("use frozen ASTRALIVE_CONTINUITY_ENABLED; old continuity flag is unsupported")
	}
	v, present := os.LookupEnv("ASTRALIVE_CONTINUITY_ENABLED")
	if !present {
		return false, nil
	}
	v = strings.ToLower(v)
	switch v {
	case "false", "0":
		return false, nil
	case "true", "1":
		return true, nil
	default:
		return false, fmt.Errorf("invalid ASTRALIVE_CONTINUITY_ENABLED")
	}
}

type Controller struct {
	Store           *durability.Store
	StagingSettings StagingSettings
	// Composed by App: conservatively retire the entire captured Session on
	// either product identity or fact version invalidation, in THIS transaction.
	RetireCapturedSession func(context.Context, pgx.Tx, durability.Run) error
}

func New(store *durability.Store) *Controller {
	c := &Controller{Store: store}
	store.TimelineProjection = c.Project
	return c
}

type StartRequest struct {
	RequestID     string      `json:"requestId"`
	ScriptVersion string      `json:"scriptVersion"`
	Beats         []BeatInput `json:"beats"`
	RequiredSinks []string    `json:"requiredSinks"`
	Policy        Policy      `json:"policy"`
	Style         string      `json:"style"`
}

func (c *Controller) load(ctx context.Context, tx pgx.Tx, sid string) (Document, error) {
	var raw []byte
	e := tx.QueryRow(ctx, `SELECT document_json FROM v05_narrations WHERE session_id=$1 AND state NOT IN ('STOPPED','FAILED') ORDER BY updated_at DESC LIMIT 1 FOR UPDATE`, sid).Scan(&raw)
	var d Document
	if e == nil {
		e = json.Unmarshal(raw, &d)
	}
	return d, e
}
func (c *Controller) Snapshot(ctx context.Context, sid string) (Document, error) {
	// The authenticated HTTP route checks current Session AND Room ownership.
	// Reads include finished/recovery projections and need no execution lease.
	var raw []byte
	e := c.Store.DB.QueryRow(ctx, `SELECT document_json FROM v05_narrations WHERE session_id=$1 ORDER BY updated_at DESC LIMIT 1`, sid).Scan(&raw)
	var d Document
	if e == nil {
		e = json.Unmarshal(raw, &d)
	}
	return d, e
}

// FinalizeStop projects existing authenticated Session terminal evidence in
// the caller's event transaction. A STOPPING tombstone alone is insufficient.
func (c *Controller) FinalizeStop(ctx context.Context, tx pgx.Tx, sid string) error {
	d, err := c.load(ctx, tx, sid)
	if err == pgx.ErrNoRows {
		return nil
	}
	if err != nil {
		return err
	}
	if d.State != Stopping || !d.StopBarrier {
		return ErrUnknown
	}
	var proven bool
	err = tx.QueryRow(ctx, `SELECT EXISTS(
 SELECT 1 FROM live_sessions se JOIN session_provider_bindings b ON b.session_id=se.id
 JOIN v05_inbox i ON i.session_id=se.id AND i.run_epoch=$2 AND i.command_type='STOP_SESSION'
 JOIN v05_receipts r ON r.session_id=i.session_id AND r.run_epoch=i.run_epoch
 AND r.command_id=i.command_id AND r.tenant_id=i.tenant_id AND r.user_id=i.user_id
 WHERE se.id=$1 AND se.status='ENDED' AND b.released_at IS NOT NULL
 AND b.tenant_id=i.tenant_id AND b.user_id=i.user_id
 AND i.execution_state='TERMINAL' AND r.state='completed' AND r.evidence_type='control_cleanup')`, sid, d.RunEpoch).Scan(&proven)
	if err != nil {
		return err
	}
	if !proven {
		return ErrUnknown
	}
	old := d.Revision
	d.State, d.Reason = Stopped, "SESSION_CLEANUP_CONFIRMED"
	d.Revision++
	return c.save(ctx, tx, d, old)
}
func (c *Controller) save(ctx context.Context, tx pgx.Tx, d Document, old int64) error {
	raw, _ := json.Marshal(d)
	cursor, _ := json.Marshal(d.Cursor)
	point, _ := json.Marshal(d.Resume)
	tag, e := tx.Exec(ctx, `UPDATE v05_narrations SET run_epoch=$3,revision=$4,state=$5,completion_cursor_json=$6,resume_point_json=$7,document_json=$8,stop_barrier=$9,updated_at=clock_timestamp() WHERE narration_id=$1 AND session_id=$2 AND revision=$10`, d.Plan.ID, d.Plan.SessionID, d.RunEpoch, d.Revision, d.State, cursor, point, raw, d.StopBarrier, old)
	if e != nil {
		return e
	}
	if tag.RowsAffected() != 1 {
		return ErrConflict
	}
	for _, s := range d.Plan.Segments {
		if e = c.segment(ctx, tx, d, s); e != nil {
			return e
		}
	}
	if d.Turn != nil {
		t := d.Turn
		traw, _ := json.Marshal(t)
		source, _ := json.Marshal(t.SourceIDs)
		var pointRev *int64
		if d.Resume != nil {
			pointRev = &d.Resume.Revision
		}
		_, e = tx.Exec(ctx, `INSERT INTO v05_interaction_turns(turn_id,narration_id,session_id,tenant_id,user_id,source_ids,question_hash,question,deadline,state,resume_point_revision,answer_summary,document_json) SELECT $1,narration_id,session_id,tenant_id,user_id,$3,$4,$5,$6,$7,$8,$9,$10 FROM v05_narrations WHERE narration_id=$2 ON CONFLICT(turn_id) DO UPDATE SET state=EXCLUDED.state,resume_point_revision=EXCLUDED.resume_point_revision,answer_summary=EXCLUDED.answer_summary,document_json=EXCLUDED.document_json,updated_at=clock_timestamp()`, t.ID, d.Plan.ID, source, t.QuestionHash, t.Question, t.Deadline, t.Status, pointRev, t.AnswerText, traw)
		if e != nil {
			return e
		}
		if t.Answer != nil {
			if e = c.segment(ctx, tx, d, *t.Answer); e != nil {
				return e
			}
		}
	}
	if d.Bridge != nil && d.Bridge.Text != "" {
		e = c.segment(ctx, tx, d, *d.Bridge)
	}
	return e
}
func (c *Controller) segment(ctx context.Context, tx pgx.Tx, d Document, s Segment) error {
	raw, _ := json.Marshal(s)
	facts, _ := json.Marshal(s.FactIDs)
	// Answer/bridge have a reserved nonoverlapping ordinal domain; no lexical ID ordering.
	ordinal := s.Ordinal
	if s.Lane != "NARRATION" {
		var n int
		e := tx.QueryRow(ctx, `SELECT segment_ordinal FROM v05_segments WHERE segment_id=$1`, s.ID).Scan(&n)
		if e == nil {
			ordinal = n
		} else if e == pgx.ErrNoRows {
			e = tx.QueryRow(ctx, `SELECT COALESCE(MAX(segment_ordinal),999999)+1 FROM v05_segments WHERE narration_id=$1 AND segment_ordinal>=1000000`, d.Plan.ID).Scan(&ordinal)
		}
		if e != nil {
			return e
		}
	}
	tag, e := tx.Exec(ctx, `INSERT INTO v05_segments(segment_id,narration_id,session_id,tenant_id,user_id,beat_id,segment_ordinal,text_hash,fact_ids,text,product_version,status,document_json) SELECT $1,narration_id,session_id,tenant_id,user_id,$3,$4,$5,$6,$7,$8,$9,$10 FROM v05_narrations WHERE narration_id=$2 ON CONFLICT(segment_id) DO UPDATE SET status=EXCLUDED.status,document_json=EXCLUDED.document_json,completed_at=CASE WHEN EXCLUDED.status='COMPLETED' THEN COALESCE(v05_segments.completed_at,clock_timestamp()) ELSE v05_segments.completed_at END,updated_at=clock_timestamp() WHERE v05_segments.text_hash=EXCLUDED.text_hash AND v05_segments.product_version=EXCLUDED.product_version`, s.ID, d.Plan.ID, s.BeatID, ordinal, s.TextHash, facts, s.Text, d.Plan.ProductVersion, s.Status, raw)
	if e == nil && tag.RowsAffected() != 1 {
		return ErrConflict
	}
	return e
}

// ProductSnapshot is always read through the Session's captured owner/binding.
// Values are JSON decimal strings for fingerprints, not lossy floating point.
func (c *Controller) product(ctx context.Context, tx pgx.Tx, sid string) (string, string, map[string]string, error) {
	var raw []byte
	var product string
	e := tx.QueryRow(ctx, `SELECT p.id,jsonb_build_object('productId',p.id,'name',p.name,'description',p.description,'price',p.price::text,'currency',p.currency,'stock',p.stock::text,'sizes',array_to_string(p.sizes,'、')) FROM live_sessions s JOIN live_rooms r ON r.id=s.room_id JOIN session_provider_bindings b ON b.session_id=s.id AND b.released_at IS NULL JOIN products p ON p.id=r.active_product_id JOIN resource_owners o ON o.kind='product' AND o.resource_id=p.id AND o.tenant_id=b.tenant_id AND o.user_id=b.user_id WHERE s.id=$1 AND s.status='LIVE' AND b.room_snapshot->>'activeProductId'=p.id FOR SHARE OF p`, sid).Scan(&product, &raw)
	if e != nil {
		return "", "", nil, e
	}
	hash, e := durability.Hash(raw)
	var facts map[string]string
	if e == nil {
		e = json.Unmarshal(raw, &facts)
	}
	return product, hash, facts, e
}
func (c *Controller) fresh(ctx context.Context, tx pgx.Tx, d Document) error {
	pid, h, _, e := c.product(ctx, tx, d.Plan.SessionID)
	if errors.Is(e, pgx.ErrNoRows) {
		return ErrProduct
	}
	if e != nil {
		return e
	}
	if pid != d.Plan.ProductID || h != d.Plan.ProductHash {
		return ErrProduct
	}
	return nil
}
func (c *Controller) Start(ctx context.Context, sid, trace string, x StartRequest) (Document, error) {
	if c.RetireCapturedSession == nil {
		return Document{}, ErrDependency
	}
	tx, e := durability.BeginBusiness(ctx, c.Store.DB)
	if e != nil {
		return Document{}, e
	}
	defer tx.Rollback(ctx)
	run, e := c.Store.Current(ctx, tx, sid, false)
	if e != nil || run.Status != "ACTIVE" {
		if e == nil {
			e = ErrStopped
		}
		return Document{}, e
	}
	requestRaw, er := json.Marshal(x)
	if er != nil {
		return Document{}, er
	}
	requestHash := Hash(string(requestRaw))
	// Substitutions must not mutate a caller's reusable request/idempotency body.
	if e = json.Unmarshal(requestRaw, &x); e != nil {
		return Document{}, e
	}
	product, hash, facts, e := c.product(ctx, tx, sid)
	if e != nil {
		return Document{}, e
	}
	if x.RequestID == "" || len(x.Beats) > 256 {
		return Document{}, ErrConflict
	}
	if x.Policy == "" {
		x.Policy = AtBoundary
	}
	nid := stable("narration", sid+":"+x.RequestID)
	var existing []byte
	e = tx.QueryRow(ctx, `SELECT document_json FROM v05_narrations WHERE narration_id=$1 AND session_id=$2`, nid, sid).Scan(&existing)
	if e == nil {
		var d Document
		_ = json.Unmarshal(existing, &d)
		if d.RequestHash != requestHash {
			return d, ErrConflict
		}
		return d, nil
	}
	if e != pgx.ErrNoRows {
		return Document{}, e
	}
	var ordinaryBusy bool
	e = tx.QueryRow(ctx, `SELECT EXISTS(SELECT 1 FROM utterances WHERE session_id=$1 AND status NOT IN ('COMPLETED','INTERRUPTED','FAILED','CANCELLED'))`, sid).Scan(&ordinaryBusy)
	if e != nil {
		return Document{}, e
	}
	if ordinaryBusy {
		return Document{}, ErrBoundary
	}
	var active bool
	e = tx.QueryRow(ctx, `SELECT EXISTS(SELECT 1 FROM v05_narrations WHERE session_id=$1 AND state NOT IN ('STOPPED','FAILED'))`, sid).Scan(&active)
	if e != nil {
		return Document{}, e
	}
	if active {
		return Document{}, ErrBoundary
	}
	// Dynamic claims in authored plans use trusted substitutions. Numeric
	// values are not copied from a stale script and facts are checked again at commit.
	for bi := range x.Beats {
		for si := range x.Beats[bi].Statements {
			s := &x.Beats[bi].Statements[si]
			for _, f := range s.FactIDs {
				if v, ok := facts[f]; ok {
					token := "{{" + f + "}}"
					if !strings.Contains(s.Text, token) {
						return Document{}, fmt.Errorf("%w: %s needs trusted placeholder", ErrProduct, f)
					}
					s.Text = strings.ReplaceAll(s.Text, token, v)
				}
			}
		}
	}
	p, e := BuildPlan(nid, sid, x.ScriptVersion, product, hash, hash, x.Style, x.Policy, x.RequiredSinks, x.Beats)
	if e != nil {
		return Document{}, e
	}
	d := NewDocument(p, run.Epoch)
	d.TimelineEpoch = run.TimelineEpoch
	d.RequestHash = requestHash
	if e = c.Store.ConfigureTimelineOutput(ctx, tx, run, 48000, x.RequiredSinks, nil); e != nil {
		return d, e
	}
	plan, _ := json.Marshal(p)
	raw, _ := json.Marshal(d)
	_, e = tx.Exec(ctx, `INSERT INTO v05_narrations(narration_id,session_id,tenant_id,user_id,run_epoch,revision,state,script_version,product_snapshot_hash,plan_json,document_json) SELECT $1,session_id,tenant_id,user_id,run_epoch,$4,$5,$6,$7,$8,$9 FROM v05_session_runs WHERE session_id=$2 AND run_epoch=$3`, nid, sid, run.Epoch, d.Revision, d.State, p.ScriptVersion, hash, plan, raw)
	if e != nil {
		return d, e
	}
	for _, s := range d.Plan.Segments {
		if e = c.segment(ctx, tx, d, s); e != nil {
			return d, e
		}
	}
	old := d.Revision
	s, e := d.PlanNext(old, run.Epoch)
	if e != nil {
		return d, e
	}
	if e = c.save(ctx, tx, d, old); e != nil {
		return d, e
	}
	if s != nil {
		_, e = c.enqueueSegment(ctx, tx, run, d, *s, trace)
	}
	if e != nil {
		return d, e
	}
	return d, tx.Commit(ctx)
}
func (c *Controller) payload(ctx context.Context, tx pgx.Tx, r durability.Run, d Document) (map[string]any, error) {
	var revision int64
	var voice string
	e := tx.QueryRow(ctx, `SELECT sr.timeline_revision,lr.voice_id FROM v05_session_runs sr JOIN live_sessions s ON s.id=sr.session_id JOIN live_rooms lr ON lr.id=s.room_id WHERE sr.session_id=$1 AND sr.run_epoch=$2`, r.SessionID, r.Epoch).Scan(&revision, &voice)
	return map[string]any{"leaseToken": r.Token, "expectedTimelineRevision": revision, "expectedNarrationRevision": d.Revision, "voice": map[string]string{"voiceId": voice}}, e
}
func (c *Controller) enqueue(ctx context.Context, tx pgx.Tx, r durability.Run, d Document, kind, key, trace, segment, lane string, payload map[string]any) (durability.Command, error) {
	return c.Store.EnqueueNarration(ctx, tx, r, kind, d.Plan.ID+":"+key, trace, "", payload, durability.MediaMetadata{NarrationID: d.Plan.ID, SegmentID: segment, TimelineEpoch: r.TimelineEpoch, Lane: lane})
}
func (c *Controller) enqueueSegment(ctx context.Context, tx pgx.Tx, r durability.Run, d Document, s Segment, trace string) (durability.Command, error) {
	p, e := c.payload(ctx, tx, r, d)
	if e != nil {
		return durability.Command{}, e
	}
	p["text"] = s.Text
	p["textHash"] = s.TextHash
	p["factIds"] = append([]string{}, s.FactIDs...)
	p["factVersion"] = d.Plan.ProductVersion
	p["productId"] = d.Plan.ProductID
	p["productSnapshotHash"] = d.Plan.ProductHash
	p["utteranceId"] = stable("utt", s.ID+fmt.Sprint(r.Epoch))
	p["attemptId"] = stable("attempt", s.ID+fmt.Sprint(r.Epoch))
	p["requiredSinks"] = d.Plan.RequiredSinks
	p["maxDurationMs"] = 8000
	if c.StagingSettings.Enabled {
		if c.StagingSettings.LimitsRevision != nil && *c.StagingSettings.LimitsRevision == "staging-short-1" {
			p["maxDurationMs"] = 1920
		}
		beat := s.BeatID
		if beat == "" && d.Resume != nil {
			beat = d.Resume.NextBeatID
		}
		if beat == "" {
			return durability.Command{}, ErrConflict
		}
		p["beatId"] = beat
		p["interactionTurnId"] = nil
		if s.Lane != "NARRATION" {
			if d.Turn == nil {
				return durability.Command{}, ErrConflict
			}
			p["interactionTurnId"] = d.Turn.ID
		}
	}
	return c.enqueue(ctx, tx, r, d, "COMMIT_SEGMENT", s.ID+":commit", trace, s.ID, s.Lane, p)
}

// Gate is advisory: an MVCC read must not lock execution authority while a
// Scheduler consults it. Select rechecks the full authority under SQL locks.
func (c *Controller) Gate(ctx context.Context, sid string) (bool, bool, error) {
	var raw []byte
	var epoch int64
	var active bool
	e := c.Store.DB.QueryRow(ctx, `SELECT l.run_epoch,
 r.status='ACTIVE' AND se.status='LIVE' AND l.expires_at>clock_timestamp(),d.document_json
 FROM live_sessions se
 JOIN resource_owners o ON o.kind='session' AND o.resource_id=se.id
 JOIN resource_owners ro ON ro.kind='room' AND ro.resource_id=se.room_id AND ro.tenant_id=o.tenant_id AND ro.user_id=o.user_id
 JOIN session_provider_bindings b ON b.session_id=se.id AND b.tenant_id=o.tenant_id AND b.user_id=o.user_id AND b.released_at IS NULL AND b.expires_at>clock_timestamp()
 JOIN v05_recovery_leases l ON l.session_id=se.id
 JOIN v05_session_runs r ON r.session_id=l.session_id AND r.run_epoch=l.run_epoch
 LEFT JOIN LATERAL (SELECT document_json FROM v05_narrations WHERE session_id=se.id AND state NOT IN ('STOPPED','FAILED') ORDER BY updated_at DESC LIMIT 1) d ON true
 WHERE se.id=$1`, sid).Scan(&epoch, &active, &raw)
	if e != nil {
		return true, false, e
	}
	if len(raw) == 0 {
		return true, false, nil
	}
	var d Document
	if e = json.Unmarshal(raw, &d); e != nil {
		return true, false, e
	}
	n := d.Next()
	return true, active && epoch == d.RunEpoch && d.State == Narrating && n != nil && n.Status == "EXECUTING" && !d.OperatorOverride && !d.StopBarrier && d.Plan.Policy == AtBoundary, nil
}
func (c *Controller) Select(ctx context.Context, sid string, v interaction.Selection, ttl time.Duration) (string, error) {
	ctx, cancel := context.WithDeadline(ctx, v.Event.ReceivedAt.Add(ttl))
	defer cancel()
	tx, e := durability.BeginBusiness(ctx, c.Store.DB)
	if e != nil {
		return "", e
	}
	defer tx.Rollback(ctx)
	run, e := c.Store.Current(ctx, tx, sid, false)
	if e != nil {
		return "", e
	}
	d, e := c.load(ctx, tx, sid)
	if e != nil {
		return "", e
	}
	if e = c.fresh(ctx, tx, d); e != nil {
		return "", e
	}
	if v.ProductID != d.Plan.ProductID || v.Event.SessionID != sid {
		return "", ErrProduct
	}
	sources := v.SourceIDs
	if len(sources) == 0 {
		sources = []string{v.Event.EventID}
	}
	turn := Turn{ID: stable("turn", sid+strings.Join(sources, "|")), SourceIDs: sources, Question: v.Event.Content, QuestionHash: Hash(v.Event.Content), Priority: v.Priority, Deadline: v.Event.ReceivedAt.Add(ttl), SelectedAt: v.SelectedAt, ProductHash: d.Plan.ProductHash}
	turn.SourceScope = SourceScope{v.Event.Platform, v.Event.PlatformRoomID, v.Event.InternalRoomID, v.Event.Transport}
	var seen bool
	e = tx.QueryRow(ctx, `SELECT EXISTS(SELECT 1 FROM v05_interaction_turns WHERE session_id=$1 AND turn_id=$2)`, sid, turn.ID).Scan(&seen)
	if e != nil {
		return "", e
	}
	if seen {
		return turn.ID, nil
	}
	old := d.Revision
	if e = d.RequestSuspend(turn, old, run.Epoch, time.Now(), false); e != nil {
		return "", e
	}
	if e = c.save(ctx, tx, d, old); e != nil {
		return "", e
	}
	p, e := c.payload(ctx, tx, run, d)
	if e != nil {
		return "", e
	}
	p["boundarySegmentId"] = d.BoundaryID
	p["interactionTurnId"] = turn.ID
	p["deadline"] = turn.Deadline.UTC().Format(time.RFC3339Nano)
	_, e = c.enqueue(ctx, tx, run, d, "SUSPEND_AT_BOUNDARY", turn.ID+":suspend", v.Event.TraceID, "", "NARRATION", p)
	if e != nil {
		return "", e
	}
	return turn.ID, tx.Commit(ctx)
}

// Run is a persisted-state driver, not a second comment Scheduler. Polling and
// all decisions use the same authority locks/transaction as Stop and selection.
func (c *Controller) Run(ctx context.Context) {
	tick := time.NewTicker(100 * time.Millisecond)
	defer tick.Stop()
	for {
		select {
		case <-ctx.Done():
			return
		case <-tick.C:
		}
		rows, e := c.Store.DB.Query(ctx, `SELECT session_id FROM v05_narrations WHERE state IN ('PLANNING','NARRATING','SUSPEND_REQUESTED','SUSPENDED','ANSWERING','BRIDGE_READY','RESUMING') AND NOT stop_barrier LIMIT 32`)
		if e != nil {
			continue
		}
		var sessions []string
		for rows.Next() {
			var sid string
			if rows.Scan(&sid) == nil {
				sessions = append(sessions, sid)
			}
		}
		rows.Close()
		for _, sid := range sessions {
			bounded, cancel := context.WithTimeout(ctx, 2*time.Second)
			_ = c.Drive(bounded, sid)
			cancel()
		}
	}
}

func (c *Controller) Drive(ctx context.Context, sid string) error {
	tx, e := c.Store.DB.Begin(ctx)
	if e != nil {
		return e
	}
	defer tx.Rollback(ctx)
	run, e := c.Store.Current(ctx, tx, sid, true)
	if e != nil {
		return e
	}
	d, e := c.load(ctx, tx, sid)
	if e != nil {
		return e
	}
	if d.RunEpoch != run.Epoch || run.Status != "ACTIVE" {
		return ErrStale
	}
	if d.StopBarrier || d.OperatorOverride || d.State == RecoveryRequired {
		return ErrStopped
	}
	if e = c.fresh(ctx, tx, d); e != nil {
		if !errors.Is(e, ErrProduct) {
			return e // A database outage is not a product-version decision.
		}
		// Frozen §4 requires whole old-Session Stop, not merely narration Stop.
		// The App hook reuses its existing Seal/STOP_SESSION/control path and
		// never performs a hot rebind or FORCE audience interruption.
		if c.RetireCapturedSession == nil {
			return ErrDependency
		}
		if er := c.RetireCapturedSession(ctx, tx, run); er != nil {
			return er
		}
		return tx.Commit(ctx)
	}
	// Never enqueue another operation behind an unresolved effect. ACKED media
	// still executes; segment state, not Outbox ACK, determines progress.
	var pending bool
	e = tx.QueryRow(ctx, `SELECT EXISTS(SELECT 1 FROM v05_outbox WHERE session_id=$1 AND run_epoch=$2 AND delivery_state IN ('PENDING','CLAIMED','UNKNOWN'))`, sid, run.Epoch).Scan(&pending)
	if e != nil || pending {
		return e
	}
	old := d.Revision
	trace := ids.New("trace")
	p, e := c.payload(ctx, tx, run, d)
	if e != nil {
		return e
	}
	switch d.State {
	case Planning, Narrating, Resuming:
		if d.State == Resuming && d.Bridge != nil && d.Bridge.Text != "" && d.Bridge.Status != "COMPLETED" {
			return nil
		}
		s := d.Next()
		if s == nil || s.Status == "PENDING" || s.Status == "SATISFIED_BY_ANSWER" {
			s, e = d.PlanNext(old, run.Epoch)
			if e != nil {
				return e
			}
			if e = c.save(ctx, tx, d, old); e != nil {
				return e
			}
			if s != nil {
				_, e = c.enqueueSegment(ctx, tx, run, d, *s, trace)
			}
		}
	case Suspended:
		if d.Turn == nil || d.Resume == nil {
			return ErrBoundary
		}
		if !d.Turn.Deadline.After(time.Now()) {
			d.Turn.Status = "EXPIRED"
			d.ResumeTargetEpoch = run.TimelineEpoch + 1
			d.State = BridgeReady
			d.Bridge = &Segment{Text: "", Lane: "RESUME_BRIDGE"}
			d.Revision++
			if e = c.save(ctx, tx, d, old); e != nil {
				return e
			}
			break
		}
		if run.TimelineEpoch == d.Resume.Boundary.Identity.TimelineEpoch {
			e = c.epoch(ctx, tx, run, d, "ANSWER", trace)
			break
		}
		_, _, facts, er := c.product(ctx, tx, sid)
		if er != nil {
			return er
		}
		p["interactionTurnId"] = d.Turn.ID
		p["question"] = d.Turn.Question
		p["productId"] = d.Plan.ProductID
		p["productSnapshotHash"] = d.Plan.ProductHash
		p["factVersion"] = d.Plan.ProductVersion
		p["deadline"] = d.Turn.Deadline.UTC().Format(time.RFC3339Nano)
		p["resumePointRevision"] = d.Resume.Revision
		p["latestFacts"] = facts
		safe, factIDs := factAnswer(d.Turn.Question, facts)
		p["answerText"] = safe
		p["factIds"] = factIDs
		_, e = c.enqueue(ctx, tx, run, d, "START_AUDIENCE_ANSWER", d.Turn.ID+":prepare-answer", trace, "", "AUDIENCE_ANSWER", p)
	case Answering:
		if d.Turn == nil || d.Turn.Status != "COMPLETED" {
			return nil
		}
		_, _, facts, er := c.product(ctx, tx, sid)
		if er != nil {
			return er
		}
		p["context"] = map[string]any{"goal": d.Plan.Beats, "lastCompletedText": d.Resume.Cursor.LastText, "question": d.Turn.Question, "committedAnswer": d.Turn.AnswerText, "completedFactIds": d.Cursor.CompletedFacts, "pendingRequiredFactIds": d.PendingFacts(), "nextBeatId": d.Resume.NextBeatID, "style": d.Plan.Style, "productId": d.Plan.ProductID, "factVersion": d.Plan.ProductVersion, "latestFacts": facts}
		p["choices"] = d.BridgeChoices()
		p["interactionTurnId"] = d.Turn.ID
		p["resumePointRevision"] = d.Resume.Revision
		_, e = c.enqueue(ctx, tx, run, d, "PREPARE_RESUME_BRIDGE", d.Turn.ID+":prepare-bridge", trace, "", "RESUME_BRIDGE", p)
	case BridgeReady:
		if d.Resume == nil {
			return ErrBoundary
		}
		targetEpoch := d.Resume.Boundary.Identity.TimelineEpoch + 2
		if d.Turn != nil && d.Turn.Status == "EXPIRED" {
			targetEpoch = d.ResumeTargetEpoch
		}
		if run.TimelineEpoch < targetEpoch {
			e = c.epoch(ctx, tx, run, d, "RESUME", trace)
			break
		}
		if e = d.ResumeNarration(old, run.Epoch, d.Resume.Revision); e != nil {
			return e
		}
		if e = c.save(ctx, tx, d, old); e != nil {
			return e
		}
		if d.Bridge != nil && d.Bridge.Text != "" {
			_, e = c.enqueueSegment(ctx, tx, run, d, *d.Bridge, trace)
		}
	}
	if e != nil {
		return e
	}
	return tx.Commit(ctx)
}
func (c *Controller) epoch(ctx context.Context, tx pgx.Tx, r durability.Run, d Document, reason, trace string) error {
	var cursor int64
	e := tx.QueryRow(ctx, `SELECT current_committed_sample FROM v05_session_runs WHERE session_id=$1 AND run_epoch=$2`, r.SessionID, r.Epoch).Scan(&cursor)
	if e != nil {
		return e
	}
	if d.InvalidatedEpoch != r.TimelineEpoch {
		p, e := c.payload(ctx, tx, r, d)
		if e != nil {
			return e
		}
		delete(p, "voice")
		p["cutSample"] = cursor
		p["reason"] = reason
		_, e = c.enqueue(ctx, tx, r, d, "INVALIDATE_AFTER", d.Turn.ID+":"+reason+":invalidate", trace, "", "NARRATION", p)
		return e
	}
	reservation, e := c.Store.ReserveTimelineEpoch(ctx, tx, r, r.TimelineEpoch, cursor, reason)
	if e != nil {
		return e
	}
	p, e := c.payload(ctx, tx, r, d)
	if e != nil {
		return e
	}
	delete(p, "voice")
	p["expectedPreviousEpoch"] = r.TimelineEpoch
	p["newEpoch"] = reservation.TimelineEpoch
	p["reservationToken"] = reservation.ReservationToken
	p["originPosition"] = Position{r.SessionID, r.Epoch, r.TimelineEpoch, cursor, 48000, cursor * 1000000 / 48000}
	p["reason"] = reason
	// Install begins a new publication fence; retained consumed prefix is immutable.
	_, e = c.Store.EnqueueNarration(ctx, tx, r, "BEGIN_EPOCH", d.Plan.ID+":"+d.Turn.ID+":"+reason+":epoch", trace, "", p, durability.MediaMetadata{NarrationID: d.Plan.ID, TimelineEpoch: reservation.TimelineEpoch, Lane: "NARRATION"})
	return e
}

// Project is invoked by A AFTER proof validation but BEFORE transaction commit.
// A receipt append, completed-fact ledger and cursor CAS share this transaction.
func (c *Controller) Project(ctx context.Context, tx pgx.Tx, command durability.Command, raw json.RawMessage) error {
	var x struct {
		Operation  string          `json:"operation"`
		Proof      json.RawMessage `json:"proof"`
		ReceiptSeq int64           `json:"receiptSeq"`
	}
	if json.Unmarshal(raw, &x) != nil {
		return ErrConflict
	}
	var nid string
	_ = json.Unmarshal(command.NarrationID, &nid)
	if nid == "" {
		return nil
	}
	d, e := c.load(ctx, tx, command.SessionID)
	if e != nil {
		return e
	}
	if d.Plan.ID != nid || d.RunEpoch != command.RunEpoch {
		return ErrStale
	}
	old := d.Revision
	if d.StopBarrier || d.OperatorOverride {
		return ErrStopped
	}
	switch x.Operation {
	case "SEGMENT_READY", "COMMIT_INTENT":
		if e = c.fresh(ctx, tx, d); e != nil {
			return e
		}
		var segment string
		_ = json.Unmarshal(command.SegmentID, &segment)
		if command.Lane == "NARRATION" {
			s := d.Next()
			if s == nil || s.ID != segment || s.Status != "PLANNED" || d.State == SuspendRequested {
				return ErrBoundary
			}
		}
		if e = c.validateDescriptor(d, command, x.Operation, x.Proof); e != nil {
			return e
		}
		return nil
	case "COMMIT_INSTALLED":
		if e = c.fresh(ctx, tx, d); e != nil {
			return e
		}
		var id string
		_ = json.Unmarshal(command.SegmentID, &id)
		if command.Lane == "NARRATION" {
			e = d.SegmentStarted(id, old, d.RunEpoch)
		} else if command.Lane == "AUDIENCE_ANSWER" {
			if d.State != Answering || d.Turn == nil || d.Turn.Answer == nil || d.Turn.Answer.ID != id {
				return ErrBoundary
			}
			d.Turn.Answer.Status = "EXECUTING"
			d.Revision++
		} else if command.Lane == "RESUME_BRIDGE" {
			if d.State != Resuming || d.Bridge == nil || d.Bridge.ID != id {
				return ErrBoundary
			}
			d.Bridge.Status = "EXECUTING"
			d.Revision++
		}
	case "SEGMENT_COMPLETED":
		p, er := c.checkpoint(ctx, tx, command, x.Proof)
		if er != nil {
			return er
		}
		switch command.Lane {
		case "NARRATION":
			e = d.CompleteNarration(p, old, d.RunEpoch)
			if e == nil && d.State == SuspendRequested && d.SuspendInstalled {
				e = d.CommitResumePoint(p, d.Revision, d.RunEpoch)
			}
		case "AUDIENCE_ANSWER":
			e = d.CompleteAnswer(p, old, d.RunEpoch)
		case "RESUME_BRIDGE":
			e = d.CompleteBridge(p, old, d.RunEpoch)
		default:
			return ErrConflict
		}
	case "SUSPEND_REQUESTED":
		if d.State != SuspendRequested {
			return ErrBoundary
		}
		d.SuspendInstalled = true
		d.Revision++
		// The boundary can complete before Runtime installs the suspend request.
		// Persist the exact already-completed checkpoint, never a generated tail.
		if d.LastCheckpoint != nil && d.LastCheckpoint.Identity.SegmentID == d.BoundaryID {
			e = d.CommitResumePoint(*d.LastCheckpoint, d.Revision, d.RunEpoch)
		}
	case "INVALIDATE_AFTER":
		if d.State != Suspended && d.State != BridgeReady {
			return ErrBoundary
		}
		d.InvalidatedEpoch = command.TimelineEpoch
		d.Revision++
	case "BEGIN_EPOCH_ACTIVE":
		var p struct {
			Previous int64 `json:"expectedPreviousEpoch"`
			New      int64 `json:"newEpoch"`
		}
		if json.Unmarshal(x.Proof, &p) != nil {
			return ErrConflict
		}
		e = d.AdvanceEpoch(p.Previous, p.New, old, d.RunEpoch)
	case "ANSWER_PREPARED":
		if command.CommandType != "START_AUDIENCE_ANSWER" || d.Turn == nil {
			return ErrConflict
		}
		if e = c.fresh(ctx, tx, d); e != nil {
			return e
		}
		if e = expectedRevision(command, d.Revision); e != nil {
			return e
		}
		var p struct {
			Text  string   `json:"text"`
			Hash  string   `json:"productSnapshotHash"`
			Facts []string `json:"factIds"`
		}
		if json.Unmarshal(x.Proof, &p) != nil || len([]rune(p.Text)) > 100 {
			return ErrConflict
		}
		var approved struct {
			Text  string   `json:"answerText"`
			Facts []string `json:"factIds"`
		}
		if json.Unmarshal(command.Payload, &approved) != nil {
			return ErrConflict
		}
		// Only Go's fresh deterministic fact resolver can satisfy original segments.
		p.Facts = nil
		if approved.Text != "" {
			if p.Text != approved.Text {
				return ErrProduct
			}
			p.Facts = approved.Facts
			d.Turn.MappedNarrationFacts = approved.Facts
		}
		answer := Segment{ID: stable("answer", d.Turn.ID+Hash(p.Text)), Text: p.Text, TextHash: Hash(p.Text), FactIDs: p.Facts, Lane: "AUDIENCE_ANSWER", Boundary: "SENTENCE_END", Status: "PLANNED"}
		e = d.BeginAnswer(answer, p.Hash, old, d.RunEpoch, time.Now())
		if e == nil {
			e = c.save(ctx, tx, d, old)
			if e != nil {
				return e
			}
			r, er := c.Store.Current(ctx, tx, d.Plan.SessionID, false)
			if er != nil {
				return er
			}
			_, e = c.enqueueSegment(ctx, tx, r, d, answer, command.TraceID)
			return e
		}
	case "RESUME_PREPARED":
		if command.CommandType != "PREPARE_RESUME_BRIDGE" {
			return ErrConflict
		}
		if e = c.fresh(ctx, tx, d); e != nil {
			return e
		}
		if e = expectedRevision(command, d.Revision); e != nil {
			return e
		}
		var p struct {
			Choice int `json:"choice"`
		}
		if json.Unmarshal(x.Proof, &p) != nil {
			return ErrConflict
		}
		e = d.PrepareBridge(p.Choice, old, d.RunEpoch)
	case "UNKNOWN":
		d.State = RecoveryRequired
		d.Reason = "UNKNOWN_MEDIA_TAIL"
		if next := d.Next(); next != nil && next.Status == "EXECUTING" {
			next.Status = "UNKNOWN"
			d.Cursor.AmbiguousSegments = appendUnique(d.Cursor.AmbiguousSegments, next.ID)
		}
		d.Revision++
	default:
		return nil
	}
	if e != nil {
		return e
	}
	if d.Revision != old {
		return c.save(ctx, tx, d, old)
	}
	return nil
}
func factAnswer(question string, facts map[string]string) (string, []string) {
	q := strings.ToLower(question)
	parts := []string{}
	ids := []string{}
	for _, cue := range []string{"价格", "多少钱", "价钱", "售价", "price", "cost", "how much"} {
		if strings.Contains(q, cue) {
			parts = append(parts, "这款目前价格是 "+facts["price"]+" "+facts["currency"]+"。")
			ids = append(ids, "price")
			break
		}
	}
	for _, cue := range []string{"库存", "有货", "现货", "存货", "剩多少", "剩几", "stock"} {
		if strings.Contains(q, cue) {
			parts = append(parts, "目前商品整体库存还有 "+facts["stock"]+" 件，各规格单独库存暂不可用。")
			ids = append(ids, "stock")
			break
		}
	}
	if len(parts) > 0 {
		return strings.Join(parts, ""), ids
	}
	if strings.Contains(q, "名称") || strings.Contains(q, "叫什么") || strings.Contains(q, "什么商品") {
		return "这款是" + facts["name"] + "。", []string{"name"}
	}
	// Continuity answers must not inject invented dynamic/specification facts.
	// When no supported calculation exists (e.g. twenty people in an office),
	// give the exact freshly verified description plus an explicit limitation.
	// Free-form language has no authority to invent a quantity or suitability.
	description := strings.TrimSpace(facts["description"])
	if description != "" && len([]rune(description)) <= 60 {
		text := "是否适用需要结合使用频率和具体需求判断。当前商品资料说明：" + description
		if !CompleteSentence(text) {
			text += "。"
		}
		return text, []string{"description"}
	}
	return "这个问题还需要结合具体使用情况确认，现有商品资料不足以给出确定结论。", nil
}

func expectedRevision(c durability.Command, revision int64) error {
	var p struct {
		Expected *int64 `json:"expectedNarrationRevision"`
	}
	if json.Unmarshal(c.Payload, &p) != nil || p.Expected == nil || *p.Expected != revision {
		return ErrConflict
	}
	return nil
}
func (c *Controller) validateDescriptor(d Document, command durability.Command, operation string, raw json.RawMessage) error {
	var envelope struct {
		Descriptor json.RawMessage `json:"descriptor"`
		Commit     struct {
			Descriptor json.RawMessage `json:"descriptor"`
		} `json:"commit"`
	}
	if json.Unmarshal(raw, &envelope) != nil {
		return ErrConflict
	}
	descriptor := envelope.Descriptor
	if operation == "COMMIT_INTENT" {
		descriptor = envelope.Commit.Descriptor
	}
	var p struct {
		Count       int64    `json:"sampleCount"`
		SourceCount int64    `json:"sourceSampleCount"`
		SourceRate  int64    `json:"sourceSampleRate"`
		Hash        string   `json:"contentHash"`
		VideoHash   string   `json:"videoHash"`
		Frames      int      `json:"videoFrameCount"`
		Version     string   `json:"factVersion"`
		TextHash    string   `json:"textHash"`
		Facts       []string `json:"factIds"`
		Sinks       []string `json:"requiredSinks"`
		Final       bool     `json:"finalMarker"`
		Utterance   string   `json:"utteranceId"`
	}
	if json.Unmarshal(descriptor, &p) != nil || p.Count <= 0 || p.Count > 48000*8 || p.SourceRate != 16000 || p.SourceCount*3 != p.Count || p.Hash == "" || p.VideoHash == "" || p.Frames <= 0 || !p.Final || p.Version != d.Plan.ProductVersion || !sameSet(p.Sinks, d.Plan.RequiredSinks) {
		return ErrConflict
	}
	var id string
	_ = json.Unmarshal(command.SegmentID, &id)
	var segment *Segment
	for i := range d.Plan.Segments {
		if d.Plan.Segments[i].ID == id {
			segment = &d.Plan.Segments[i]
		}
	}
	if d.Turn != nil && d.Turn.Answer != nil && d.Turn.Answer.ID == id {
		segment = d.Turn.Answer
	}
	if d.Bridge != nil && d.Bridge.ID == id {
		segment = d.Bridge
	}
	if segment == nil || p.TextHash != segment.TextHash || !sameSet(p.Facts, segment.FactIDs) {
		return ErrConflict
	}
	var payload struct {
		Utterance string `json:"utteranceId"`
	}
	if json.Unmarshal(command.Payload, &payload) != nil || p.Utterance != payload.Utterance {
		return ErrConflict
	}
	return nil
}
func (c *Controller) checkpoint(ctx context.Context, tx pgx.Tx, command durability.Command, raw json.RawMessage) (Checkpoint, error) {
	var x struct {
		Identity Identity                 `json:"identity"`
		Final    Position                 `json:"finalPosition"`
		Receipts []durability.SinkReceipt `json:"sinkReceipts"`
	}
	if json.Unmarshal(raw, &x) != nil {
		return Checkpoint{}, ErrConflict
	}
	var start int64
	var rate int64
	var attempt string
	var descriptor []byte
	e := tx.QueryRow(ctx, `SELECT start_sample,sample_rate,attempt_id,descriptor_json FROM v05_timeline_commits WHERE command_id=$1 AND play_state='COMPLETED'`, command.CommandID).Scan(&start, &rate, &attempt, &descriptor)
	if e != nil {
		return Checkpoint{}, e
	}
	var desc struct {
		FactVersion string   `json:"factVersion"`
		TextHash    string   `json:"textHash"`
		Required    []string `json:"requiredSinks"`
	}
	if json.Unmarshal(descriptor, &desc) != nil {
		return Checkpoint{}, ErrConflict
	}
	p := Checkpoint{Identity: x.Identity, AttemptID: attempt, Start: Position{command.SessionID, command.RunEpoch, command.TimelineEpoch, start, rate, start * 1000000 / rate}, Final: x.Final, RequiredSinks: desc.Required, FinalMarker: true, EvidenceRef: command.CommandID + ":SEGMENT_COMPLETED", ProductVersion: desc.FactVersion, TextHash: desc.TextHash}
	for _, sink := range desc.Required {
		sr := SinkRange{Sink: sink}
		for _, receipt := range x.Receipts {
			if receipt.SinkID == sink {
				if receipt.Media == "audio" {
					sr.AudioStart = receipt.Start
					sr.AudioEnd = receipt.End
				} else if receipt.Media == "video" {
					sr.VideoStart = receipt.Start
					sr.VideoEnd = receipt.End
				}
			}
		}
		p.Sinks = append(p.Sinks, sr)
	}
	return p, nil
}

// Control runs inside the existing Session Stop/FORCE transaction. It never
// authorizes automatic resume after an operator override or ambiguous tail.
func (c *Controller) Control(ctx context.Context, tx pgx.Tx, run durability.Run, kind string) error {
	d, e := c.load(ctx, tx, run.SessionID)
	if e == pgx.ErrNoRows {
		return nil
	}
	if e != nil {
		return e
	}
	old := d.Revision
	if kind == "STOP_SESSION" {
		e = d.Stop("SESSION_STOP", old, run.Epoch)
	} else {
		if d.StopBarrier {
			return ErrStopped
		}
		d.OperatorOverride = true
		d.State = RecoveryRequired
		d.Reason = "OPERATOR_FORCE_REQUIRES_EXPLICIT_RESUME"
		d.Revision++
		if s := d.Next(); s != nil && s.Status == "EXECUTING" {
			s.Status = "UNKNOWN"
			d.Cursor.AmbiguousSegments = appendUnique(d.Cursor.AmbiguousSegments, s.ID)
		}
		if d.Turn != nil && d.Turn.Status != "COMPLETED" {
			d.Turn.Status = "INTERRUPTED"
		}
	}
	if e != nil {
		return e
	}
	return c.save(ctx, tx, d, old)
}

// AdmitOrdinary shares the Session lock transaction. Only an explicit FORCE
// may replace an active narration; it sets a sticky operator barrier first.
func (c *Controller) AdmitOrdinary(ctx context.Context, tx pgx.Tx, r durability.Run, policy string) (bool, error) {
	d, e := c.load(ctx, tx, r.SessionID)
	if e == pgx.ErrNoRows {
		return false, nil
	}
	if e != nil {
		return false, e
	}
	if d.StopBarrier {
		return false, ErrStopped
	}
	if d.OperatorOverride {
		return false, nil
	}
	if policy != "FORCE" {
		return false, ErrBoundary
	}
	return true, c.Control(ctx, tx, r, "FORCE_INTERRUPT")
}

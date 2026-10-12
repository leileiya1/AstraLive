// Package narration owns semantic progress. Provider output and queue admission
// never advance this ledger; only validated, durable required-sink proofs do.
package narration

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"strings"
	"time"
	"unicode"
	"unicode/utf8"
)

type State string

const (
	Idle             State = "IDLE"
	Planning         State = "PLANNING"
	Narrating        State = "NARRATING"
	SuspendRequested State = "SUSPEND_REQUESTED"
	Suspended        State = "SUSPENDED"
	Answering        State = "ANSWERING"
	BridgeReady      State = "BRIDGE_READY"
	Resuming         State = "RESUMING"
	Stopping         State = "STOPPING"
	Stopped          State = "STOPPED"
	RecoveryRequired State = "RECOVERY_REQUIRED"
	Failed           State = "FAILED"
)

var ErrConflict = errors.New("SEGMENT_CONFLICT")
var ErrBoundary = errors.New("BOUNDARY_CONFLICT")
var ErrStale = errors.New("STALE_RUN_EPOCH")
var ErrStopped = errors.New("RUN_SEALED")
var ErrUnknown = errors.New("RECOVERY_UNKNOWN")
var ErrExpired = errors.New("INTERACTION_EXPIRED")
var ErrProduct = errors.New("PRODUCT_VERSION_CHANGED")
var ErrDependency = errors.New("DEPENDENCY_UNAVAILABLE")

type Policy string

const (
	Never      Policy = "NEVER"
	AtBoundary Policy = "AT_BOUNDARY"
	Immediate  Policy = "IMMEDIATE"
)

// Authors map facts to whole statements. The planner does not ask an LLM to
// invent fact coverage, and does not infer completion from lexical similarity.
type Statement struct {
	Text    string   `json:"text"`
	FactIDs []string `json:"factIds"`
}
type BeatInput struct {
	Title           string      `json:"title"`
	RequiredFactIDs []string    `json:"requiredFactIds"`
	Statements      []Statement `json:"statements"`
}
type Beat struct {
	ID              string   `json:"beatId"`
	Ordinal         int      `json:"beatOrdinal"`
	Title           string   `json:"title"`
	RequiredFactIDs []string `json:"requiredFactIds"`
	SegmentIDs      []string `json:"segmentIds"`
	ProductID       string   `json:"productId"`
	FactVersion     string   `json:"factVersion"`
}
type Segment struct {
	ID             string   `json:"segmentId"`
	BeatID         string   `json:"beatId"`
	Ordinal        int      `json:"segmentOrdinal"`
	Text           string   `json:"text"`
	TextHash       string   `json:"textHash"`
	FactIDs        []string `json:"factIds"`
	DurationHintMS int      `json:"durationHintMs"`
	Boundary       string   `json:"boundary"`
	Status         string   `json:"status"`
	Lane           string   `json:"lane"`
}
type Plan struct {
	ID             string    `json:"narrationId"`
	SessionID      string    `json:"sessionId"`
	ScriptVersion  string    `json:"scriptVersion"`
	ProductID      string    `json:"productId"`
	ProductVersion string    `json:"factVersion"`
	ProductHash    string    `json:"productSnapshotHash"`
	RequiredSinks  []string  `json:"requiredSinks"`
	Policy         Policy    `json:"policy"`
	Style          string    `json:"style"`
	Beats          []Beat    `json:"beats"`
	Segments       []Segment `json:"segments"`
}
type Cursor struct {
	NextOrdinal       int      `json:"nextOrdinal"`
	CompletedSegments []string `json:"completedSegmentIds"`
	CompletedFacts    []string `json:"completedFactIds"`
	LastBoundary      string   `json:"lastCompletedSegmentId"`
	LastText          string   `json:"lastCompletedText"`
	AmbiguousSegments []string `json:"ambiguousSegmentIds"`
}
type Position struct {
	SessionID     string `json:"sessionId"`
	RunEpoch      int64  `json:"runEpoch"`
	TimelineEpoch int64  `json:"timelineEpoch"`
	SampleIndex   int64  `json:"sampleIndex"`
	SampleRate    int64  `json:"sampleRate"`
	PTSUS         int64  `json:"ptsUs"`
}
type Identity struct {
	SessionID     string `json:"sessionId"`
	RunEpoch      int64  `json:"runEpoch"`
	TimelineEpoch int64  `json:"timelineEpoch"`
	GenerationID  int64  `json:"generationId"`
	SegmentID     string `json:"segmentId"`
	UtteranceID   string `json:"utteranceId"`
	Lane          string `json:"lane"`
}
type SinkRange struct {
	Sink       string `json:"sink"`
	AudioStart int64  `json:"audioStart"`
	AudioEnd   int64  `json:"audioEnd"`
	VideoStart int64  `json:"videoStart"`
	VideoEnd   int64  `json:"videoEnd"`
}
type Checkpoint struct {
	Identity        Identity    `json:"identity"`
	AttemptID       string      `json:"attemptId"`
	Start           Position    `json:"startPosition"`
	Final           Position    `json:"finalPosition"`
	RequiredSinks   []string    `json:"requiredSinks"`
	Sinks           []SinkRange `json:"sinks"`
	FinalMarker     bool        `json:"finalMarker"`
	EvidenceRef     string      `json:"evidenceRef"`
	ProductVersion  string      `json:"factVersion"`
	TextHash        string      `json:"textHash"`
	AudienceAudible bool        `json:"audienceAudible"`
}
type ResumePoint struct {
	Revision      int64      `json:"revision"`
	Boundary      Checkpoint `json:"boundary"`
	NextBeatID    string     `json:"nextBeatId"`
	NextSegmentID string     `json:"nextSegmentId"`
	Cursor        Cursor     `json:"cursor"`
}
type Turn struct {
	ID                   string      `json:"interactionTurnId"`
	SourceIDs            []string    `json:"sourceIds"`
	SourceScope          SourceScope `json:"sourceScope"`
	Question             string      `json:"question"`
	QuestionHash         string      `json:"questionHash"`
	Priority             int         `json:"priority"`
	Deadline             time.Time   `json:"deadline"`
	SelectedAt           time.Time   `json:"selectedAt"`
	ProductHash          string      `json:"capturedProductHash"`
	Status               string      `json:"state"`
	Answer               *Segment    `json:"answer,omitempty"`
	AnswerText           string      `json:"answerText"`
	AnswerFacts          []string    `json:"answerFactIds"`
	MappedNarrationFacts []string    `json:"mappedNarrationFactIds"`
}

// Source IDs are platform.Normalize hashes over this adapter/room/session scope.
// Store the scope alongside the selected and merged IDs for durable inspection.
type SourceScope struct {
	Platform       string `json:"platform"`
	PlatformRoomID string `json:"platformRoomId"`
	InternalRoomID string `json:"internalRoomId"`
	Transport      string `json:"transport"`
}
type Document struct {
	Plan              Plan         `json:"plan"`
	State             State        `json:"state"`
	Revision          int64        `json:"narrationRevision"`
	RunEpoch          int64        `json:"runEpoch"`
	TimelineEpoch     int64        `json:"timelineEpoch"`
	Cursor            Cursor       `json:"cursor"`
	Resume            *ResumePoint `json:"resumePoint,omitempty"`
	Turn              *Turn        `json:"turn,omitempty"`
	Bridge            *Segment     `json:"bridge,omitempty"`
	StopBarrier       bool         `json:"stopBarrier"`
	OperatorOverride  bool         `json:"operatorOverride"`
	Reason            string       `json:"reason"`
	BoundaryID        string       `json:"boundarySegmentId"`
	LastCheckpoint    *Checkpoint  `json:"lastCheckpoint,omitempty"`
	RequestHash       string       `json:"requestHash"`
	SuspendInstalled  bool         `json:"suspendInstalled"`
	InvalidatedEpoch  int64        `json:"invalidatedEpoch"`
	ResumeTargetEpoch int64        `json:"resumeTargetEpoch,omitempty"`
}

func Hash(s string) string {
	v := sha256.Sum256([]byte(s))
	return "sha256:" + hex.EncodeToString(v[:])
}
func stable(prefix, seed string) string {
	return prefix + "_" + strings.TrimPrefix(Hash(seed), "sha256:")[:32]
}
func contains(xs []string, x string) bool {
	for _, s := range xs {
		if s == x {
			return true
		}
	}
	return false
}
func appendUnique(xs []string, ys ...string) []string {
	for _, y := range ys {
		if !contains(xs, y) {
			xs = append(xs, y)
		}
	}
	return xs
}
func sameSet(a, b []string) bool {
	if len(a) != len(b) {
		return false
	}
	for _, x := range a {
		if !contains(b, x) {
			return false
		}
	}
	return true
}
func validSet(xs []string) bool {
	seen := map[string]bool{}
	for _, x := range xs {
		if strings.TrimSpace(x) == "" || seen[x] {
			return false
		}
		seen[x] = true
	}
	return true
}
func (d Document) Clone() Document {
	raw, _ := json.Marshal(d)
	var v Document
	_ = json.Unmarshal(raw, &v)
	return v
}

// BuildPlan accepts semantic statements, not an arbitrary character cutter.
// Multiple complete short sentences may be packed, but prices, units, model
// names and long indivisible sentences are never sliced. TTS measured cap is
// enforced separately before commit (8 seconds maximum).
func BuildPlan(id, session, version, product, productVersion, productHash, style string, policy Policy, sinks []string, input []BeatInput) (Plan, error) {
	return buildPlan(id, session, version, product, productVersion, productHash, style, policy, sinks, input, 4000)
}

func buildPlan(id, session, version, product, productVersion, productHash, style string, policy Policy, sinks []string, input []BeatInput, packingLimit int) (Plan, error) {
	p := Plan{ID: id, SessionID: session, ScriptVersion: version, ProductID: product, ProductVersion: productVersion, ProductHash: productHash, Style: style, Policy: policy, RequiredSinks: sinks}
	if id == "" || session == "" || version == "" || product == "" || productVersion == "" || productHash == "" || len(input) == 0 || len(sinks) == 0 || !validSet(sinks) || (policy != Never && policy != AtBoundary && policy != Immediate) {
		return p, ErrConflict
	}
	globalFacts := map[string]bool{}
	for bi, b := range input {
		if strings.TrimSpace(b.Title) == "" || utf8.RuneCountInString(b.Title) > 30 || len(b.Statements) == 0 || !validSet(b.RequiredFactIDs) {
			return p, ErrConflict
		}
		beat := Beat{ID: stable("beat", id+version+fmt.Sprint(bi)), Ordinal: bi, Title: b.Title, RequiredFactIDs: b.RequiredFactIDs, ProductID: product, FactVersion: productVersion}
		covered := []string{}
		for _, stmt := range b.Statements {
			text := strings.TrimSpace(stmt.Text)
			if !CompleteSentence(text) || utf8.RuneCountInString(text) > 120 || !validSet(stmt.FactIDs) {
				return p, fmt.Errorf("%w: explicit complete semantic statement required", ErrConflict)
			}
			for _, fact := range stmt.FactIDs {
				if !contains(b.RequiredFactIDs, fact) || globalFacts[fact] {
					return p, fmt.Errorf("%w: repeated or undeclared fact", ErrConflict)
				}
				globalFacts[fact] = true
				covered = append(covered, fact)
			}
			hint := utf8.RuneCountInString(text) * 200
			// Packing uses only whole statements and remains bounded. Timing hints are
			// estimates, never proof of synthesized duration or safe interruption time.
			if n := len(p.Segments); n > 0 && len(stmt.FactIDs) == 0 && len(p.Segments[n-1].FactIDs) == 0 && p.Segments[n-1].BeatID == beat.ID && p.Segments[n-1].DurationHintMS+hint <= packingLimit {
				prev := &p.Segments[n-1]
				prev.Text += text
				prev.TextHash = Hash(prev.Text)
				prev.FactIDs = append(prev.FactIDs, stmt.FactIDs...)
				prev.DurationHintMS += hint
				prev.ID = stable("segment", id+version+fmt.Sprint(prev.Ordinal)+prev.TextHash)
				beat.SegmentIDs[len(beat.SegmentIDs)-1] = prev.ID
			} else {
				s := Segment{ID: stable("segment", id+version+fmt.Sprint(len(p.Segments))+Hash(text)), BeatID: beat.ID, Ordinal: len(p.Segments), Text: text, TextHash: Hash(text), FactIDs: stmt.FactIDs, DurationHintMS: hint, Boundary: "SENTENCE_END", Status: "PENDING", Lane: "NARRATION"}
				p.Segments = append(p.Segments, s)
				beat.SegmentIDs = append(beat.SegmentIDs, s.ID)
			}
		}
		if !sameSet(covered, b.RequiredFactIDs) {
			return p, fmt.Errorf("%w: required facts missing from plan", ErrConflict)
		}
		p.Beats = append(p.Beats, beat)
	}
	return p, nil
}
func CompleteSentence(s string) bool {
	r := []rune(strings.TrimSpace(s))
	if len(r) == 0 {
		return false
	}
	last := r[len(r)-1]
	return strings.ContainsRune("。！？!?；;", last) || last == '.' && (len(r) < 2 || !unicode.IsDigit(r[len(r)-2]))
}
func NewDocument(p Plan, run int64) Document {
	return Document{Plan: p, State: Planning, Revision: 1, RunEpoch: run, TimelineEpoch: 1}
}

// Beat progress is a deterministic projection of the SQL-backed plan/cursor,
// never a second mutable completion ledger or an LLM memory summary.
type BeatProgress struct {
	BeatID           string   `json:"beatId"`
	ProductID        string   `json:"productId"`
	FactVersion      string   `json:"factVersion"`
	RequiredFacts    []string `json:"requiredFactIds"`
	CompletedFacts   []string `json:"completedFactIds"`
	PendingFacts     []string `json:"pendingFactIds"`
	CurrentSegmentID string   `json:"currentSegmentId"`
	NextBeatID       string   `json:"nextTargetBeatId"`
	LastBoundary     string   `json:"lastCompletedSegmentId"`
}

func (d Document) Progress() []BeatProgress {
	result := make([]BeatProgress, 0, len(d.Plan.Beats))
	for i, b := range d.Plan.Beats {
		p := BeatProgress{BeatID: b.ID, ProductID: d.Plan.ProductID, FactVersion: d.Plan.ProductVersion, RequiredFacts: b.RequiredFactIDs, CompletedFacts: []string{}, PendingFacts: []string{}}
		for _, f := range b.RequiredFactIDs {
			if contains(d.Cursor.CompletedFacts, f) {
				p.CompletedFacts = append(p.CompletedFacts, f)
			} else {
				p.PendingFacts = append(p.PendingFacts, f)
			}
		}
		for _, s := range d.Plan.Segments {
			if s.BeatID != b.ID {
				continue
			}
			if s.Status == "COMPLETED" {
				p.LastBoundary = s.ID
			}
			if s.Ordinal == d.Cursor.NextOrdinal {
				p.CurrentSegmentID = s.ID
			}
		}
		if i+1 < len(d.Plan.Beats) {
			p.NextBeatID = d.Plan.Beats[i+1].ID
		}
		result = append(result, p)
	}
	return result
}
func (d Document) MarshalJSON() ([]byte, error) {
	type plain Document
	return json.Marshal(struct {
		plain
		Progress []BeatProgress `json:"beatProgress"`
	}{plain(d), d.Progress()})
}
func (d *Document) guard(rev, run int64) error {
	if d.StopBarrier || d.State == Stopped || d.State == Stopping {
		return ErrStopped
	}
	if run != d.RunEpoch {
		return ErrStale
	}
	if rev != d.Revision {
		return ErrConflict
	}
	return nil
}
func (d *Document) Next() *Segment {
	if d.Cursor.NextOrdinal >= len(d.Plan.Segments) {
		return nil
	}
	return &d.Plan.Segments[d.Cursor.NextOrdinal]
}
func (d *Document) PendingFacts() []string {
	v := []string{}
	for _, b := range d.Plan.Beats {
		for _, f := range b.RequiredFactIDs {
			if !contains(d.Cursor.CompletedFacts, f) {
				v = append(v, f)
			}
		}
	}
	return v
}
func (d *Document) PlanNext(rev, run int64) (*Segment, error) {
	if e := d.guard(rev, run); e != nil {
		return nil, e
	}
	if d.State != Planning && d.State != Narrating && d.State != Resuming {
		return nil, ErrBoundary
	}
	for d.Next() != nil && d.Next().Status == "SATISFIED_BY_ANSWER" {
		d.Cursor.NextOrdinal++
	}
	next := d.Next()
	if next == nil {
		if len(d.PendingFacts()) != 0 {
			return nil, ErrUnknown
		}
		d.State = Stopped
		d.StopBarrier = true
		d.Reason = "FINISHED"
		d.Revision++
		return nil, nil
	}
	if next.Status == "UNKNOWN" {
		return nil, ErrUnknown
	}
	if next.Status == "PENDING" {
		next.Status = "PLANNED"
		d.Revision++
	}
	return next, nil
}
func (d *Document) SegmentStarted(id string, rev, run int64) error {
	if e := d.guard(rev, run); e != nil {
		return e
	}
	s := d.Next()
	if s == nil || s.ID != id || s.Status != "PLANNED" || (d.State != Planning && d.State != Narrating && d.State != Resuming) {
		return ErrConflict
	}
	s.Status = "EXECUTING"
	d.State = Narrating
	d.Revision++
	return nil
}
func (d *Document) ValidateProof(s Segment, p Checkpoint) error {
	i := p.Identity
	if i.SessionID != d.Plan.SessionID || i.RunEpoch != d.RunEpoch || i.TimelineEpoch != d.TimelineEpoch || i.GenerationID < 1 || i.UtteranceID == "" || i.SegmentID != s.ID || i.Lane != s.Lane || p.AttemptID == "" || p.EvidenceRef == "" || !p.FinalMarker || p.TextHash != s.TextHash || p.ProductVersion != d.Plan.ProductVersion || !sameSet(p.RequiredSinks, d.Plan.RequiredSinks) {
		return ErrConflict
	}
	for _, pos := range []Position{p.Start, p.Final} {
		if pos.SessionID != i.SessionID || pos.RunEpoch != i.RunEpoch || pos.TimelineEpoch != i.TimelineEpoch || pos.SampleRate < 1 || pos.SampleIndex < 0 || pos.PTSUS != pos.SampleIndex*1000000/pos.SampleRate {
			return ErrBoundary
		}
	}
	if p.Start.SampleRate != p.Final.SampleRate || p.Final.SampleIndex <= p.Start.SampleIndex || p.Final.SampleIndex-p.Start.SampleIndex > 8*p.Start.SampleRate {
		return ErrBoundary
	}
	for _, sink := range p.RequiredSinks {
		n := 0
		for _, v := range p.Sinks {
			if v.Sink == sink {
				n++
				if v.AudioStart != p.Start.SampleIndex || v.VideoStart != p.Start.SampleIndex || v.AudioEnd != p.Final.SampleIndex || v.VideoEnd != p.Final.SampleIndex {
					return ErrBoundary
				}
			}
		}
		if n != 1 {
			return ErrBoundary
		}
	}
	return nil
}
func (d *Document) CompleteNarration(p Checkpoint, rev, run int64) error {
	if e := d.guard(rev, run); e != nil {
		return e
	}
	s := d.Next()
	if s == nil || s.Status != "EXECUTING" || (d.State != Narrating && d.State != SuspendRequested) {
		return ErrBoundary
	}
	if e := d.ValidateProof(*s, p); e != nil {
		return e
	}
	s.Status = "COMPLETED"
	d.Cursor.CompletedSegments = appendUnique(d.Cursor.CompletedSegments, s.ID)
	d.Cursor.CompletedFacts = appendUnique(d.Cursor.CompletedFacts, s.FactIDs...)
	d.Cursor.LastBoundary = s.ID
	d.Cursor.LastText = s.Text
	d.Cursor.NextOrdinal++
	d.LastCheckpoint = &p
	d.Revision++
	return nil
}
func (d *Document) RequestSuspend(t Turn, rev, run int64, now time.Time, manual bool) error {
	if e := d.guard(rev, run); e != nil {
		return e
	}
	if d.State != Narrating || d.OperatorOverride || d.Plan.Policy == Never {
		return ErrBoundary
	}
	if d.Plan.Policy == Immediate && !manual {
		return ErrBoundary
	}
	if t.ID == "" || len(t.SourceIDs) == 0 || !validSet(t.SourceIDs) || strings.TrimSpace(t.Question) == "" || t.QuestionHash != Hash(t.Question) || t.SelectedAt.IsZero() || !t.Deadline.After(now) || t.Deadline.Sub(t.SelectedAt) > 10*time.Minute {
		return ErrExpired
	}
	if t.ProductHash != d.Plan.ProductHash {
		return ErrProduct
	}
	next := d.Next()
	if next != nil && next.Status == "EXECUTING" {
		d.BoundaryID = next.ID
	} else if d.LastCheckpoint != nil {
		d.BoundaryID = d.LastCheckpoint.Identity.SegmentID
	} else {
		return ErrBoundary
	}
	t.Status = "SUSPEND_REQUESTED"
	d.Turn = &t
	d.SuspendInstalled = false
	d.State = SuspendRequested
	d.Revision++
	return nil
}
func (d *Document) CommitResumePoint(p Checkpoint, rev, run int64) error {
	if e := d.guard(rev, run); e != nil {
		return e
	}
	if d.State != SuspendRequested || d.LastCheckpoint == nil || d.BoundaryID != p.Identity.SegmentID || d.Cursor.LastBoundary != p.Identity.SegmentID {
		return ErrBoundary
	}
	a, _ := json.Marshal(d.LastCheckpoint)
	b, _ := json.Marshal(p)
	if string(a) != string(b) {
		return ErrBoundary
	}
	point := ResumePoint{Revision: d.Revision + 1, Boundary: p, Cursor: d.Clone().Cursor}
	if next := d.Next(); next != nil {
		point.NextBeatID = next.BeatID
		point.NextSegmentID = next.ID
	}
	d.Resume = &point
	d.State = Suspended
	d.Turn.Status = "SUSPENDED"
	d.Revision++
	return nil
}
func (d *Document) BeginAnswer(s Segment, hash string, rev, run int64, now time.Time) error {
	if e := d.guard(rev, run); e != nil {
		return e
	}
	if d.State != Suspended || d.Resume == nil || d.Turn == nil {
		return ErrBoundary
	}
	if !d.Turn.Deadline.After(now) {
		return ErrExpired
	}
	if hash != d.Plan.ProductHash || hash != d.Turn.ProductHash {
		return ErrProduct
	}
	if s.ID == "" || s.Lane != "AUDIENCE_ANSWER" || s.TextHash != Hash(s.Text) || !CompleteSentence(s.Text) {
		return ErrConflict
	}
	d.Turn.Answer = &s
	d.Turn.Status = "ANSWERING"
	d.State = Answering
	d.Revision++
	return nil
}
func (d *Document) CompleteAnswer(p Checkpoint, rev, run int64) error {
	if e := d.guard(rev, run); e != nil {
		return e
	}
	if d.State != Answering || d.Turn == nil || d.Turn.Answer == nil {
		return ErrBoundary
	}
	if e := d.ValidateProof(*d.Turn.Answer, p); e != nil {
		return e
	}
	d.Turn.AnswerText = d.Turn.Answer.Text
	d.Turn.Answer.Status = "COMPLETED"
	d.Turn.AnswerFacts = d.Turn.Answer.FactIDs
	d.Turn.Status = "COMPLETED"
	// Only an exact fresh deterministic answer is granted a mapping by Go.
	// LLM labels, generated text and partial playback are never completion proof.
	for i := d.Cursor.NextOrdinal; i < len(d.Plan.Segments); i++ {
		s := &d.Plan.Segments[i]
		covered := len(s.FactIDs) > 0
		for _, f := range s.FactIDs {
			covered = covered && contains(d.Turn.MappedNarrationFacts, f)
		}
		if covered && s.Status == "PENDING" && strings.Contains(d.Turn.AnswerText, s.Text) {
			s.Status = "SATISFIED_BY_ANSWER"
			d.Cursor.CompletedSegments = appendUnique(d.Cursor.CompletedSegments, s.ID)
			d.Cursor.CompletedFacts = appendUnique(d.Cursor.CompletedFacts, s.FactIDs...)
		}
	}
	for d.Next() != nil && d.Next().Status == "SATISFIED_BY_ANSWER" {
		d.Cursor.NextOrdinal++
	}
	if d.Resume != nil {
		d.Resume.NextBeatID = ""
		d.Resume.NextSegmentID = ""
		if n := d.Next(); n != nil {
			d.Resume.NextBeatID = n.BeatID
			d.Resume.NextSegmentID = n.ID
		}
	}
	d.Revision++
	return nil
}

// BridgeChoices are approved fact-free transition language. An LLM may choose
// wording; it cannot add prices/specs or rewrite completion. Empty is valid.
func (d *Document) BridgeChoices() []string {
	n := d.Next()
	if n == nil {
		return []string{""}
	}
	title := ""
	for _, b := range d.Plan.Beats {
		if b.ID == n.BeatID {
			title = b.Title
		}
	}
	// Authored headings may themselves contain stale/untracked claims. Only
	// neutral topic labels can enter a fact-free spoken bridge.
	switch title {
	case "商品定位", "关键功能", "容量与使用场景", "水箱容量", "售后保障", "价格与购买说明", "购买说明":
	default:
		title = "下一项讲解内容"
	}
	return []string{"", "说到这里，接下来看看" + title + "。", "这个问题也正好引出了" + title + "，我们接着往下看。"}
}
func (d *Document) PrepareBridge(choice int, rev, run int64) error {
	if e := d.guard(rev, run); e != nil {
		return e
	}
	if d.State != Answering || d.Turn == nil || d.Turn.Status != "COMPLETED" {
		return ErrBoundary
	}
	choices := d.BridgeChoices()
	if choice < 0 || choice >= len(choices) {
		return ErrConflict
	}
	text := choices[choice]
	d.Bridge = &Segment{ID: stable("bridge", d.Turn.ID+text), Text: text, TextHash: Hash(text), Lane: "RESUME_BRIDGE", Boundary: "SENTENCE_END", Status: "PLANNED"}
	d.State = BridgeReady
	d.Revision++
	return nil
}
func (d *Document) ResumeNarration(rev, run, pointRevision int64) error {
	if e := d.guard(rev, run); e != nil {
		return e
	}
	if d.State != BridgeReady || d.Resume == nil || d.Resume.Revision != pointRevision {
		return ErrBoundary
	}
	if n := d.Next(); n != nil && n.ID != d.Resume.NextSegmentID {
		return ErrConflict
	}
	d.State = Resuming
	d.Revision++
	return nil
}
func (d *Document) CompleteBridge(p Checkpoint, rev, run int64) error {
	if e := d.guard(rev, run); e != nil {
		return e
	}
	if d.State != Resuming || d.Bridge == nil || d.Bridge.Text == "" {
		return ErrBoundary
	}
	if e := d.ValidateProof(*d.Bridge, p); e != nil {
		return e
	}
	d.Bridge.Status = "COMPLETED"
	d.Revision++
	return nil
}
func (d *Document) AdvanceEpoch(previous, next, rev, run int64) error {
	if e := d.guard(rev, run); e != nil {
		return e
	}
	if previous != d.TimelineEpoch || next != previous+1 || next > 9007199254740991 {
		return ErrConflict
	}
	if d.State != Suspended && d.State != BridgeReady {
		return ErrBoundary
	}
	d.TimelineEpoch = next
	d.Revision++
	return nil
}
func (d *Document) Stop(reason string, rev, run int64) error {
	if d.StopBarrier && d.State == Stopped {
		return nil
	}
	if run != d.RunEpoch {
		return ErrStale
	}
	if rev != d.Revision {
		return ErrConflict
	}
	d.StopBarrier = true
	d.State = Stopping
	d.Reason = reason
	for i := range d.Plan.Segments {
		if d.Plan.Segments[i].Status != "COMPLETED" && d.Plan.Segments[i].Status != "SATISFIED_BY_ANSWER" {
			d.Plan.Segments[i].Status = "CANCELLED"
		}
	}
	if d.Turn != nil && d.Turn.Status != "COMPLETED" {
		d.Turn.Status = "CANCELLED"
	}
	d.Revision++
	return nil
}
func (d *Document) Recover(newRun int64) error {
	if d.StopBarrier {
		return ErrStopped
	}
	if newRun <= d.RunEpoch {
		return ErrStale
	}
	d.RunEpoch = newRun
	d.TimelineEpoch = 1
	d.State = RecoveryRequired
	d.Reason = "RECONCILE_REQUIRED_SINKS"
	for i := range d.Plan.Segments {
		s := &d.Plan.Segments[i]
		if s.Status == "EXECUTING" {
			s.Status = "UNKNOWN"
			d.Cursor.AmbiguousSegments = appendUnique(d.Cursor.AmbiguousSegments, s.ID)
		}
	}
	if d.Turn != nil && d.Turn.Status != "COMPLETED" {
		d.Turn.Status = "UNKNOWN"
		if d.Turn.Answer != nil && d.Turn.Answer.Status == "EXECUTING" {
			d.Turn.Answer.Status = "UNKNOWN"
			d.Cursor.AmbiguousSegments = appendUnique(d.Cursor.AmbiguousSegments, d.Turn.Answer.ID)
		}
	}
	if d.Bridge != nil && d.Bridge.Status == "EXECUTING" {
		d.Bridge.Status = "UNKNOWN"
		d.Cursor.AmbiguousSegments = appendUnique(d.Cursor.AmbiguousSegments, d.Bridge.ID)
	}
	d.Revision++
	return nil
}

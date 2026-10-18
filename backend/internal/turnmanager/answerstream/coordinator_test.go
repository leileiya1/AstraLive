package answerstream

import (
	cp "astralive/backend/internal/contentplan"
	domain "astralive/backend/internal/contentplan/answerstream"
	"context"
	"errors"
	"io"
	"sync"
	"sync/atomic"
	"testing"
	"time"
)

// All peers below are explicit CPU/Mock domain seams. They do NOT implement
// v2 DTOs, SQL, ticket authentication, fsync, media drain or real TTS.
var now = time.Date(2026, 10, 17, 0, 0, 0, 0, time.UTC)

const reply = "这款的价格是129.90元。这款有XL和XXL尺码。"

type mockSource struct {
	tokens []rune
	reads  atomic.Int32
	closed atomic.Int32
}

func (s *mockSource) Next(ctx context.Context) (string, error) {
	s.reads.Add(1)
	if e := ctx.Err(); e != nil {
		return "", e
	}
	if len(s.tokens) == 0 {
		return "", io.EOF
	}
	r := s.tokens[0]
	s.tokens = s.tokens[1:]
	return string(r), nil
}
func (s *mockSource) Close() error { s.closed.Add(1); return nil }

type channelSource struct {
	chunks  chan string
	done    chan struct{}
	once    sync.Once
	reads   atomic.Int32
	entered chan struct{}
}

func (s *channelSource) Next(ctx context.Context) (string, error) {
	s.reads.Add(1)
	if s.entered != nil {
		select {
		case s.entered <- struct{}{}:
		default:
		}
	}
	select {
	case <-ctx.Done():
		return "", ctx.Err()
	case <-s.done:
		return "", context.Canceled
	case text, ok := <-s.chunks:
		if !ok {
			return "", io.EOF
		}
		return text, nil
	}
}
func (s *channelSource) Close() error { s.once.Do(func() { close(s.done) }); return nil }

type mockFacts struct{}

func (mockFacts) Observe(_ context.Context, _ domain.Binding, f []domain.Dependency) ([]domain.Dependency, error) {
	return append([]domain.Dependency(nil), f...), nil
}

type mockEncoding struct{}

func (mockEncoding) Encode(d domain.Draft) ([]byte, error) {
	// Deliberately NOT an AnswerArtifact wire object: tests distinguish pure
	// domain coordination from formal encoder/Authority interoperability.
	return cp.Canonical(map[string]any{"testOnly": true, "text": d.Text, "textHash": d.TextHash, "previous": d.PreviousHash, "sequence": d.Sequence, "id": d.ID})
}

type mockPeers struct {
	mu                                                   sync.Mutex
	prepared                                             []domain.Artifact
	started, continuations, tts, commits, seals, latches int
	drains                                               map[string]bool
	consumed                                             map[string]bool
	changed, expired, noProof                            bool
	lost                                                 string
	lostPrepare                                          bool
	beforePrepare, beforeConsume, beforeDrain            func()
}

func (p *mockPeers) Check(ctx context.Context, a domain.Artifact) error {
	if e := ctx.Err(); e != nil {
		return e
	}
	p.mu.Lock()
	defer p.mu.Unlock()
	if p.changed || p.expired {
		return domain.ErrFacts
	}
	return nil
}
func (p *mockPeers) Prepare(ctx context.Context, a domain.Artifact) error {
	if p.beforePrepare != nil {
		p.beforePrepare()
	}
	if e := p.Check(ctx, a); e != nil {
		return e
	}
	p.mu.Lock()
	defer p.mu.Unlock()
	for _, old := range p.prepared {
		if old.Draft().ID == a.Draft().ID {
			if old.Hash() != a.Hash() {
				return errors.New("descriptor conflict")
			}
			return nil
		}
	}
	p.prepared = append(p.prepared, a)
	if p.lostPrepare {
		p.lostPrepare = false
		return ErrPrepareUncertain
	}
	return nil
}
func (p *mockPeers) Start(ctx context.Context, a domain.Artifact, m StartMode) error {
	if e := p.Check(ctx, a); e != nil {
		return e
	}
	p.mu.Lock()
	defer p.mu.Unlock()
	if m == First {
		if p.started > 0 {
			return errors.New("duplicate global START")
		}
		p.started++
	} else {
		if a.Draft().Sequence < 2 || !p.drains[a.Draft().PreviousHash] {
			return errors.New("untrusted predecessor")
		}
		p.continuations++
	}
	if p.lost == "start" && m == First || p.lost == "continuation" && m == Continuation {
		return errors.New("ACK lost")
	}
	return nil
}
func (p *mockPeers) ConsumeOnce(ctx context.Context, a domain.Artifact) error {
	if p.beforeConsume != nil {
		p.beforeConsume()
	}
	if e := p.Check(ctx, a); e != nil {
		return e
	}
	p.mu.Lock()
	defer p.mu.Unlock()
	if p.consumed[a.Hash()] {
		return errors.New("duplicate consume")
	}
	p.consumed[a.Hash()] = true
	p.latches++
	if p.lost == "consume" {
		return errors.New("Backend consumed, Guardian ACK lost")
	}
	p.tts++
	return nil
}
func (p *mockPeers) ConfirmDrain(ctx context.Context, a domain.Artifact) error {
	if p.beforeDrain != nil {
		p.beforeDrain()
	}
	if e := p.Check(ctx, a); e != nil {
		return e
	}
	p.mu.Lock()
	defer p.mu.Unlock()
	if p.noProof {
		return errors.New("required range missing")
	}
	p.drains[a.Hash()] = true
	return nil
}
func (p *mockPeers) Seal(ctx context.Context, s domain.Summary) error {
	if e := ctx.Err(); e != nil {
		return e
	}
	p.mu.Lock()
	defer p.mu.Unlock()
	text := ""
	if len(s.Entries) != len(p.prepared) {
		return errors.New("manifest size mismatch")
	}
	for i, a := range p.prepared {
		if s.Entries[i].Digest != a.Hash() {
			return errors.New("manifest hash mismatch")
		}
		text += a.Draft().Text
	}
	if s.TextHash != cp.Hash(text) {
		return errors.New("full actual text hash mismatch")
	}
	p.seals++
	return nil
}
func (p *mockPeers) Commit(ctx context.Context, s domain.Summary) error {
	if e := ctx.Err(); e != nil {
		return e
	}
	p.mu.Lock()
	defer p.mu.Unlock()
	if p.seals != 1 {
		return errors.New("missing seal")
	}
	for _, entry := range s.Entries {
		if !p.drains[entry.Digest] {
			return errors.New("missing drain")
		}
	}
	p.commits++
	return nil
}
func harness(t *testing.T, source domain.Source) (*Coordinator, *mockPeers) {
	t.Helper()
	deps := func(kind string) []domain.Dependency {
		return []domain.Dependency{{Kind: kind, Product: "product", Version: "version", Digest: cp.Hash(kind), Verified: now, Expires: now.Add(2 * time.Second)}}
	}
	l, e := domain.NewLanguage([]domain.Rule{{Clause: "这款的价格是129.90元", Dependencies: deps("PRICE")}, {Clause: "这款有XL和XXL尺码", Dependencies: deps("SIZE_OPTIONS")}})
	if e != nil {
		t.Fatal(e)
	}
	b, e := domain.NewBuilder(domain.Binding{Tenant: "tenant", Owner: "owner", Run: "run", Session: "session", Command: "command", Attempt: "attempt", Turn: "turn", Utterance: "utterance", Producer: "producer", Answer: "answer", Product: "product", Snapshot: cp.Hash("snapshot"), RequestHash: cp.Hash("question"), Epoch: 1, Generation: 7}, func() time.Time { return now }, mockFacts{}, mockEncoding{})
	if e != nil {
		t.Fatal(e)
	}
	p := &mockPeers{drains: map[string]bool{}, consumed: map[string]bool{}}
	c := New(context.Background(), domain.NewScanner(source, l), b, p, p)
	t.Cleanup(c.Stop)
	return c, p
}
func must(t *testing.T, e error) {
	t.Helper()
	if e != nil {
		t.Fatal(e)
	}
}
func expect(t *testing.T, e, target error) {
	t.Helper()
	if !errors.Is(e, target) {
		t.Fatalf("got %v, want %v", e, target)
	}
}

func TestWindowBackpressureSingleIdentityAndCompletionGate(t *testing.T) {
	s := &mockSource{tokens: []rune(reply)}
	c, p := harness(t, s)
	must(t, c.PrepareNext())
	reads := s.reads.Load()
	expect(t, c.PrepareNext(), ErrWindow)
	if s.reads.Load() != reads {
		t.Fatal("read second before first START")
	}
	must(t, c.StartNext())
	must(t, c.PrepareNext())
	reads = s.reads.Load()
	expect(t, c.PrepareNext(), ErrWindow)
	if s.reads.Load() != reads {
		t.Fatal("third unit read while full")
	}
	expect(t, c.StartNext(), ErrNotReady)
	expect(t, c.Complete(), ErrNotReady)
	must(t, c.Drain())
	if p.commits != 0 {
		t.Fatal("unit finish released business slot")
	}
	must(t, c.StartNext())
	expect(t, c.Complete(), ErrNotReady)
	expect(t, c.PrepareNext(), io.EOF)
	expect(t, c.Complete(), ErrNotReady)
	must(t, c.Drain())
	must(t, c.Complete())
	must(t, c.Complete())
	if p.started != 1 || p.continuations != 1 || p.tts != 2 || p.commits != 1 || p.seals != 1 {
		t.Fatalf("counts: %+v", p)
	}
	if p.prepared[0].Draft().Binding != p.prepared[1].Draft().Binding {
		t.Fatal("COMMENT identity changed")
	}
}
func TestFirstUnitBeforeProviderEOFAndLatePrepareCanRaceDrain(t *testing.T) {
	s := &channelSource{chunks: make(chan string), done: make(chan struct{}), entered: make(chan struct{}, 4)}
	c, p := harness(t, s)
	result := make(chan error, 1)
	go func() { result <- c.PrepareNext() }()
	<-s.entered
	s.chunks <- "这款的价格是129.90元。"
	must(t, <-result)
	must(t, c.StartNext())
	if p.tts != 1 || c.View().Sealed {
		t.Fatal("EOF gate")
	}
	go func() { result <- c.PrepareNext() }()
	<-s.entered
	// Drain while Next is still waiting for a late LLM unit; there is no lock
	// held across Source.Next and no tombstone created by normal unit completion.
	must(t, c.Drain())
	if v := c.View(); v.Stopped || v.Drained != 1 || !v.Preparing {
		t.Fatal(v)
	}
	s.chunks <- "这款有XL和XXL尺码。"
	must(t, <-result)
	must(t, c.StartNext())
	must(t, c.Drain())
	close(s.chunks)
	expect(t, c.PrepareNext(), io.EOF)
	must(t, c.Complete())
	if p.started != 1 || p.tts != 2 || p.continuations != 1 {
		t.Fatal("identity/continuation regression")
	}
}
func TestPrepareACKLossRetriesSameArtifactWithoutReadingOrRegenerating(t *testing.T) {
	s := &mockSource{tokens: []rune(reply)}
	c, p := harness(t, s)
	p.lostPrepare = true
	expect(t, c.PrepareNext(), ErrPrepareUncertain)
	reads := s.reads.Load()
	first := p.prepared[0]
	must(t, c.PrepareNext())
	if s.reads.Load() != reads || len(p.prepared) != 1 || p.prepared[0].Hash() != first.Hash() {
		t.Fatal("regenerated uncertain prepare")
	}
	must(t, c.StartNext())
	if p.started != 1 || p.tts != 1 {
		t.Fatal("prepare retry repeated effect")
	}
}
func TestLostAuthorizationACKNeverRetriesOrCompletes(t *testing.T) {
	for _, where := range []string{"start", "continuation", "consume"} {
		t.Run(where, func(t *testing.T) {
			c, p := harness(t, &mockSource{tokens: []rune(reply)})
			p.lost = where
			must(t, c.PrepareNext())
			if where == "continuation" {
				must(t, c.StartNext())
				must(t, c.Drain())
				must(t, c.PrepareNext())
			}
			expect(t, c.StartNext(), ErrUnknown)
			starts, cont, tts, latches := p.started, p.continuations, p.tts, p.latches
			for _, action := range []func() error{c.StartNext, c.PrepareNext, c.Drain, c.Complete} {
				expect(t, action(), ErrUnknown)
			}
			if p.started != starts || p.continuations != cont || p.tts != tts || p.latches != latches || p.commits != 0 {
				t.Fatal("unknown replay")
			}
			if where == "consume" && (p.latches != 1 || p.tts != 0) {
				t.Fatal("consumed unknown started TTS")
			}
		})
	}
}
func TestFactChangeOrExpiryBetweenPrepareAndEffectClosesAnswer(t *testing.T) {
	for _, where := range []string{"changed", "expired"} {
		t.Run(where, func(t *testing.T) {
			c, p := harness(t, &mockSource{tokens: []rune(reply)})
			must(t, c.PrepareNext())
			must(t, c.StartNext())
			must(t, c.PrepareNext())
			must(t, c.Drain())
			p.changed = where == "changed"
			p.expired = where == "expired"
			expect(t, c.StartNext(), domain.ErrFacts)
			if !c.View().Unknown || p.continuations != 0 || p.tts != 1 || p.commits != 0 {
				t.Fatal(c.View())
			}
		})
	}
}
func TestStopUnknownAndRequiredDrainNeverAdvanceBusiness(t *testing.T) {
	for _, mode := range []string{"stop", "unknown", "missing-drain", "stop-in-consume", "stop-in-drain"} {
		t.Run(mode, func(t *testing.T) {
			c, p := harness(t, &mockSource{tokens: []rune(reply)})
			must(t, c.PrepareNext())
			switch mode {
			case "stop-in-consume":
				p.beforeConsume = c.Stop
				expect(t, c.StartNext(), ErrStopped)
			case "stop":
				must(t, c.StartNext())
				c.Stop()
			case "unknown":
				must(t, c.StartNext())
				c.Unknown()
			case "missing-drain":
				must(t, c.StartNext())
				p.noProof = true
				expect(t, c.Drain(), ErrUnknown)
			case "stop-in-drain":
				must(t, c.StartNext())
				p.beforeDrain = c.Stop
				expect(t, c.Drain(), ErrStopped)
			}
			if c.Complete() == nil || c.StartNext() == nil || c.PrepareNext() == nil || p.commits != 0 || c.View().Drained != 0 {
				t.Fatal("terminal state advanced business")
			}
		})
	}
}
func TestStopCancelsBlockedSourceAndDoesNotWaitForPrepare(t *testing.T) {
	s := &channelSource{chunks: make(chan string), done: make(chan struct{})}
	c, p := harness(t, s)
	result := make(chan error, 1)
	go func() { result <- c.PrepareNext() }()
	c.Stop()
	select {
	case e := <-result:
		expect(t, e, ErrStopped)
	case <-time.After(time.Second):
		t.Fatal("Stop didn't cancel provider")
	}
	if p.tts != 0 || p.started != 0 || p.commits != 0 {
		t.Fatal("stopped source caused effect")
	}
}
func TestConcurrentStartHasOneGlobalStartAndOnceTTS(t *testing.T) {
	c, p := harness(t, &mockSource{tokens: []rune(reply)})
	must(t, c.PrepareNext())
	var wg sync.WaitGroup
	for i := 0; i < 32; i++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			e := c.StartNext()
			if e != nil && !errors.Is(e, ErrNotReady) {
				t.Error(e)
			}
		}()
	}
	wg.Wait()
	if p.started != 1 || p.latches != 1 || p.tts != 1 {
		t.Fatal("concurrent repeated effect")
	}
}
func TestConcurrentPrepareHasOneProviderOwnerAndNoThirdUnit(t *testing.T) {
	s := &channelSource{chunks: make(chan string), done: make(chan struct{})}
	c, p := harness(t, s)
	entered, release := make(chan struct{}), make(chan struct{})
	p.beforePrepare = func() { close(entered); <-release }
	result := make(chan error, 1)
	go func() { result <- c.PrepareNext() }()
	s.chunks <- "这款的价格是129.90元。"
	<-entered
	expect(t, c.PrepareNext(), ErrBusy)
	c.Stop()
	close(release)
	expect(t, <-result, ErrStopped)
	if len(p.prepared) != 0 || p.tts != 0 {
		t.Fatal("late prepare reopened stopped stream")
	}
}
func TestUnsafeTrailingTextCannotSealOrReleaseAfterSafePrefix(t *testing.T) {
	c, p := harness(t, &mockSource{tokens: []rune("这款的价格是129.90元。如果加钱。")})
	must(t, c.PrepareNext())
	must(t, c.StartNext())
	must(t, c.Drain())
	expect(t, c.PrepareNext(), domain.ErrUnsafe)
	if p.seals != 0 || p.commits != 0 || !c.View().Unknown {
		t.Fatal("incomplete answer completed")
	}
}

func TestNewDomainInstanceCannotReplayAgainstExistingOnceAuthority(t *testing.T) {
	c1, p := harness(t, &mockSource{tokens: []rune(reply)})
	must(t, c1.PrepareNext())
	must(t, c1.StartNext())
	c1.Unknown()
	// Reconstruct ONLY domain state, retaining the same authoritative mock peer.
	// A real restart needs Agent2 reconciliation; a new Go object is no permission.
	c2, _ := harness(t, &mockSource{tokens: []rune(reply)})
	c2.executor = p
	c2.control = p
	must(t, c2.PrepareNext())
	expect(t, c2.StartNext(), ErrUnknown)
	if p.started != 1 || p.tts != 1 || p.latches != 1 || p.commits != 0 {
		t.Fatal("restart replayed already consumed answer")
	}
}

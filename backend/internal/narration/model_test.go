package narration

import (
	"encoding/json"
	"errors"
	"fmt"
	"strings"
	"testing"
	"time"
)

func fixture(t *testing.T, n int) Document {
	t.Helper()
	beats := []BeatInput{}
	for i := 0; i < n; i++ {
		beats = append(beats, BeatInput{Title: fmt.Sprintf("使用场景%c", '甲'+i), RequiredFactIDs: []string{fmt.Sprintf("fact-%d", i)}, Statements: []Statement{{Text: "这是商品的一个完整语义说明。", FactIDs: []string{fmt.Sprintf("fact-%d", i)}}}})
	}
	p, e := BuildPlan("narration", "session", "v1", "product-A", "facts-v1", "hash-A", "自然亲切", AtBoundary, []string{"preview", "rtmp"}, beats)
	if e != nil {
		t.Fatal(e)
	}
	return NewDocument(p, 1)
}
func proof(d Document, s Segment) Checkpoint {
	start := int64(s.Ordinal) * 48000
	end := start + 48000
	return Checkpoint{Identity: Identity{SessionID: d.Plan.SessionID, RunEpoch: d.RunEpoch, TimelineEpoch: d.TimelineEpoch, GenerationID: 7, SegmentID: s.ID, UtteranceID: "utt-" + s.ID, Lane: s.Lane}, AttemptID: "attempt-" + s.ID, Start: Position{d.Plan.SessionID, d.RunEpoch, d.TimelineEpoch, start, 16000, start * 1000000 / 16000}, Final: Position{d.Plan.SessionID, d.RunEpoch, d.TimelineEpoch, end, 16000, end * 1000000 / 16000}, RequiredSinks: d.Plan.RequiredSinks, Sinks: []SinkRange{{"preview", start, end, start, end}, {"rtmp", start, end, start, end}}, FinalMarker: true, EvidenceRef: "durable-commit", ProductVersion: d.Plan.ProductVersion, TextHash: s.TextHash}
}
func must(t *testing.T, e error) {
	t.Helper()
	if e != nil {
		t.Fatal(e)
	}
}
func start(t *testing.T, d *Document) Segment {
	t.Helper()
	s, e := d.PlanNext(d.Revision, d.RunEpoch)
	must(t, e)
	if s == nil {
		t.Fatal("no next segment")
	}
	v := *s
	must(t, d.SegmentStarted(v.ID, d.Revision, d.RunEpoch))
	return v
}
func selected(d Document, i int) Turn {
	return Turn{ID: fmt.Sprint("turn-", i), SourceIDs: []string{fmt.Sprint("comment-", i)}, Question: "办公室二十个人够用吗？", QuestionHash: Hash("办公室二十个人够用吗？"), Deadline: time.Now().Add(20 * time.Second), SelectedAt: time.Now(), ProductHash: d.Plan.ProductHash, Priority: 80}
}
func interruptCycle(t *testing.T, d *Document, s Segment, i int) {
	t.Helper()
	must(t, d.RequestSuspend(selected(*d, i), d.Revision, d.RunEpoch, time.Now(), false))
	p := proof(*d, s)
	must(t, d.CompleteNarration(p, d.Revision, d.RunEpoch))
	must(t, d.CommitResumePoint(p, d.Revision, d.RunEpoch))
	cursor := d.Cursor.NextOrdinal
	must(t, d.AdvanceEpoch(d.TimelineEpoch, d.TimelineEpoch+1, d.Revision, d.RunEpoch))
	a := Segment{ID: fmt.Sprint("answer-", i), Text: "需要结合使用频率判断。", TextHash: Hash("需要结合使用频率判断。"), Lane: "AUDIENCE_ANSWER"}
	must(t, d.BeginAnswer(a, d.Plan.ProductHash, d.Revision, d.RunEpoch, time.Now()))
	must(t, d.CompleteAnswer(proof(*d, a), d.Revision, d.RunEpoch))
	must(t, d.PrepareBridge(0, d.Revision, d.RunEpoch))
	must(t, d.AdvanceEpoch(d.TimelineEpoch, d.TimelineEpoch+1, d.Revision, d.RunEpoch))
	must(t, d.ResumeNarration(d.Revision, d.RunEpoch, d.Resume.Revision))
	if d.Cursor.NextOrdinal != cursor {
		t.Fatal("answer moved narration cursor")
	}
}

func TestNormalQuestionAtNaturalBoundary(t *testing.T) {
	d := fixture(t, 20)
	for i := 0; i < 3; i++ {
		s := start(t, &d)
		must(t, d.CompleteNarration(proof(d, s), d.Revision, d.RunEpoch))
	}
	s := start(t, &d)
	before := d.Cursor.NextOrdinal
	must(t, d.RequestSuspend(selected(d, 1), d.Revision, 1, time.Now(), false))
	if d.Cursor.NextOrdinal != before || d.State != SuspendRequested {
		t.Fatal("suspend advanced unplayed text")
	}
	p := proof(d, s)
	must(t, d.CompleteNarration(p, d.Revision, 1))
	must(t, d.CommitResumePoint(p, d.Revision, 1))
	if d.Resume.NextSegmentID != d.Plan.Segments[4].ID || len(d.Cursor.CompletedFacts) != 4 {
		t.Fatal("wrong resume point")
	}
}

func TestAnswerUsesFreshSupportedFactsAndDoesNotInventSuitability(t *testing.T) {
	facts := map[string]string{"price": "99.00", "currency": "CNY", "stock": "0", "name": "净水器", "description": "水箱容量五升。"}
	price, ids := factAnswer("售价多少钱？", facts)
	if price != "这款目前价格是 99.00 CNY。" || !sameSet(ids, []string{"price"}) {
		t.Fatal(price, ids)
	}
	stock, ids := factAnswer("现在有货吗？", facts)
	if !strings.Contains(stock, "库存还有 0 件") || !sameSet(ids, []string{"stock"}) {
		t.Fatal(stock, ids)
	}
	answer, ids := factAnswer("办公室二十个人够用吗？", facts)
	if !strings.Contains(answer, facts["description"]) || !strings.Contains(answer, "需要结合") || !sameSet(ids, []string{"description"}) || strings.Contains(answer, "够用") {
		t.Fatal("invented suitability", answer, ids)
	}
	delete(facts, "description")
	answer, ids = factAnswer("办公室二十个人够用吗？", facts)
	if len(ids) != 0 || !strings.Contains(answer, "不足以") {
		t.Fatal("unsupported fact completion", answer, ids)
	}
}

func TestAnswerMaySatisfyOnlyExactApprovedWholeStatement(t *testing.T) {
	d := fixture(t, 3)
	s := start(t, &d)
	must(t, d.RequestSuspend(selected(d, 1), d.Revision, 1, time.Now(), false))
	p := proof(d, s)
	must(t, d.CompleteNarration(p, d.Revision, 1))
	must(t, d.CommitResumePoint(p, d.Revision, 1))
	must(t, d.AdvanceEpoch(1, 2, d.Revision, 1))
	exact := "这款目前价格是 99.00 CNY。"
	d.Plan.Segments[1].Text = exact
	d.Plan.Segments[1].TextHash = Hash(exact)
	answer := Segment{ID: "answer", Text: exact, TextHash: Hash(exact), FactIDs: []string{"fact-1", "fact-2"}, Lane: "AUDIENCE_ANSWER"}
	must(t, d.BeginAnswer(answer, d.Plan.ProductHash, d.Revision, 1, time.Now()))
	d.Turn.MappedNarrationFacts = []string{"fact-1", "fact-2"}
	must(t, d.CompleteAnswer(proof(d, answer), d.Revision, 1))
	if d.Plan.Segments[1].Status != "SATISFIED_BY_ANSWER" || d.Plan.Segments[2].Status != "PENDING" || d.Cursor.NextOrdinal != 2 {
		t.Fatal("label alone skipped unspoken content")
	}
	if d.Resume.NextSegmentID != d.Plan.Segments[2].ID {
		t.Fatal("bridge targets satisfied fact")
	}
	must(t, d.PrepareBridge(1, d.Revision, 1))
	if !CompleteSentence(d.Bridge.Text) || len([]rune(d.Bridge.Text)) > 100 {
		t.Fatal("unbounded bridge")
	}
}
func TestFiveQuestionsNeverRecursivelyInterruptAndNoMissingFacts(t *testing.T) {
	d := fixture(t, 200)
	for i := 0; i < 200; i++ {
		s := start(t, &d)
		if i%37 == 3 && i/37 < 5 {
			interruptCycle(t, &d, s, i)
		} else {
			must(t, d.CompleteNarration(proof(d, s), d.Revision, d.RunEpoch))
		}
	}
	s, e := d.PlanNext(d.Revision, d.RunEpoch)
	must(t, e)
	if s != nil || d.Reason != "FINISHED" || len(d.Cursor.CompletedFacts) != 200 || len(d.PendingFacts()) != 0 {
		t.Fatal("lost or repeated fact")
	}
}
func TestCompletionNeedsEverySinkAndVersion(t *testing.T) {
	d := fixture(t, 2)
	s := start(t, &d)
	p := proof(d, s)
	p.Sinks[1].VideoEnd--
	if !errors.Is(d.CompleteNarration(p, d.Revision, 1), ErrBoundary) {
		t.Fatal("accepted incomplete required sink")
	}
	p = proof(d, s)
	p.ProductVersion = "old"
	if !errors.Is(d.CompleteNarration(p, d.Revision, 1), ErrConflict) {
		t.Fatal("accepted old facts")
	}
	if d.Cursor.NextOrdinal != 0 {
		t.Fatal("invalid proof advanced cursor")
	}
}
func TestNoRecursiveAnswerNoExpiredOrSwitchedProduct(t *testing.T) {
	d := fixture(t, 3)
	s := start(t, &d)
	turn := selected(d, 1)
	turn.ProductHash = "hash-B"
	if !errors.Is(d.RequestSuspend(turn, d.Revision, 1, time.Now(), false), ErrProduct) {
		t.Fatal("answered old product")
	}
	turn = selected(d, 1)
	turn.Deadline = time.Now().Add(-time.Second)
	if !errors.Is(d.RequestSuspend(turn, d.Revision, 1, time.Now(), false), ErrExpired) {
		t.Fatal("accepted expired comment")
	}
	interruptCycle(t, &d, s, 1)
	if !errors.Is(d.RequestSuspend(selected(d, 2), d.Revision, 1, time.Now(), false), ErrBoundary) {
		t.Fatal("nested answer admitted")
	}
}
func TestCrashSnapshotsNeverReplayUnknown(t *testing.T) {
	for _, state := range []State{SuspendRequested, Suspended, Answering, BridgeReady, Resuming} {
		t.Run(string(state), func(t *testing.T) {
			d := fixture(t, 3)
			s := start(t, &d)
			must(t, d.RequestSuspend(selected(d, 1), d.Revision, 1, time.Now(), false))
			if state != SuspendRequested {
				p := proof(d, s)
				must(t, d.CompleteNarration(p, d.Revision, 1))
				must(t, d.CommitResumePoint(p, d.Revision, 1))
			}
			d.State = state
			raw, _ := json.Marshal(d)
			var recovered Document
			must(t, json.Unmarshal(raw, &recovered))
			completed := len(recovered.Cursor.CompletedFacts)
			must(t, recovered.Recover(2))
			if recovered.State != RecoveryRequired || len(recovered.Cursor.CompletedFacts) != completed {
				t.Fatal("recovery lost completion")
			}
			_, e := recovered.PlanNext(recovered.Revision, 2)
			if e == nil {
				t.Fatal("blind crash replay")
			}
			if state == SuspendRequested && recovered.Plan.Segments[0].Status != "UNKNOWN" {
				t.Fatal("unproven executing segment marked retryable")
			}
		})
	}
}
func TestStopWinsAgainstBridgeResumeAndStaleRun(t *testing.T) {
	d := fixture(t, 3)
	s := start(t, &d)
	interruptCycle(t, &d, s, 1)
	must(t, d.Stop("OPERATOR_STOP", d.Revision, 1))
	if !errors.Is(d.ResumeNarration(d.Revision, 1, d.Resume.Revision), ErrStopped) {
		t.Fatal("ghost resume")
	}
	if !errors.Is(d.Recover(2), ErrStopped) {
		t.Fatal("terminal recovery")
	}
	d = fixture(t, 2)
	if !errors.Is(d.SegmentStarted("bogus", d.Revision, 0), ErrStale) {
		t.Fatal("old run admitted")
	}
}
func TestPlannerStableAndProtectsPriceUnitModel(t *testing.T) {
	input := []BeatInput{{Title: "规格", RequiredFactIDs: []string{"model", "capacity", "price"}, Statements: []Statement{{"型号是 AC-129.90。", []string{"model"}}, {"水箱容量为 500 毫升。", []string{"capacity"}}, {"参考价格为 129.90 元。", []string{"price"}}}}}
	p, e := BuildPlan("n", "s", "v", "p", "v1", "h", "style", AtBoundary, []string{"rtmp"}, input)
	must(t, e)
	q, e := BuildPlan("n", "s", "v", "p", "v1", "h", "style", AtBoundary, []string{"rtmp"}, input)
	must(t, e)
	for i, s := range p.Segments {
		if s.ID != q.Segments[i].ID || !CompleteSentence(s.Text) {
			t.Fatal("unstable or sliced segment")
		}
	}
	input[0].Statements[0].Text = "售价为 129."
	_, e = BuildPlan("n", "s", "v", "p", "v1", "h", "style", AtBoundary, []string{"rtmp"}, input)
	if e == nil {
		t.Fatal("accepted incomplete decimal")
	}
}
func TestPlannerRejectsMissingAndDuplicateRequiredFacts(t *testing.T) {
	input := []BeatInput{{Title: "容量", RequiredFactIDs: []string{"capacity", "price"}, Statements: []Statement{{"水箱容量为五百毫升。", []string{"capacity"}}}}}
	_, e := BuildPlan("n", "s", "v", "p", "v1", "h", "style", AtBoundary, []string{"rtmp"}, input)
	if e == nil {
		t.Fatal("missing fact accepted")
	}
	input[0].Statements = append(input[0].Statements, Statement{"还是五百毫升。", []string{"capacity"}})
	_, e = BuildPlan("n", "s", "v", "p", "v1", "h", "style", AtBoundary, []string{"rtmp"}, input)
	if e == nil {
		t.Fatal("duplicate fact accepted")
	}
}

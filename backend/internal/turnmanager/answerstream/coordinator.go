// Package answerstream coordinates one already-admitted COMMENT. It does not
// select/rate comments, allocate turns, own a DB, or replace the existing manager.
package answerstream

import (
	domain "astralive/backend/internal/contentplan/answerstream"
	"context"
	"errors"
	"io"
	"sync"
)

var (
	ErrWindow   = errors.New("ANSWER_WINDOW_FULL")
	ErrNotReady = errors.New("ANSWER_PREDECESSOR_NOT_DRAINED")
	ErrBusy     = errors.New("ANSWER_OPERATION_IN_FLIGHT")
	ErrStopped  = errors.New("RUN_STOPPED")
	ErrUnknown  = errors.New("ANSWER_UNKNOWN")
	// Only Prepare may retry an ambiguous ACK, with the SAME immutable descriptor.
	ErrPrepareUncertain = errors.New("PREPARE_RECEIPT_UNCERTAIN")
)

type StartMode int

const (
	First StartMode = iota
	Continuation
)

// Executor is a trusted in-process adapter seam, NOT a new wire protocol. Agent4
// must implement it using its sole generated DTO and Agent2's real Authority.
// Implementations recheck scope/Stop/epoch/Binding/fact deadlines and must honor
// cancellation. No method accepts model-authored grants, booleans or drain proof.
type Executor interface {
	Check(context.Context, domain.Artifact) error
	// Prepare resolves CAS races internally, retaining descriptor/key. Only a
	// lost PREPARE receipt may return ErrPrepareUncertain for identical retry.
	Prepare(context.Context, domain.Artifact) error
	// Start obtains a fresh Permit then FIRST true START/Continuation response.
	// Store the original secret ticket privately; never cache/query a true result.
	Start(context.Context, domain.Artifact, StartMode) error
	// ConsumeOnce implements Receiver ACK + Runtime once-TTS, not just enqueue.
	// Success has exactly one local invocation; any uncertainty is terminal here.
	// It keeps original async execution lineage and rechecks at output boundaries.
	ConsumeOnce(context.Context, domain.Artifact) error
	// ConfirmDrain waits for registered all-required ranges and Backend confirmation.
	// Local finish/PCM/queue-empty/Runtime self-report alone MUST NOT return success.
	ConfirmDrain(context.Context, domain.Artifact) error
	Seal(context.Context, domain.Summary) error
}

// Completion is owned by CONTROL, separate from Runtime's Executor privilege.
// It performs existing business completion CAS only after authoritative seal /
// all-required contiguous drains / no unknown tails. No cursor write lives here.
type Completion interface {
	Commit(context.Context, domain.Summary) error
}

type phase string

const (
	prepared phase = "PREPARED"
	starting phase = "STARTING"
	playing  phase = "PLAYING"
	draining phase = "DRAINING"
	drained  phase = "DRAINED"
)

type entry struct {
	artifact domain.Artifact
	phase    phase
}
type View struct {
	Prepared, Drained                              int
	Sealed, Completed, Stopped, Unknown, Preparing bool
}

type Coordinator struct {
	mu                                       sync.Mutex
	ctx                                      context.Context
	cancel                                   context.CancelFunc
	scanner                                  *domain.Scanner
	builder                                  *domain.Builder
	executor                                 Executor
	control                                  Completion
	entries                                  []entry // bounded audit, max32; contains text, never audio/tickets
	retry                                    *domain.Artifact
	preparing, sealed, completing, completed bool
	summary                                  domain.Summary
	terminal                                 error
	uncertain                                bool
}

// New requires one already accepted/bound COMMENT and one provider task. The
// caller retains existing Scheduler merged identity, fairness/TTL and Turn Slot.
// A single PrepareNext owner supplies pull backpressure; Drain may run while
// PrepareNext is blocked on a late provider token. No worker/queue is spawned.
func New(ctx context.Context, s *domain.Scanner, b *domain.Builder, e Executor, c Completion) *Coordinator {
	ctx, cancel := context.WithCancel(ctx)
	return &Coordinator{ctx: ctx, cancel: cancel, scanner: s, builder: b, executor: e, control: c}
}
func (c *Coordinator) current() error {
	if c.terminal != nil {
		return c.terminal
	}
	return c.ctx.Err()
}
func (c *Coordinator) abort(err error) error {
	c.mu.Lock()
	if c.terminal == nil {
		c.terminal = errors.Join(ErrUnknown, err)
	}
	c.uncertain = true
	out := c.terminal
	c.mu.Unlock()
	c.cancel()
	c.scanner.Close()
	return out
}
func (c *Coordinator) live() error { c.mu.Lock(); defer c.mu.Unlock(); return c.current() }

// Stop is an irreversible local cancellation, not a substitute for orchestrating
// Backend/Guardian ReceiverStop. Shared entrypoints must initiate those original
// Stop operations too. There is deliberately no in-memory Resume/replay method.
func (c *Coordinator) Stop() {
	c.mu.Lock()
	for _, e := range c.entries {
		if e.phase == starting || e.phase == playing || e.phase == draining {
			c.uncertain = true
		}
	}
	c.terminal = ErrStopped
	c.mu.Unlock()
	c.cancel()
	c.scanner.Close()
}
func (c *Coordinator) Unknown() { _ = c.abort(ErrUnknown) }

// PrepareNext recognizes/builds one unit, or seals at genuine provider EOF.
// Never reads ahead when the active+lookahead window is full; token queue size0.
func (c *Coordinator) PrepareNext() error {
	c.mu.Lock()
	if err := c.current(); err != nil {
		c.mu.Unlock()
		return err
	}
	if c.sealed {
		c.mu.Unlock()
		return io.EOF
	}
	if c.preparing {
		c.mu.Unlock()
		return ErrBusy
	}
	undrained := 0
	for _, e := range c.entries {
		if e.phase != drained {
			undrained++
		}
	}
	if c.retry == nil && (undrained >= 2 || len(c.entries) > 0 && (c.entries[len(c.entries)-1].phase == prepared || c.entries[len(c.entries)-1].phase == starting)) {
		c.mu.Unlock()
		return ErrWindow
	}
	c.preparing = true
	retry := c.retry
	c.mu.Unlock()
	defer func() { c.mu.Lock(); c.preparing = false; c.mu.Unlock() }()
	var a domain.Artifact
	if retry != nil {
		a = *retry
	} else {
		u, err := c.scanner.Next(c.ctx)
		if err == io.EOF {
			summary := c.builder.Summary()
			if len(summary.Entries) == 0 {
				return c.abort(domain.ErrUnsafe)
			}
			if err := c.live(); err != nil {
				return err
			}
			if err := c.executor.Seal(c.ctx, summary); err != nil {
				return c.abort(err)
			}
			c.mu.Lock()
			defer c.mu.Unlock()
			if err := c.current(); err != nil {
				return err
			}
			c.summary = summary
			c.sealed = true
			return io.EOF
		}
		if err != nil {
			return c.abort(err)
		}
		a, err = c.builder.Build(c.ctx, u)
		if err != nil {
			return c.abort(err)
		}
		c.mu.Lock()
		c.retry = &a
		c.mu.Unlock()
	}
	if err := c.live(); err != nil {
		return err
	}
	if err := c.executor.Check(c.ctx, a); err != nil {
		return c.abort(err)
	}
	if err := c.live(); err != nil {
		return err
	}
	if err := c.executor.Prepare(c.ctx, a); err != nil {
		if errors.Is(err, ErrPrepareUncertain) {
			if terminal := c.live(); terminal != nil {
				return terminal
			}
			return err
		}
		return c.abort(err)
	}
	c.mu.Lock()
	defer c.mu.Unlock()
	if err := c.current(); err != nil {
		return err
	}
	c.entries = append(c.entries, entry{a, prepared})
	c.retry = nil
	return nil
}

// StartNext emits no reusable authorization. The adapter owns private tickets,
// the Receiver latch and Runtime once-TTS. A failed START/Consume is never retried.
func (c *Coordinator) StartNext() error {
	c.mu.Lock()
	if err := c.current(); err != nil {
		c.mu.Unlock()
		return err
	}
	i := -1
	for n, e := range c.entries {
		if e.phase == prepared {
			i = n
			break
		}
	}
	if i < 0 {
		c.mu.Unlock()
		return ErrNotReady
	}
	if i > 0 && c.entries[i-1].phase != drained {
		c.mu.Unlock()
		return ErrNotReady
	}
	a := c.entries[i].artifact
	c.entries[i].phase = starting
	c.mu.Unlock()
	mode := Continuation
	if i == 0 {
		mode = First
	}
	if err := c.executor.Check(c.ctx, a); err != nil {
		return c.abort(err)
	}
	if err := c.live(); err != nil {
		return err
	}
	if err := c.executor.Start(c.ctx, a, mode); err != nil {
		return c.abort(err)
	}
	if err := c.live(); err != nil {
		return err
	}
	if err := c.executor.ConsumeOnce(c.ctx, a); err != nil {
		return c.abort(err)
	}
	c.mu.Lock()
	defer c.mu.Unlock()
	if err := c.current(); err != nil {
		return err
	}
	c.entries[i].phase = playing
	return nil
}

// Drain can race PrepareNext in either order; it never changes product cursor,
// releases the business Turn Slot, or writes a Run Stop tombstone.
func (c *Coordinator) Drain() error {
	c.mu.Lock()
	if err := c.current(); err != nil {
		c.mu.Unlock()
		return err
	}
	i := -1
	for n, e := range c.entries {
		if e.phase == playing {
			i = n
			break
		}
	}
	if i < 0 {
		c.mu.Unlock()
		return ErrNotReady
	}
	a := c.entries[i].artifact
	c.entries[i].phase = draining
	c.mu.Unlock()
	if err := c.executor.ConfirmDrain(c.ctx, a); err != nil {
		return c.abort(err)
	}
	c.mu.Lock()
	defer c.mu.Unlock()
	if err := c.current(); err != nil {
		return err
	}
	c.entries[i].phase = drained
	return nil
}

func (c *Coordinator) Complete() error {
	c.mu.Lock()
	if c.completed && c.terminal == nil {
		c.mu.Unlock()
		return nil
	}
	if err := c.current(); err != nil {
		c.mu.Unlock()
		return err
	}
	if c.completing {
		c.mu.Unlock()
		return ErrBusy
	}
	if !c.sealed || c.preparing || len(c.entries) == 0 {
		c.mu.Unlock()
		return ErrNotReady
	}
	for _, e := range c.entries {
		if e.phase != drained {
			c.mu.Unlock()
			return ErrNotReady
		}
	}
	summary := c.summary
	summary.Entries = append([]domain.ManifestEntry(nil), summary.Entries...)
	c.completing = true
	c.mu.Unlock()
	if err := c.control.Commit(c.ctx, summary); err != nil {
		return c.abort(err)
	}
	c.mu.Lock()
	defer c.mu.Unlock()
	if err := c.current(); err != nil {
		return err
	}
	c.completed = true
	c.cancel()
	return nil
}
func (c *Coordinator) View() View {
	c.mu.Lock()
	defer c.mu.Unlock()
	v := View{Prepared: len(c.entries), Sealed: c.sealed, Completed: c.completed, Stopped: errors.Is(c.terminal, ErrStopped), Unknown: c.uncertain || errors.Is(c.terminal, ErrUnknown), Preparing: c.preparing}
	for _, e := range c.entries {
		if e.phase == drained {
			v.Drained++
		}
	}
	return v
}

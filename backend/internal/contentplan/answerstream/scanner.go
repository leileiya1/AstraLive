package answerstream

import (
	"context"
	"io"
	"sync"
	"sync/atomic"
	"unicode/utf8"
)

// Source is a pull-based adapter over the existing DeepSeek stream. Its Next
// must honor ctx and Close must cancel/unblock it. The adapter must reject raw
// provider frames >16KiB BEFORE SSE/JSON decoding, and split decoded text into
// <=64-rune slices without dropping/normalizing bytes. It must not buffer a full
// response. No new LLM request, media queue or producer goroutine is created here.
type Source interface {
	Next(context.Context) (string, error)
	Close() error
}

// Scanner retains <=240 assembler runes and <=64 pending token runes. It reads
// nothing until Next is called, so downstream window pressure reaches Source.
// One caller owns Next; Close may run concurrently. There is no token queue.
type Scanner struct {
	source   Source
	language *Language
	pending  []rune
	closed   sync.Once
	stopped  atomic.Bool
	terminal error
}

func NewScanner(source Source, language *Language) *Scanner {
	return &Scanner{source: source, language: language}
}
func (s *Scanner) Close() {
	s.stopped.Store(true)
	s.closed.Do(func() {
		if s.source != nil {
			_ = s.source.Close()
		}
	})
}
func (s *Scanner) fail(err error) (Unit, error) {
	s.terminal = err
	s.pending = nil
	s.Close()
	return Unit{}, err
}
func (s *Scanner) Next(ctx context.Context) (Unit, error) {
	if s.terminal != nil {
		return Unit{}, s.terminal
	}
	if s.source == nil || s.language == nil {
		return s.fail(ErrUnsafe)
	}
	n := s.language.root
	buf := make([]rune, 0, MaxUnit)
	for {
		if s.stopped.Load() {
			return s.fail(context.Canceled)
		}
		if err := ctx.Err(); err != nil {
			return s.fail(err)
		}
		if len(s.pending) == 0 {
			chunk, err := s.source.Next(ctx)
			// Source may not combine text and error: no ignored final payload.
			if err != nil {
				if chunk != "" {
					return s.fail(ErrUnsafe)
				}
				if err == io.EOF && len(buf) > 0 {
					return s.fail(ErrUnsafe)
				}
				return s.fail(err)
			}
			if chunk == "" || len(chunk) > MaxFrameBytes || !utf8.ValidString(chunk) || utf8.RuneCountInString(chunk) > MaxSlice {
				return s.fail(ErrLimit)
			}
			s.pending = []rune(chunk)
		}
		r := s.pending[0]
		s.pending = s.pending[1:]
		if len(buf) == MaxUnit {
			return s.fail(ErrLimit)
		}
		buf = append(buf, r)
		n = n.next[r]
		if n == nil {
			return s.fail(ErrUnsafe)
		}
		if n.accept != nil {
			if s.stopped.Load() {
				return s.fail(context.Canceled)
			}
			if err := ctx.Err(); err != nil {
				return s.fail(err)
			}
			return Unit{string(buf), append([]Dependency(nil), n.accept.facts...)}, nil
		}
	}
}

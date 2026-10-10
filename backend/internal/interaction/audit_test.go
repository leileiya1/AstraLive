package interaction

import (
	"context"
	"sync"
	"testing"
)

type admissionContext struct {
	context.Context
	checked chan struct{}
	once    sync.Once
}

func (c *admissionContext) Err() error {
	err := c.Context.Err()
	c.once.Do(func() { close(c.checked) })
	return err
}

func TestAuditDistinctQuestionIntentsDoNotMerge(t *testing.T) {
	for _, pair := range [][2]string{
		{"XL 库存多少？", "XL 和 XXL 库存多少？"},
		{"商品库存多少？", "2XL 库存多少？"},
		{"商品库存多少？", "180码库存多少？"},
		{"商品库存多少？", "商品价格和库存多少？"},
		{"商品库存多少？", "商品材质和库存多少？"},
		{"价格多少？", "价格多少，怎么搭配？"},
		{"价格多少？", "商品名称和价格多少？"},
	} {
		t.Run(pair[1], func(t *testing.T) {
			s, _, _, _ := fixture(t)
			receive(t, s, event("a", "alice", pair[0]))
			receive(t, s, event("b", "bob", pair[1]))
			if v := s.Snapshot(); v.Candidates != 2 || v.Counters.Merged != 0 {
				t.Fatalf("distinct intents lost by merge: %+v", v)
			}
		})
	}
}

func TestAuditCancelDuringReceiveLockWait(t *testing.T) {
	s, _, _, _ := fixture(t)
	base, cancel := context.WithCancel(context.Background())
	ctx := &admissionContext{Context: base, checked: make(chan struct{})}
	s.mu.Lock()
	done := make(chan error, 1)
	go func() { done <- s.Receive(ctx, event("a", "alice", "多少钱？")) }()
	<-ctx.checked // first cancellation check completed, now waiting for s.mu
	cancel()
	s.mu.Unlock()
	if err := <-done; err != context.Canceled {
		t.Fatalf("cancelled replay delivery admitted: %v", err)
	}
	if s.Snapshot().Candidates != 0 {
		t.Fatal("cancelled replay queued a candidate")
	}
}

func TestFastPollDoesNotIncreaseAutomaticSpeechFrequency(t *testing.T) {
	s, now, d, _ := fixture(t)
	receive(t, s, event("poll-price", "a", "多少钱？"))
	receive(t, s, event("poll-stock", "b", "整体库存有多少？"))
	if err := s.Tick(context.Background()); err != nil {
		t.Fatal(err)
	}
	for i := 0; i < 19; i++ {
		*now = now.Add(s.config.PollInterval)
		if err := s.Tick(context.Background()); err != nil {
			t.Fatal(err)
		}
	}
	if len(d.items) != 1 {
		t.Fatal("100ms polling bypassed two-second admission interval", len(d.items))
	}
	*now = now.Add(s.config.PollInterval)
	if err := s.Tick(context.Background()); err != nil {
		t.Fatal(err)
	}
	if len(d.items) != 2 || s.Snapshot().Counters.Force != 0 {
		t.Fatal("reply interval/fence changed")
	}
}

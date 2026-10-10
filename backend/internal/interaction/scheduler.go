// Package interaction selects audience questions independently of inference/media.
package interaction

import (
	"astralive/backend/internal/ids"
	"astralive/backend/internal/platform"
	"context"
	"fmt"
	"regexp"
	"sort"
	"strings"
	"sync"
	"time"
	"unicode/utf8"
)

type Mode string

const (
	ProductExplaining  Mode = "PRODUCT_EXPLAINING"
	CommentInteraction Mode = "COMMENT_INTERACTION"
	Idle               Mode = "IDLE"
	OperatorOverride   Mode = "OPERATOR_OVERRIDE"
)

type Config struct {
	AllowPriorityPreemption                bool
	Capacity                               int
	TTL, MergeWindow, UserWindow, Interval time.Duration
	UserLimit, GlobalLimit, CacheCapacity  int
}

func DefaultConfig() Config {
	return Config{Capacity: 64, TTL: 20 * time.Second, MergeWindow: 8 * time.Second, UserWindow: 10 * time.Second, Interval: 2 * time.Second, UserLimit: 3, GlobalLimit: 100, CacheCapacity: 4096}
}
func (c Config) Validate() error {
	if c.Capacity < 1 || c.Capacity > 1000 || c.TTL <= 0 || c.MergeWindow <= 0 || c.UserWindow <= 0 || c.Interval <= 0 || c.UserLimit < 1 || c.GlobalLimit < 1 || c.CacheCapacity < c.Capacity || c.CacheCapacity > 10000 {
		return fmt.Errorf("invalid scheduler config")
	}
	return nil
}

type Selection struct {
	EstimatedReplyMS int            `json:"estimatedReplyMs"`
	Event            platform.Event `json:"event"`
	Topic            string         `json:"topic"`
	Audience         int            `json:"audience"`
	Priority         int            `json:"priority"`
	Policy           string         `json:"policy"`
	ProductID        string         `json:"productId"`
	SelectedAt       time.Time      `json:"selectedAt"`
}
type Dispatcher interface {
	Dispatch(context.Context, Selection) (string, error)
}
type Gate struct {
	CurrentSource      string
	CurrentPriority    int
	CurrentUtteranceID string
	Running, Busy      bool
	ProductID          string
}
type GateFunc func(context.Context) (Gate, error)
type Counters struct {
	Input        int `json:"input"`
	Deduplicated int `json:"deduplicated"`
	Merged       int `json:"merged"`
	Selected     int `json:"selected"`
	Expired      int `json:"expired"`
	Dropped      int `json:"dropped"`
	Filtered     int `json:"filtered"`
	Delivered    int `json:"delivered"`
	Failed       int `json:"failed"`
	Peak         int `json:"peak"`
	Force        int `json:"force"`
}
type Latency struct {
	Samples  int     `json:"samples"`
	MeanMS   float64 `json:"meanMs"`
	P50MS    float64 `json:"p50Ms"`
	P95MS    float64 `json:"p95Ms"`
	MaxMS    float64 `json:"maxMs"`
	Boundary string  `json:"boundary"`
}
type Observation struct {
	ClockDomain            string  `json:"clockDomain"`
	ReceiptAgeMS           float64 `json:"receiptAgeMs"`
	ReceiveToSelectedMS    float64 `json:"receiveToSelectedMs"`
	ReceiveToDispatchAckMS float64 `json:"receiveToDispatchAckMs"`
}
type Snapshot struct {
	Observation *Observation     `json:"observation,omitempty"`
	Mode        Mode             `json:"mode"`
	Candidates  int              `json:"candidates"`
	Counters    Counters         `json:"counters"`
	Recent      []platform.Event `json:"recent"`
	Current     *Selection       `json:"current,omitempty"`
	UtteranceID string           `json:"utteranceId,omitempty"`
	LastError   string           `json:"lastError,omitempty"`
	Stopped     bool             `json:"stopped"`
	Latency     Latency          `json:"latency"`
}
type window struct {
	At    time.Time
	Count int
}
type Limiter struct {
	mu      sync.Mutex
	current window
}

func (l *Limiter) allow(now time.Time, limit int) bool {
	l.mu.Lock()
	defer l.mu.Unlock()
	if now.Sub(l.current.At) >= time.Second {
		l.current = window{At: now}
	}
	if l.current.Count >= limit {
		return false
	}
	l.current.Count++
	return true
}

type candidate struct {
	selection Selection
	users     map[string]bool
}
type Scheduler struct {
	dispatchAckMS        float64
	resumeMode           Mode
	mu                   sync.Mutex
	config               Config
	mapping              platform.Mapping
	product              string
	now                  func() time.Time
	dispatch             Dispatcher
	gate                 GateFunc
	limiter              *Limiter
	mode                 Mode
	stopped, inFlight    bool
	queue                []*candidate
	seen                 map[string]time.Time
	repeats              map[string]time.Time
	users                map[string]window
	served               map[string]time.Time
	counters             Counters
	recent               []platform.Event
	current              *Selection
	utterance, lastError string
	latencies            []float64
	lastSelected         time.Time
}

func New(c Config, m platform.Mapping, product string, d Dispatcher, g GateFunc, clock func() time.Time, l *Limiter) (*Scheduler, error) {
	if err := c.Validate(); err != nil {
		return nil, err
	}
	if clock == nil {
		clock = time.Now
	}
	if l == nil {
		l = &Limiter{}
	}
	return &Scheduler{config: c, mapping: m, product: product, now: clock, dispatch: d, gate: g, limiter: l, mode: Idle, seen: map[string]time.Time{}, repeats: map[string]time.Time{}, users: map[string]window{}, served: map[string]time.Time{}}, nil
}

var sizeRE = regexp.MustCompile(`(?i)(?:[2-5]xl|x{1,4}l|xs|s|m|l|[0-9]{1,3}\s*(?:码|号))`)

// Go regexp has no lookaround. Validate boundaries without consuming them so
// adjacent labels (XL/XXL) are all recognized; model IDs such as AB-2XL-Pro stay
// outside size classification. Multiple facts keep the complete question key.
func sizesIn(text string) []string {
	var sizes []string
	seen := map[string]bool{}
	for _, span := range sizeRE.FindAllStringIndex(text, -1) {
		word := func(b byte) bool { return b >= 'a' && b <= 'z' || b >= '0' && b <= '9' || b == '-' || b == '_' }
		if span[0] > 0 && word(text[span[0]-1]) || span[1] < len(text) && word(text[span[1]]) {
			continue
		}
		size := strings.TrimSpace(strings.TrimSuffix(strings.TrimSuffix(strings.ToUpper(text[span[0]:span[1]]), "码"), "号"))
		if !seen[size] {
			sizes = append(sizes, size)
			seen[size] = true
		}
	}
	return sizes
}

func Topic(text string) (string, bool, bool) {
	lower := strings.ToLower(text)
	sizes := sizesIn(lower)
	stock := contains(lower, "库存", "有货", "现货", "存货", "剩多少", "剩几", "stock")
	price := contains(lower, "价格", "多少钱", "价钱", "售价", "price")
	name := contains(lower, "名称", "叫什么", "什么商品")
	details := contains(lower, "材质", "面料", "规格", "尺寸", "型号", "描述", "成分", "洗", "品牌", "适合", "推荐", "怎么", "如何", "区别", "比较", "搭配", "身高", "体重", "和", "以及", "同时", "另外")
	question := contains(lower, "?", "？", "吗", "么", "多少", "什么", "怎么", "如何", "是否") ||
		contains(lower, "帮我", "帮我们", "请介绍", "请推荐", "请说", "请讲", "请回答", "请解释", "请比较", "请帮")
	if len(sizes) > 1 || price && (stock || len(sizes) > 0 || name) || name && stock || details && (stock || price || len(sizes) > 0 || name) {
		return "product:" + strings.TrimSpace(lower), true, question
	}
	if len(sizes) == 1 {
		size := sizes[0]
		if stock {
			return "size_stock:" + size, true, true
		}
		if contains(lower, "有", "提供", "尺码", "可选", "码") {
			return "size_option:" + size, true, true
		}
	}
	if stock {
		return "overall_stock", true, true
	}
	if price {
		return "price", true, true
	}
	if name {
		return "name", true, true
	}
	if contains(lower, "材质", "规格", "尺寸", "尺码", "商品", "产品") {
		return "product:" + strings.TrimSpace(lower), true, question
	}
	return "chat:" + strings.TrimSpace(lower), false, question
}
func contains(s string, words ...string) bool {
	for _, w := range words {
		if strings.Contains(s, w) {
			return true
		}
	}
	return false
}
func (s *Scheduler) prune(now time.Time) {
	kept := s.queue[:0]
	for _, c := range s.queue {
		if now.Sub(c.selection.Event.ReceivedAt) >= s.config.TTL {
			s.counters.Expired++
			outcomes.WithLabelValues("expired").Inc()
		} else {
			kept = append(kept, c)
		}
	}
	s.queue = kept
	for k, t := range s.seen {
		if now.Sub(t) >= 2*s.config.TTL {
			delete(s.seen, k)
		}
	}
	for k, t := range s.repeats {
		if now.Sub(t) >= s.config.MergeWindow {
			delete(s.repeats, k)
		}
	}
	for k, w := range s.users {
		if now.Sub(w.At) >= s.config.UserWindow {
			delete(s.users, k)
		}
	}
	for k, t := range s.served {
		if now.Sub(t) >= 2*s.config.TTL {
			delete(s.served, k)
		}
	}
}
func (s *Scheduler) Receive(ctx context.Context, e platform.Event) error {
	if err := ctx.Err(); err != nil {
		return err
	}
	s.mu.Lock()
	defer s.mu.Unlock()
	if err := ctx.Err(); err != nil {
		return err
	}
	s.counters.Input++
	outcomes.WithLabelValues("input").Inc()
	if s.stopped {
		s.counters.Dropped++
		outcomes.WithLabelValues("dropped").Inc()
		return nil
	}
	now := s.now()
	s.prune(now)
	normalized, err := platform.Normalize(e, s.mapping, now)
	if err != nil {
		s.counters.Filtered++
		outcomes.WithLabelValues("filtered").Inc()
		return err
	}
	e = normalized
	if e.EventID != "" {
		if _, ok := s.seen[e.EventID]; ok {
			s.counters.Deduplicated++
			outcomes.WithLabelValues("deduplicated").Inc()
			return nil
		}
		if len(s.seen) >= s.config.CacheCapacity {
			s.counters.Dropped++
			outcomes.WithLabelValues("dropped").Inc()
			return nil
		}
		s.seen[e.EventID] = now
	} else {
		e.EventID = ids.New("receipt")
		e.TraceID = ids.New("trace")
	}
	repeat := e.UserExternalID + "\x00" + strings.ToLower(e.Content)
	if _, ok := s.repeats[repeat]; ok {
		s.counters.Deduplicated++
		outcomes.WithLabelValues("deduplicated").Inc()
		return nil
	}
	if len(s.repeats) >= s.config.CacheCapacity {
		s.counters.Dropped++
		outcomes.WithLabelValues("dropped").Inc()
		return nil
	}
	s.repeats[repeat] = now
	w := s.users[e.UserExternalID]
	if now.Sub(w.At) >= s.config.UserWindow {
		w = window{At: now}
	}
	if w.Count >= s.config.UserLimit || (len(s.users) >= s.config.CacheCapacity && w.Count == 0) || !s.limiter.allow(now, s.config.GlobalLimit) {
		s.counters.Dropped++
		outcomes.WithLabelValues("dropped").Inc()
		return nil
	}
	w.Count++
	s.users[e.UserExternalID] = w
	s.recent = append(s.recent, e)
	if len(s.recent) > 20 {
		s.recent = s.recent[1:]
	}
	topic, product, question := Topic(e.Content)
	if !question && !product && !contains(e.Content, "你好", "谢谢", "hello") {
		s.counters.Filtered++
		outcomes.WithLabelValues("filtered").Inc()
		return nil
	}
	for _, c := range s.queue {
		if c.selection.Topic == topic && now.Sub(c.selection.Event.ReceivedAt) < s.config.MergeWindow {
			if len(c.users) < 128 {
				c.users[e.UserExternalID] = true
			}
			c.selection.Audience = len(c.users)
			s.counters.Merged++
			outcomes.WithLabelValues("merged").Inc()
			return nil
		}
	}
	if len(s.queue) >= s.config.Capacity {
		s.counters.Dropped++
		outcomes.WithLabelValues("dropped").Inc()
		return nil
	}
	priority := 40
	if question {
		priority += 10
	}
	if product {
		priority += 30
	}
	selection := Selection{Event: e, Topic: topic, Audience: 1, Priority: priority, Policy: "NONE", ProductID: s.product, EstimatedReplyMS: estimate(topic)}
	s.queue = append(s.queue, &candidate{selection, map[string]bool{e.UserExternalID: true}})
	if len(s.queue) > s.counters.Peak {
		s.counters.Peak = len(s.queue)
	}
	return nil
}

// Tick reserves at most one selection. No automatic FORCE; sentence boundaries use
// the existing utterance completion/drain boundary. Explicit operator resume required.
func (s *Scheduler) Tick(ctx context.Context) error {
	s.mu.Lock()
	defer s.mu.Unlock()
	now := s.now()
	s.prune(now)
	if s.stopped || s.inFlight || s.mode == OperatorOverride || now.Sub(s.lastSelected) < s.config.Interval {
		return nil
	}
	gate, err := s.gate(ctx)
	if err != nil {
		s.lastError = "GATE_UNAVAILABLE"
		return err
	}
	if !gate.Running {
		s.stopLocked()
		return nil
	}
	if !gate.Busy && s.mode == CommentInteraction {
		s.mode = s.resumeMode
		if s.mode == "" {
			s.mode = Idle
		}
	}
	if gate.ProductID != s.product {
		s.counters.Dropped += len(s.queue)
		outcomes.WithLabelValues("dropped").Add(float64(len(s.queue)))
		s.queue = nil
		s.mode = OperatorOverride
		s.lastError = "PRODUCT_CHANGED_NEW_SESSION_REQUIRED"
		return nil
	}
	if len(s.queue) == 0 {
		return nil
	}
	score := func(c *candidate) int {
		n := c.selection.Priority + min(c.selection.Audience-1, 5)*4
		if _, ok := s.served[c.selection.Event.UserExternalID]; ok {
			n -= 45
		}
		n -= c.selection.EstimatedReplyMS / 1000
		n -= utf8.RuneCountInString(c.selection.Event.Content) / 20
		n += int(now.Sub(c.selection.Event.ReceivedAt) / time.Second)
		return n
	}
	best := 0
	for i := 1; i < len(s.queue); i++ {
		if score(s.queue[i]) > score(s.queue[best]) {
			best = i
		}
	}
	chosen := s.queue[best].selection
	preempting := false
	if gate.Busy {
		if !s.config.AllowPriorityPreemption || s.mode != ProductExplaining || gate.CurrentSource != "AUTO_SCRIPT" || chosen.Priority < 80 || chosen.Audience < 3 || chosen.Priority <= gate.CurrentPriority {
			return nil
		}
		chosen.Policy = "INTERRUPT_LOWER_PRIORITY"
		preempting = true
	}
	s.queue = append(s.queue[:best], s.queue[best+1:]...)
	chosen.SelectedAt = now
	selectionDelay.Observe(now.Sub(chosen.Event.ReceivedAt).Seconds())
	s.current = &chosen
	s.utterance = ""
	s.dispatchAckMS = 0
	s.lastSelected = now
	s.counters.Selected++
	outcomes.WithLabelValues("selected").Inc()
	s.inFlight = true
	previous := s.mode
	s.mode = CommentInteraction
	s.mu.Unlock()
	id, err := s.dispatch.Dispatch(ctx, chosen)
	s.mu.Lock()
	s.inFlight = false
	if !s.stopped && s.mode == CommentInteraction {
		if err != nil {
			s.mode = previous
		} else {
			s.resumeMode = previous
		}
	}
	s.utterance = id
	s.dispatchAckMS = float64(s.now().Sub(chosen.Event.ReceivedAt).Microseconds()) / 1000
	if err != nil {
		s.counters.Failed++
		outcomes.WithLabelValues("failed").Inc()
		s.lastError = "DISPATCH_FAILED_NO_AUTOMATIC_RETRY"
	} else {
		s.counters.Delivered++
		outcomes.WithLabelValues("delivered").Inc()
		s.lastError = ""
		if preempting {
			s.mode = OperatorOverride
			s.lastError = "EXPLANATION_INTERRUPTED_OPERATOR_RESUME_REQUIRED"
		}
	}
	if _, exists := s.served[chosen.Event.UserExternalID]; exists || len(s.served) < s.config.CacheCapacity {
		s.served[chosen.Event.UserExternalID] = now
	}
	s.latencies = append(s.latencies, float64(now.Sub(chosen.Event.ReceivedAt).Microseconds())/1000)
	if len(s.latencies) > 256 {
		s.latencies = s.latencies[1:]
	}
	return err
}
func (s *Scheduler) SetMode(m Mode) error {
	if m != ProductExplaining && m != CommentInteraction && m != Idle && m != OperatorOverride {
		return fmt.Errorf("invalid mode")
	}
	s.mu.Lock()
	defer s.mu.Unlock()
	if !s.stopped {
		s.mode = m
	}
	return nil
}
func (s *Scheduler) stopLocked() {
	if !s.stopped {
		s.counters.Dropped += len(s.queue)
		outcomes.WithLabelValues("dropped").Add(float64(len(s.queue)))
	}
	s.stopped = true
	s.queue = nil
	s.seen = map[string]time.Time{}
	s.users = map[string]window{}
	s.repeats = map[string]time.Time{}
	s.served = map[string]time.Time{}
	s.recent = nil
}
func (s *Scheduler) Stop() { s.mu.Lock(); defer s.mu.Unlock(); s.stopLocked() }
func (s *Scheduler) Snapshot() Snapshot {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.prune(s.now())
	v := Snapshot{Mode: s.mode, Candidates: len(s.queue), Counters: s.counters, Recent: append([]platform.Event{}, s.recent...), UtteranceID: s.utterance, LastError: s.lastError, Stopped: s.stopped}
	if s.current != nil {
		c := *s.current
		v.Current = &c
		v.Observation = &Observation{ClockDomain: "go_monotonic", ReceiptAgeMS: float64(s.now().Sub(c.Event.ReceivedAt).Microseconds()) / 1000, ReceiveToSelectedMS: float64(c.SelectedAt.Sub(c.Event.ReceivedAt).Microseconds()) / 1000, ReceiveToDispatchAckMS: s.dispatchAckMS}
	}
	v.Latency = Stats(s.latencies, "comment_received → scheduler_selected (Go monotonic; last 256 selected)")
	return v
}
func Stats(values []float64, boundary string) Latency {
	v := append([]float64{}, values...)
	sort.Float64s(v)
	r := Latency{Samples: len(v), Boundary: boundary}
	if len(v) == 0 {
		return r
	}
	for _, x := range v {
		r.MeanMS += x
	}
	r.MeanMS /= float64(len(v))
	r.P50MS = v[(len(v)*50+99)/100-1]
	r.P95MS = v[(len(v)*95+99)/100-1]
	r.MaxMS = v[len(v)-1]
	return r
}

// Initial estimates are ranking hints, not measured provider durations.
func estimate(topic string) int {
	switch {
	case topic == "price" || topic == "name" || strings.HasPrefix(topic, "size_option:"):
		return 3000
	case topic == "overall_stock" || strings.HasPrefix(topic, "size_stock:"):
		return 6000
	case strings.HasPrefix(topic, "product:"):
		return 8000
	default:
		return 4000
	}
}

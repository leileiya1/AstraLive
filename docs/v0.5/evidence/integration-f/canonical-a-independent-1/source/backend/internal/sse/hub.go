package sse

import "sync"

type Message struct {
	Name string
	Data []byte
}
type Hub struct {
	mu      sync.RWMutex
	clients map[string]map[chan Message]struct{}
}

func New() *Hub { return &Hub{clients: make(map[string]map[chan Message]struct{})} }
func (h *Hub) Subscribe(id string) (<-chan Message, func()) {
	ch := make(chan Message, 32)
	h.mu.Lock()
	if h.clients[id] == nil {
		h.clients[id] = make(map[chan Message]struct{})
	}
	h.clients[id][ch] = struct{}{}
	h.mu.Unlock()
	return ch, func() {
		h.mu.Lock()
		delete(h.clients[id], ch)
		if len(h.clients[id]) == 0 {
			delete(h.clients, id)
		}
		close(ch)
		h.mu.Unlock()
	}
}
func (h *Hub) Publish(id string, m Message) {
	h.mu.RLock()
	defer h.mu.RUnlock()
	for ch := range h.clients[id] {
		select {
		case ch <- m:
		default:
		}
	}
}

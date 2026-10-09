package httpapi

import (
	"encoding/json"
	"net/http"

	"astralive/backend/generated/dbgen"
	"astralive/backend/internal/ids"
	"github.com/go-chi/chi/v5"
	"github.com/jackc/pgx/v5/pgtype"
)

func (h *Server) createAvatar(w http.ResponseWriter, r *http.Request) {
	var v struct {
		Name   string `json:"name"`
		Engine string `json:"engine"`
	}
	if !decode(w, r, &v) {
		return
	}
	if !valid(v.Name) || !valid(v.Engine) {
		failure(w, r, 422, "INVALID_ARGUMENT", "name and engine required")
		return
	}
	a, e := h.S.Q.CreateAvatar(r.Context(), dbgen.CreateAvatarParams{ID: ids.New("avatar"), Name: v.Name, Engine: v.Engine})
	if e != nil {
		dbFail(w, r, e, "")
		return
	}
	respond(w, r, 201, avatar(a))
}
func (h *Server) listAvatars(w http.ResponseWriter, r *http.Request) {
	a, e := h.S.Q.ListAvatars(r.Context())
	if e != nil {
		dbFail(w, r, e, "")
		return
	}
	v := make([]any, 0, len(a))
	for _, x := range a {
		v = append(v, avatar(x))
	}
	respond(w, r, 200, v)
}
func (h *Server) getAvatar(w http.ResponseWriter, r *http.Request) {
	a, e := h.S.Q.GetAvatar(r.Context(), chi.URLParam(r, "avatarId"))
	if e != nil {
		dbFail(w, r, e, "AVATAR_NOT_FOUND")
		return
	}
	respond(w, r, 200, avatar(a))
}
func (h *Server) deleteAvatar(w http.ResponseWriter, r *http.Request) {
	n, e := h.S.Q.DeleteAvatar(r.Context(), chi.URLParam(r, "avatarId"))
	if e != nil {
		dbFail(w, r, e, "")
		return
	}
	if n == 0 {
		failure(w, r, 404, "AVATAR_NOT_FOUND", "avatar not found")
		return
	}
	respond(w, r, 200, map[string]any{})
}
func (h *Server) prepareAvatar(w http.ResponseWriter, r *http.Request) {
	id := chi.URLParam(r, "avatarId")
	a, e := h.S.Q.GetAvatar(r.Context(), id)
	if e != nil {
		dbFail(w, r, e, "AVATAR_NOT_FOUND")
		return
	}
	j, e := h.S.Q.CreateJob(r.Context(), dbgen.CreateJobParams{ID: ids.New("job"), Kind: "AVATAR_PREPARE", ResourceID: id})
	if e != nil {
		dbFail(w, r, e, "")
		return
	}
	if a.Engine == "MOCK" {
		_, _ = h.S.Q.SetAvatarStatus(r.Context(), dbgen.SetAvatarStatusParams{ID: id, Status: "READY"})
		_, _ = h.S.Q.CompleteJob(r.Context(), j.ID)
	}
	respond(w, r, 202, map[string]any{"jobId": j.ID, "status": "PENDING"})
}
func (h *Server) createVoice(w http.ResponseWriter, r *http.Request) {
	var v struct {
		Name            string `json:"name"`
		Provider        string `json:"provider"`
		ProviderVoiceID string `json:"providerVoiceId"`
	}
	if !decode(w, r, &v) {
		return
	}
	if !valid(v.Name) || !valid(v.Provider) || !valid(v.ProviderVoiceID) {
		failure(w, r, 422, "INVALID_ARGUMENT", "voice fields required")
		return
	}
	x, e := h.S.Q.CreateVoice(r.Context(), dbgen.CreateVoiceParams{ID: ids.New("voice"), Name: v.Name, Provider: v.Provider, ProviderVoiceID: v.ProviderVoiceID})
	if e != nil {
		dbFail(w, r, e, "")
		return
	}
	respond(w, r, 201, voice(x))
}
func (h *Server) listVoices(w http.ResponseWriter, r *http.Request) {
	a, e := h.S.Q.ListVoices(r.Context())
	if e != nil {
		dbFail(w, r, e, "")
		return
	}
	v := make([]any, 0, len(a))
	for _, x := range a {
		v = append(v, voice(x))
	}
	respond(w, r, 200, v)
}
func (h *Server) getVoice(w http.ResponseWriter, r *http.Request) {
	v, e := h.S.Q.GetVoice(r.Context(), chi.URLParam(r, "voiceId"))
	if e != nil {
		dbFail(w, r, e, "VOICE_NOT_FOUND")
		return
	}
	respond(w, r, 200, voice(v))
}
func (h *Server) deleteVoice(w http.ResponseWriter, r *http.Request) {
	n, e := h.S.Q.DeleteVoice(r.Context(), chi.URLParam(r, "voiceId"))
	if e != nil {
		dbFail(w, r, e, "")
		return
	}
	if n == 0 {
		failure(w, r, 404, "VOICE_NOT_FOUND", "voice not found")
		return
	}
	respond(w, r, 200, map[string]any{})
}
func (h *Server) createProduct(w http.ResponseWriter, r *http.Request) {
	var v productInput
	if !decode(w, r, &v) {
		return
	}
	if !v.valid() {
		failure(w, r, 422, "INVALID_ARGUMENT", "invalid product")
		return
	}
	n, e := num(v.Price)
	if e != nil {
		failure(w, r, 422, "INVALID_ARGUMENT", "invalid price")
		return
	}
	x, e := h.S.Q.CreateProduct(r.Context(), dbgen.CreateProductParams{ID: ids.New("product"), Name: v.Name, Description: v.Description, Price: n, Currency: v.Currency, Stock: v.Stock, Sizes: v.Sizes})
	if e != nil {
		dbFail(w, r, e, "")
		return
	}
	respond(w, r, 201, product(x))
}
func (h *Server) updateProduct(w http.ResponseWriter, r *http.Request) {
	var v productInput
	if !decode(w, r, &v) {
		return
	}
	if !v.valid() {
		failure(w, r, 422, "INVALID_ARGUMENT", "invalid product")
		return
	}
	n, e := num(v.Price)
	if e != nil {
		failure(w, r, 422, "INVALID_ARGUMENT", "invalid price")
		return
	}
	x, e := h.S.Q.UpdateProduct(r.Context(), dbgen.UpdateProductParams{ID: chi.URLParam(r, "productId"), Name: v.Name, Description: v.Description, Price: n, Currency: v.Currency, Stock: v.Stock, Sizes: v.Sizes})
	if e != nil {
		dbFail(w, r, e, "PRODUCT_NOT_FOUND")
		return
	}
	respond(w, r, 200, product(x))
}
func (h *Server) listProducts(w http.ResponseWriter, r *http.Request) {
	a, e := h.S.Q.ListProducts(r.Context())
	if e != nil {
		dbFail(w, r, e, "")
		return
	}
	v := make([]any, 0, len(a))
	for _, x := range a {
		v = append(v, product(x))
	}
	respond(w, r, 200, v)
}
func (h *Server) getProduct(w http.ResponseWriter, r *http.Request) {
	v, e := h.S.Q.GetProduct(r.Context(), chi.URLParam(r, "productId"))
	if e != nil {
		dbFail(w, r, e, "PRODUCT_NOT_FOUND")
		return
	}
	respond(w, r, 200, product(v))
}
func (h *Server) createKnowledge(w http.ResponseWriter, r *http.Request) {
	var m map[string]any
	if !decode(w, r, &m) {
		return
	}
	if m == nil {
		failure(w, r, 422, "INVALID_ARGUMENT", "object required")
		return
	}
	b, _ := json.Marshal(m)
	x, e := h.S.Q.CreateKnowledgeBase(r.Context(), dbgen.CreateKnowledgeBaseParams{ID: ids.New("kb"), Metadata: b})
	if e != nil {
		dbFail(w, r, e, "")
		return
	}
	m["knowledgeBaseId"] = x.ID
	respond(w, r, 201, m)
}
func (h *Server) addDocument(w http.ResponseWriter, r *http.Request) {
	id := chi.URLParam(r, "knowledgeBaseId")
	_, e := h.S.Q.GetKnowledgeBase(r.Context(), id)
	if e != nil {
		dbFail(w, r, e, "RESOURCE_NOT_FOUND")
		return
	}
	failure(w, r, 422, "INVALID_ARGUMENT", "document payload format is pending CCR")
}
func (h *Server) indexKnowledge(w http.ResponseWriter, r *http.Request) {
	id := chi.URLParam(r, "knowledgeBaseId")
	_, e := h.S.Q.GetKnowledgeBase(r.Context(), id)
	if e != nil {
		dbFail(w, r, e, "RESOURCE_NOT_FOUND")
		return
	}
	j, e := h.S.Q.CreateJob(r.Context(), dbgen.CreateJobParams{ID: ids.New("job"), Kind: "KNOWLEDGE_INDEX", ResourceID: id})
	if e != nil {
		dbFail(w, r, e, "")
		return
	}
	respond(w, r, 202, map[string]any{"jobId": j.ID, "status": j.Status})
}
func (h *Server) getJob(w http.ResponseWriter, r *http.Request) {
	j, e := h.S.Q.GetJob(r.Context(), chi.URLParam(r, "jobId"))
	if e != nil {
		dbFail(w, r, e, "RESOURCE_NOT_FOUND")
		return
	}
	respond(w, r, 200, map[string]any{"jobId": j.ID, "status": j.Status})
}
func (h *Server) checkRoomInput(w http.ResponseWriter, r *http.Request, v roomInput) bool {
	if !valid(v.Name) || !valid(v.AvatarID) || !valid(v.VoiceID) {
		failure(w, r, 422, "INVALID_ARGUMENT", "room fields required")
		return false
	}
	if _, e := h.S.Q.GetAvatar(r.Context(), v.AvatarID); e != nil {
		dbFail(w, r, e, "AVATAR_NOT_FOUND")
		return false
	}
	if _, e := h.S.Q.GetVoice(r.Context(), v.VoiceID); e != nil {
		dbFail(w, r, e, "VOICE_NOT_FOUND")
		return false
	}
	if v.KnowledgeBaseID != "" {
		if _, e := h.S.Q.GetKnowledgeBase(r.Context(), v.KnowledgeBaseID); e != nil {
			dbFail(w, r, e, "RESOURCE_NOT_FOUND")
			return false
		}
	}
	if v.ActiveProductID != "" {
		if _, e := h.S.Q.GetProduct(r.Context(), v.ActiveProductID); e != nil {
			dbFail(w, r, e, "PRODUCT_NOT_FOUND")
			return false
		}
	}
	return true
}
func (h *Server) createRoom(w http.ResponseWriter, r *http.Request) {
	var v roomInput
	if !decode(w, r, &v) || !h.checkRoomInput(w, r, v) {
		return
	}
	x, e := h.S.Q.CreateRoom(r.Context(), v.params(ids.New("room")))
	if e != nil {
		dbFail(w, r, e, "")
		return
	}
	respond(w, r, 201, room(x))
}
func (h *Server) updateRoom(w http.ResponseWriter, r *http.Request) {
	var v roomInput
	if !decode(w, r, &v) || !h.checkRoomInput(w, r, v) {
		return
	}
	x, e := h.S.Q.UpdateRoom(r.Context(), dbgen.UpdateRoomParams{ID: chi.URLParam(r, "roomId"), Name: v.Name, AvatarID: v.AvatarID, VoiceID: v.VoiceID, KnowledgeBaseID: pgtype.Text{String: v.KnowledgeBaseID, Valid: v.KnowledgeBaseID != ""}, ActiveProductID: pgtype.Text{String: v.ActiveProductID, Valid: v.ActiveProductID != ""}, SystemPrompt: v.SystemPrompt})
	if e != nil {
		dbFail(w, r, e, "ROOM_NOT_FOUND")
		return
	}
	respond(w, r, 200, room(x))
}
func (h *Server) listRooms(w http.ResponseWriter, r *http.Request) {
	a, e := h.S.Q.ListRooms(r.Context())
	if e != nil {
		dbFail(w, r, e, "")
		return
	}
	v := make([]any, 0, len(a))
	for _, x := range a {
		v = append(v, room(x))
	}
	respond(w, r, 200, v)
}
func (h *Server) getRoom(w http.ResponseWriter, r *http.Request) {
	v, e := h.S.Q.GetRoom(r.Context(), chi.URLParam(r, "roomId"))
	if e != nil {
		dbFail(w, r, e, "ROOM_NOT_FOUND")
		return
	}
	respond(w, r, 200, room(v))
}
func (h *Server) toolProduct(w http.ResponseWriter, r *http.Request) {
	v, e := h.S.Q.GetProduct(r.Context(), chi.URLParam(r, "productId"))
	if e != nil {
		dbFail(w, r, e, "PRODUCT_NOT_FOUND")
		return
	}
	_ = json.NewEncoder(w).Encode(map[string]any{"ok": true, "data": product(v)})
}
func (h *Server) toolStock(w http.ResponseWriter, r *http.Request) {
	v, e := h.S.Q.GetProduct(r.Context(), chi.URLParam(r, "productId"))
	if e != nil {
		dbFail(w, r, e, "PRODUCT_NOT_FOUND")
		return
	}
	_ = json.NewEncoder(w).Encode(map[string]any{"ok": true, "data": map[string]any{"productId": v.ID, "stock": v.Stock}})
}
func (h *Server) toolPrice(w http.ResponseWriter, r *http.Request) {
	v, e := h.S.Q.GetProduct(r.Context(), chi.URLParam(r, "productId"))
	if e != nil {
		dbFail(w, r, e, "PRODUCT_NOT_FOUND")
		return
	}
	p := product(v).(map[string]any)
	_ = json.NewEncoder(w).Encode(map[string]any{"ok": true, "data": map[string]any{"productId": v.ID, "price": p["price"]}})
}

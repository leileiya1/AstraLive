package httpapi

import (
	"bytes"
	"io"
	"net/http"
	"sync"

	"astralive/backend/generated/openapi"
	"github.com/getkin/kin-openapi/openapi3"
	"github.com/getkin/kin-openapi/openapi3filter"
	"github.com/getkin/kin-openapi/routers"
	"github.com/getkin/kin-openapi/routers/legacy"
)

var (
	contractRouter routers.Router
	contractOnce   sync.Once
	contractErr    error
)

func getContractRouter() (routers.Router, error) {
	contractOnce.Do(func() {
		data, e := openapi.Spec()
		if e != nil {
			contractErr = e
			return
		}
		doc, e := openapi3.NewLoader().LoadFromData(data)
		if e != nil {
			contractErr = e
			return
		}
		contractRouter, contractErr = legacy.NewRouter(doc)
	})
	return contractRouter, contractErr
}
func (h *Server) validateContract(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path == "/metrics" {
			next.ServeHTTP(w, r)
			return
		}
		router, e := getContractRouter()
		if e != nil {
			failure(w, r, 500, "INTERNAL_ERROR", "OpenAPI unavailable")
			return
		}
		route, params, e := router.FindRoute(r)
		if e != nil {
			next.ServeHTTP(w, r)
			return
		}
		var raw []byte
		if r.Body != nil {
			raw, e = io.ReadAll(io.LimitReader(r.Body, 1<<20))
			if e != nil {
				failure(w, r, 400, "INVALID_ARGUMENT", "invalid body")
				return
			}
			r.Body = io.NopCloser(bytes.NewReader(raw))
		}
		e = openapi3filter.ValidateRequest(r.Context(), &openapi3filter.RequestValidationInput{Request: r, PathParams: params, Route: route})
		r.Body = io.NopCloser(bytes.NewReader(raw))
		if e != nil {
			failure(w, r, 422, "INVALID_ARGUMENT", e.Error())
			return
		}
		next.ServeHTTP(w, r)
	})
}

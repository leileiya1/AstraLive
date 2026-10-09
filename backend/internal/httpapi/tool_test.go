package httpapi

import (
	"encoding/json"
	"io"
	"log/slog"
	"net/http"
	"net/http/httptest"
	"testing"
	"time"

	"astralive/backend/generated/dbgen"
	"astralive/backend/internal/app"
	"github.com/pashagolub/pgxmock/v4"
)

func TestProductToolAuthorizationAndStock(t *testing.T) {
	mock, e := pgxmock.NewPool()
	if e != nil {
		t.Fatal(e)
	}
	defer mock.Close()
	h := &Server{S: &app.Service{Q: dbgen.New(mock)}, Token: "test-token", Log: slog.New(slog.NewTextHandler(io.Discard, nil))}
	ts := httptest.NewServer(h.Router())
	defer ts.Close()
	resp, e := http.Get(ts.URL + "/internal/v1/tools/products/product_1/stock")
	if e != nil {
		t.Fatal(e)
	}
	resp.Body.Close()
	if resp.StatusCode != 401 {
		t.Fatalf("unauthorized status %d", resp.StatusCode)
	}
	rows := pgxmock.NewRows([]string{"id", "name", "description", "price", "currency", "stock", "sizes", "created_at", "updated_at"}).AddRow("product_1", "shirt", "cotton", "129.00", "CNY", int32(27), []string{"XL"}, time.Now(), time.Now())
	mock.ExpectQuery("SELECT .* FROM products WHERE id").WithArgs("product_1").WillReturnRows(rows)
	req, _ := http.NewRequest("GET", ts.URL+"/internal/v1/tools/products/product_1/stock", nil)
	req.Header.Set("Authorization", "Bearer test-token")
	resp, e = http.DefaultClient.Do(req)
	if e != nil {
		t.Fatal(e)
	}
	defer resp.Body.Close()
	var v struct {
		Ok   bool `json:"ok"`
		Data struct {
			ProductID string `json:"productId"`
			Stock     int    `json:"stock"`
		} `json:"data"`
	}
	if e = json.NewDecoder(resp.Body).Decode(&v); e != nil {
		t.Fatal(e)
	}
	if resp.StatusCode != 200 || !v.Ok || v.Data.ProductID != "product_1" || v.Data.Stock != 27 {
		t.Fatalf("status=%d body=%+v", resp.StatusCode, v)
	}
	if e = mock.ExpectationsWereMet(); e != nil {
		t.Fatal(e)
	}
}
func TestProductToolAllRoutes(t *testing.T) {
	mock, err := pgxmock.NewPool()
	if err != nil {
		t.Fatal(err)
	}
	defer mock.Close()
	h := &Server{S: &app.Service{Q: dbgen.New(mock)}, Token: "test-token", Log: slog.New(slog.NewTextHandler(io.Discard, nil))}
	ts := httptest.NewServer(h.Router())
	defer ts.Close()
	for _, tc := range []struct {
		path    string
		wantKey string
		want    any
	}{
		{"", "name", "shirt"}, {"/stock", "stock", float64(27)}, {"/price", "price", float64(129)},
	} {
		rows := pgxmock.NewRows([]string{"id", "name", "description", "price", "currency", "stock", "sizes", "created_at", "updated_at"}).AddRow("product_1", "shirt", "cotton", "129.00", "CNY", int32(27), []string{"XL"}, time.Now(), time.Now())
		mock.ExpectQuery("SELECT .* FROM products WHERE id").WithArgs("product_1").WillReturnRows(rows)
		req, _ := http.NewRequest("GET", ts.URL+"/internal/v1/tools/products/product_1"+tc.path, nil)
		req.Header.Set("Authorization", "Bearer test-token")
		resp, err := http.DefaultClient.Do(req)
		if err != nil {
			t.Fatal(err)
		}
		var result struct {
			Ok   bool           `json:"ok"`
			Data map[string]any `json:"data"`
		}
		err = json.NewDecoder(resp.Body).Decode(&result)
		resp.Body.Close()
		if err != nil || resp.StatusCode != 200 || !result.Ok || result.Data[tc.wantKey] != tc.want {
			t.Fatalf("%s status=%d result=%+v err=%v", tc.path, resp.StatusCode, result, err)
		}
	}
	if err := mock.ExpectationsWereMet(); err != nil {
		t.Fatal(err)
	}
}

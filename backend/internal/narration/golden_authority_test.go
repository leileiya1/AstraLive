package narration_test

import (
	"encoding/json"
	"net/http"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"time"

	"github.com/jackc/pgx/v5/pgxpool"
)

// F-owned, test-only passive evidence from the disposable Golden database.
// Authentication and the production handler still decide the request. Never
// serialize bindings, vaults, command payloads, credentials or SQL arguments.
func goldenAuthorityDiagnostics(next http.Handler, pool *pgxpool.Pool, out string) http.Handler {
	var mu sync.Mutex
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		parts := strings.Split(strings.Trim(r.URL.Path, "/"), "/")
		if r.Method == "POST" && len(parts) == 5 && parts[0] == "api" && parts[1] == "v0.5" && parts[2] == "narration" && parts[4] == "start" {
			var raw []byte
			err := pool.QueryRow(r.Context(), `SELECT jsonb_build_object(
 'sessionId',s.id,'sessionStatus',s.status,'roomProductId',lr.active_product_id,
 'snapshotProductId',b.room_snapshot->>'activeProductId','bindingExists',b.session_id IS NOT NULL,
 'bindingUnreleased',b.released_at IS NULL,'bindingUnexpired',b.expires_at>clock_timestamp(),
 'productExists',p.id IS NOT NULL,'productOwnerMatches',EXISTS(SELECT 1 FROM resource_owners o WHERE o.kind='product' AND o.resource_id=p.id AND o.tenant_id=b.tenant_id AND o.user_id=b.user_id),
 'capturedProductMatches',b.room_snapshot->>'activeProductId'=p.id,
 'leaseExists',l.session_id IS NOT NULL,'leaseValid',l.expires_at>clock_timestamp(),
 'leaseOwnerMatches',l.owner_id=sr.owner_id,'runStatus',sr.status,'runEpoch',sr.run_epoch,
 'runBelongsBinding',sr.provider_binding_id=b.binding_id)
 FROM live_sessions s LEFT JOIN live_rooms lr ON lr.id=s.room_id
 LEFT JOIN session_provider_bindings b ON b.session_id=s.id
 LEFT JOIN products p ON p.id=lr.active_product_id
 LEFT JOIN v05_recovery_leases l ON l.session_id=s.id
 LEFT JOIN v05_session_runs sr ON sr.session_id=l.session_id AND sr.run_epoch=l.run_epoch
 WHERE s.id=$1`, parts[3]).Scan(&raw)
			row := map[string]any{"at": time.Now().UTC().Format(time.RFC3339Nano), "scope": "ACTUAL_OWNED_SQL_BEFORE_PUBLIC_NARRATION_START", "querySucceeded": err == nil}
			if err == nil {
				row["authority"] = json.RawMessage(raw)
			}
			encoded, _ := json.Marshal(row)
			mu.Lock()
			file, e := os.OpenFile(filepath.Join(out, "authority-snapshots.jsonl"), os.O_WRONLY|os.O_CREATE|os.O_APPEND, 0600)
			if e == nil {
				file.Write(append(encoded, '\n'))
				file.Close()
			}
			mu.Unlock()
		}
		next.ServeHTTP(w, r)
	})
}

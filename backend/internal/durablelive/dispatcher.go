package durablelive

import (
	"bytes"
	"context"
	"errors"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"strings"
	"sync"
	"time"

	"github.com/jackc/pgx/v5"
)

type Claimed struct {
	Intent  Object
	Command Object
}

// ClaimBatch owns short transactions only; network operations follow Commit.
func (s *Store) ClaimBatch(ctx context.Context, p Principal, limit int) ([]Claimed, error) {
	if p.Role != "CONTROL" || p.InstanceID == "" {
		return nil, fault("FORBIDDEN")
	}
	if limit < 1 || limit > 64 {
		return nil, fault("INVALID_ARGUMENT")
	}
	rows, e := s.DB.Query(ctx, `SELECT DISTINCT run_id FROM dl05_outbox WHERE tenant_id=$1 AND owner_id=$2 AND status='PENDING' AND next_attempt_at<=clock_timestamp() ORDER BY run_id LIMIT $3`, p.TenantID, p.OwnerID, limit*4)
	if e != nil {
		return nil, e
	}
	runs := []string{}
	for rows.Next() {
		var id string
		if e = rows.Scan(&id); e != nil {
			rows.Close()
			return nil, e
		}
		runs = append(runs, id)
	}
	e = rows.Err()
	rows.Close()
	if e != nil {
		return nil, e
	}
	out := []Claimed{}
	for _, id := range runs {
		if len(out) == limit {
			break
		}
		var commandID string
		if e = s.DB.QueryRow(ctx, `SELECT command_id FROM dl05_outbox WHERE run_id=$1 AND status='PENDING' ORDER BY CASE WHEN operation='STOP_RUN' THEN 0 ELSE 1 END,next_attempt_at,intent_id LIMIT 1`, id).Scan(&commandID); e != nil {
			if e == pgx.ErrNoRows {
				continue
			}
			return out, e
		}
		approved, err := s.preflightFacts(ctx, p, "JournalStart", Object{"runId": id, "commandId": commandID})
		if err != nil {
			if _, ok := err.(*Fault); ok {
				continue
			}
			return out, err
		}
		v, e := s.claimOne(approved, p, id)
		if e != nil {
			if _, ok := e.(*Fault); ok {
				continue
			}
			return out, e
		}
		if v != nil {
			out = append(out, *v)
		}
	}
	return out, nil
}
func (s *Store) claimOne(ctx context.Context, p Principal, id string) (*Claimed, error) {
	tx, e := s.begin(ctx)
	if e != nil {
		return nil, e
	}
	defer tx.Rollback(context.Background())
	r, e := jsonRow(tx.QueryRow(ctx, "SELECT "+runJSON+" FROM dl05_runs WHERE run_id=$1 FOR UPDATE SKIP LOCKED", id))
	if e == pgx.ErrNoRows {
		return nil, nil
	}
	if e != nil {
		return nil, e
	}
	if e = authorize(p, r); e != nil {
		return nil, e
	}
	if e = owner(ctx, tx, p, "room", str(r, "roomId")); e != nil {
		return nil, e
	}
	// STOP is selected first and deliberately independent of the media lease.
	in, e := jsonRow(tx.QueryRow(ctx, "SELECT "+intentJSON+` FROM dl05_outbox WHERE run_id=$1 AND status='PENDING' AND next_attempt_at<=clock_timestamp() ORDER BY CASE WHEN operation='STOP_RUN' THEN 0 ELSE 1 END,next_attempt_at,intent_id FOR UPDATE SKIP LOCKED LIMIT 1`, id))
	if e == pgx.ErrNoRows {
		return nil, nil
	}
	if e != nil {
		return nil, e
	}
	cmd, e := commandFor(ctx, tx, r, str(in, "commandId"))
	if e != nil {
		return nil, e
	}
	expiry := time.Now().Add(15 * time.Second)
	switch str(in, "operation") {
	case "STOP_RUN":
		if num(r, "stopRevision") == 0 || num(cmd, "stopRevision") != num(r, "stopRevision") {
			return nil, fault("RUN_STOPPED")
		}
	case "EXECUTE_TURN", "INSTALL_FENCE":
		phase := "ACTIVE"
		if str(in, "operation") == "INSTALL_FENCE" {
			phase = "PENDING_INSTALL"
		}
		l, e := s.validLease(ctx, tx, p, r, phase, true)
		if e != nil {
			return nil, e
		}
		if num(in, "runEpoch") != num(r, "runEpoch") {
			return nil, fault("STALE_RUN_EPOCH")
		}
		expiry = instant(l["leaseExpiresAt"])
		if str(in, "operation") == "EXECUTE_TURN" {
			if e = s.validateSession(ctx, tx, p, r); e != nil {
				return nil, e
			}
			if e = s.validatePayload(ctx, tx, p, r, obj(cmd, "payload"), true); e != nil {
				return nil, e
			}
		}
	}
	_, e = tx.Exec(ctx, `UPDATE dl05_outbox SET status='CLAIMED',claimed_by=$2,claim_version=claim_version+1,lease_expires_at=LEAST($3,clock_timestamp()+interval '15 seconds'),attempt_count=attempt_count+1,updated_at=clock_timestamp() WHERE intent_id=$1`, in["intentId"], p.InstanceID, expiry)
	if e != nil {
		return nil, e
	}
	in, e = loadIntent(ctx, tx, str(in, "intentId"))
	if e != nil {
		return nil, e
	}
	if e = tx.Commit(ctx); e != nil {
		return nil, e
	}
	return &Claimed{in, cmd}, nil
}

// MarkSendStarted is a second short transaction. Its CAS fences expired senders.
func (s *Store) MarkSendStarted(ctx context.Context, p Principal, c Claimed) error {
	var e error
	ctx, e = s.preflightFacts(ctx, p, "JournalStart", Object{"runId": c.Intent["runId"], "commandId": c.Command["commandId"]})
	if e != nil {
		return e
	}
	tx, e := s.begin(ctx)
	if e != nil {
		return e
	}
	defer tx.Rollback(context.Background())
	r, e := loadRun(ctx, tx, str(c.Intent, "runId"), true)
	if e != nil {
		return e
	}
	if e = authorize(p, r); e != nil {
		return e
	}
	if e = owner(ctx, tx, p, "room", str(r, "roomId")); e != nil {
		return e
	}
	if str(c.Intent, "operation") != "STOP_RUN" {
		phase := "ACTIVE"
		if str(c.Intent, "operation") == "INSTALL_FENCE" {
			phase = "PENDING_INSTALL"
		}
		if _, e = s.validLease(ctx, tx, p, r, phase, true); e != nil {
			return e
		}
		if e = checkEpoch(r, c.Command); e != nil {
			return e
		}
		if str(c.Intent, "operation") == "EXECUTE_TURN" {
			if e = s.validateSession(ctx, tx, p, r); e != nil {
				return e
			}
			if e = s.validatePayload(ctx, tx, p, r, obj(c.Command, "payload"), true); e != nil {
				return e
			}
		}
	} else if num(r, "stopRevision") != num(c.Command, "stopRevision") {
		return fault("RUN_STOPPED")
	}
	tag, e := tx.Exec(ctx, `UPDATE dl05_outbox SET send_started_at=clock_timestamp(),updated_at=clock_timestamp() WHERE intent_id=$1 AND status='CLAIMED' AND claim_version=$2 AND claimed_by=$3 AND lease_expires_at>clock_timestamp() AND send_started_at IS NULL`, c.Intent["intentId"], num(c.Intent, "claimVersion"), p.InstanceID)
	if e != nil {
		return e
	}
	if tag.RowsAffected() != 1 {
		return fault("LEASE_LOST")
	}
	if str(c.Intent, "operation") == "EXECUTE_TURN" {
		a, e := loadAttempt(ctx, tx, str(c.Intent, "attemptId"))
		if e != nil {
			return e
		}
		cp := systemCheckpoint(a, "DISPATCHED", "SEND_STARTED", "backend-sender", "command:"+str(c.Intent, "commandId"))
		if e = setSystemSequence(ctx, tx, cp); e != nil {
			return e
		}
		if e = insertCheckpoint(ctx, tx, cp, "APPLIED"); e != nil {
			return e
		}
		_, e = tx.Exec(ctx, `UPDATE dl05_attempts SET last_checkpoint='DISPATCHED',updated_at=clock_timestamp() WHERE attempt_id=$1 AND last_checkpoint='PLANNED'`, a["attemptId"])
		if e != nil {
			return e
		}
	}
	return tx.Commit(ctx)
}

type Sender interface {
	Send(context.Context, Object) (Object, error)
}
type Dispatcher struct {
	Store     *Store
	Principal Principal
	Sender    Sender
	Batch     int
}

func (d *Dispatcher) Tick(ctx context.Context) error {
	n := d.Batch
	if n == 0 {
		n = 16
	}
	claims, e := d.Store.ClaimBatch(ctx, d.Principal, n)
	if e != nil {
		return e
	}
	var wg sync.WaitGroup
	errorsCh := make(chan error, len(claims))
	sem := make(chan struct{}, 4)
	for _, c := range claims {
		c := c
		sem <- struct{}{}
		wg.Add(1)
		go func() {
			defer wg.Done()
			defer func() { <-sem }()
			if e := d.Store.MarkSendStarted(ctx, d.Principal, c); e != nil {
				return
			}
			response, sendErr := d.Sender.Send(ctx, c.Command)
			if e := d.Store.recordSend(ctx, d.Principal, c, response, sendErr); e != nil {
				errorsCh <- e
			}
		}()
	}
	wg.Wait()
	close(errorsCh)
	var all []error
	for e := range errorsCh {
		all = append(all, e)
	}
	return errors.Join(all...)
}
func (d *Dispatcher) Run(ctx context.Context, interval time.Duration) error {
	if interval < 50*time.Millisecond {
		return fault("INVALID_ARGUMENT")
	}
	return runLoop(ctx, interval, d.Tick)
}

// Poll retries after dependencies recover, but never grants another media send.
func runLoop(ctx context.Context, interval time.Duration, tick func(context.Context) error) error {
	delay := interval
	for {
		err := tick(ctx)
		if ctx.Err() != nil {
			return ctx.Err()
		}
		if err != nil {
			delay *= 2
			if delay > 5*time.Second {
				delay = 5 * time.Second
			}
		} else {
			delay = interval
		}
		timer := time.NewTimer(delay)
		select {
		case <-ctx.Done():
			timer.Stop()
			return ctx.Err()
		case <-timer.C:
		}
	}
}

func (s *Store) recordSend(ctx context.Context, p Principal, c Claimed, response Object, sendErr error) error {
	tx, e := s.begin(ctx)
	if e != nil {
		return e
	}
	defer tx.Rollback(context.Background())
	r, e := loadRun(ctx, tx, str(c.Intent, "runId"), true)
	if e != nil {
		return e
	}
	if e = authorize(p, r); e != nil {
		return e
	}
	status := "RECONCILING"
	code := "RECOVERY_UNKNOWN"
	if sendErr == nil && str(c.Intent, "operation") == "EXECUTE_TURN" {
		if e = validate("RuntimeExecuteResponse", response); e == nil && response["commandId"] == c.Command["commandId"] && response["requestHash"] == c.Command["requestHash"] {
			var durable bool
			e = tx.QueryRow(ctx, `SELECT EXISTS(SELECT 1 FROM dl05_runtime_inbox WHERE command_id=$1 AND request_hash=$2 AND receipt_id=$3 AND revision>=$4)`, c.Command["commandId"], c.Command["requestHash"], response["receiptId"], num(response, "revision")).Scan(&durable)
			if e != nil {
				return e
			}
			if durable {
				status = "ACCEPTED"
				code = ""
			}
		}
	}
	// HTTP alone never completes control cleanup or a media attempt.
	_, e = tx.Exec(ctx, `UPDATE dl05_outbox SET status=CASE WHEN status IN ('CLAIMED','ACCEPTED') THEN $4 ELSE status END,last_error_code=$5,updated_at=clock_timestamp() WHERE intent_id=$1 AND claim_version=$2 AND claimed_by=$3 AND status NOT IN ('COMPLETED','FAILED','UNKNOWN')`, c.Intent["intentId"], num(c.Intent, "claimVersion"), p.InstanceID, status, nullable(code))
	if e != nil {
		return e
	}
	return tx.Commit(ctx)
}

// HTTPSender speaks only the frozen v0.5 operations. Token is held in memory,
// never in envelopes, errors, logs or command-line flags. Redirects are refused.
type HTTPSender struct {
	BaseURL string
	Token   string
	Client  *http.Client
}

func (h *HTTPSender) Send(ctx context.Context, cmd Object) (Object, error) {
	name := "RuntimeExecute"
	switch str(cmd, "operation") {
	case "STOP_RUN":
		name = "RuntimeStop"
	case "INSTALL_FENCE":
		name = "FenceInstall"
	}
	op, e := operation(name)
	if e != nil {
		return nil, e
	}
	path := strings.ReplaceAll(op.Path, "{sessionId}", url.PathEscape(str(cmd, "sessionId")))
	body, e := Canonical(cmd)
	if e != nil {
		return nil, e
	}
	req, e := http.NewRequestWithContext(ctx, http.MethodPost, strings.TrimRight(h.BaseURL, "/")+path, bytes.NewReader(body))
	if e != nil {
		return nil, fault("DEPENDENCY_UNAVAILABLE")
	}
	req.Header.Set("Authorization", "Bearer "+h.Token)
	req.Header.Set("Content-Type", "application/json")
	client := h.Client
	if client == nil {
		client = &http.Client{Timeout: 8 * time.Second}
	}
	copyClient := *client
	copyClient.CheckRedirect = func(*http.Request, []*http.Request) error { return http.ErrUseLastResponse }
	resp, e := copyClient.Do(req)
	if e != nil {
		return nil, fault("DEPENDENCY_UNAVAILABLE")
	}
	defer resp.Body.Close()
	if resp.StatusCode != op.SuccessStatus {
		return nil, fmt.Errorf("runtime status %d", resp.StatusCode)
	}
	b, e := io.ReadAll(io.LimitReader(resp.Body, MaxBody+1))
	if e != nil {
		return nil, e
	}
	out, e := Decode(b)
	if e != nil {
		return nil, e
	}
	if e = validate(strings.TrimPrefix(op.ResponseSchema, "#/$defs/"), out); e != nil {
		return nil, e
	}
	return out, nil
}

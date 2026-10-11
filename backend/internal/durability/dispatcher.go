package durability

import (
	"context"
	"encoding/json"
	"errors"
	"github.com/jackc/pgx/v5"
	"log/slog"
	"math/rand/v2"
	"net"
	"time"
)

type Remote interface {
	Deliver(context.Context, string, json.RawMessage) error
	Reconcile(context.Context, string, string) (json.RawMessage, error)
}
type Dispatcher struct {
	Store  *Store
	Remote Remote
	Log    *slog.Logger
}

func (d *Dispatcher) Run(ctx context.Context) {
	slots := make(chan struct{}, 16)
	tick := time.NewTicker(100 * time.Millisecond)
	defer tick.Stop()
	for {
		select {
		case <-ctx.Done():
			return
		case <-tick.C:
		}
		// Independent claims prevent a slow room from occupying the global dispatch loop.
		for n := 0; n < 8; n++ {
			acquired := false
			select {
			case slots <- struct{}{}:
				acquired = true
			default:
			}
			if !acquired {
				break
			}
			c, e := d.Store.Claim(ctx)
			if errors.Is(e, pgx.ErrNoRows) {
				<-slots
				break
			}
			if e != nil {
				<-slots
				d.Log.Error("outbox claim pending", "reason", "DEPENDENCY_UNAVAILABLE")
				break
			}
			go func() { defer func() { <-slots }(); d.dispatch(ctx, c) }()
		}
	}
}
func (d *Dispatcher) dispatch(root context.Context, c Claim) {
	ctx, cancel := context.WithTimeout(root, 8*time.Second)
	defer cancel()
	if e := d.Store.VerifyClaim(ctx, c); e != nil {
		_ = d.Store.Finish(ctx, c, "CANCELLED", "FENCE_REJECTED", 0)
		return
	}
	done := make(chan struct{})
	go func() {
		t := time.NewTicker(3 * time.Second)
		defer t.Stop()
		for {
			select {
			case <-done:
				return
			case <-ctx.Done():
				return
			case <-t.C:
				if d.Store.Extend(ctx, c) != nil {
					cancel()
					return
				}
			}
		}
	}()
	e := d.Remote.Deliver(ctx, c.Command.SessionID, c.Raw)
	close(done)
	state, code := "ACKED", ""
	if e != nil {
		state, code = "UNKNOWN", "ACK_AMBIGUOUS"
		var network *net.OpError
		if errors.As(e, &network) && network.Op == "dial" {
			state, code = "PENDING", "CONNECT_NOT_SENT"
			if c.Attempt >= 5 {
				state = "FAILED"
			}
		}
	}
	finishCtx, finishCancel := context.WithTimeout(root, 2*time.Second)
	defer finishCancel()
	if err := d.Store.Finish(finishCtx, c, state, code, time.Duration(250*(1<<min(c.Attempt-1, 3)))*time.Millisecond+time.Duration(rand.IntN(50))*time.Millisecond); err != nil {
		d.Log.Warn("outbox completion fenced", "commandId", c.Command.CommandID)
	}
}

// ReconcileUnknown NEVER infers safe replay from an HTTP404 or absence of a receipt.
// A durably ACCEPTED, unstarted inbox can safely accept the same immutable envelope.
func (d *Dispatcher) ReconcileUnknown(ctx context.Context) error {
	rows, e := d.Store.DB.Query(ctx, `SELECT o.command_id,o.session_id,o.run_epoch,o.attempt_count,o.unknown_since<clock_timestamp()-interval '30 seconds' FROM v05_outbox o LEFT JOIN v05_inbox i ON i.command_id=o.command_id JOIN v05_recovery_leases l ON l.session_id=o.session_id AND l.run_epoch=o.run_epoch JOIN v05_session_runs r ON r.session_id=o.session_id AND r.run_epoch=o.run_epoch
 WHERE (o.delivery_state='UNKNOWN' OR o.delivery_state='ACKED' AND i.execution_state IN ('ACCEPTED','STARTED','UNKNOWN')) AND o.next_attempt_at<=clock_timestamp() AND l.owner_id=$1 AND l.expires_at>clock_timestamp() AND r.status IN ('ACTIVE','STOPPING') LIMIT 32`, d.Store.Owner)
	if e != nil {
		return e
	}
	type item struct {
		id, sid string
		epoch   int64
		attempt int
		expired *bool
	}
	var list []item
	for rows.Next() {
		var x item
		if e = rows.Scan(&x.id, &x.sid, &x.epoch, &x.attempt, &x.expired); e != nil {
			rows.Close()
			return e
		}
		list = append(list, x)
	}
	e = rows.Err()
	rows.Close()
	if e != nil {
		return e
	}
	for _, x := range list {
		probe, cancel := context.WithTimeout(ctx, 2*time.Second)
		raw, err := d.Remote.Reconcile(probe, x.sid, x.id)
		cancel()
		var receipt struct {
			ExecutionState string `json:"executionState"`
		}
		if err == nil {
			err = json.Unmarshal(raw, &receipt)
		}
		state, code := "UNKNOWN", "RECOVERY_UNKNOWN"
		delay := 30 * time.Second
		if err == nil {
			switch receipt.ExecutionState {
			case "TERMINAL", "STARTED":
				state, code = "ACKED", ""
				delay = time.Second
			case "ACCEPTED":
				if x.attempt < 5 {
					state, code = "PENDING", ""
					delay = time.Duration(250*(1<<min(x.attempt-1, 3))) * time.Millisecond
					delay += time.Duration(rand.IntN(50)) * time.Millisecond
				}
			}
		}
		_, e = d.Store.DB.Exec(ctx, `UPDATE v05_outbox o SET delivery_state=$4,unknown_since=CASE WHEN $4='UNKNOWN' THEN COALESCE(unknown_since,clock_timestamp()) ELSE unknown_since END,last_error_code=NULLIF($5,''),next_attempt_at=clock_timestamp()+$6::bigint*interval '1 millisecond',updated_at=clock_timestamp()
 FROM v05_recovery_leases l WHERE o.command_id=$1 AND o.session_id=$2 AND o.run_epoch=$3 AND o.delivery_state IN ('UNKNOWN','ACKED') AND l.session_id=o.session_id AND l.run_epoch=o.run_epoch AND l.owner_id=$7 AND l.expires_at>clock_timestamp()`, x.id, x.sid, x.epoch, state, code, delay.Milliseconds(), d.Store.Owner)
		if e != nil {
			return e
		}
		if state == "UNKNOWN" && x.expired != nil && *x.expired {
			tx, err := d.Store.DB.Begin(ctx)
			if err != nil {
				return err
			}
			r, err := d.Store.Current(ctx, tx, x.sid, true)
			if err == nil && r.Epoch == x.epoch && r.Status == "ACTIVE" {
				_, err = tx.Exec(ctx, `UPDATE v05_session_runs SET status='RECOVERY_REQUIRED' WHERE session_id=$1 AND run_epoch=$2`, x.sid, x.epoch)
				if err == nil {
					err = d.Store.FenceTimeline(ctx, tx, r, "RECONCILIATION_BUDGET_EXHAUSTED", false)
				}
				if err == nil {
					_, err = tx.Exec(ctx, `INSERT INTO v05_recovery_audit(session_id,run_epoch,action,reason_code) VALUES($1,$2,'MANUAL_REVIEW','RECONCILIATION_BUDGET_EXHAUSTED')`, x.sid, x.epoch)
				}
			}
			if err == nil {
				err = tx.Commit(ctx)
			}
			_ = tx.Rollback(ctx)
			if err != nil {
				return err
			}
		}
	}
	return nil
}

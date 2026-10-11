// Package recovery performs conservative takeover. Missing physical media evidence is never a replay instruction.
package recovery

import (
	"astralive/backend/internal/durability"
	"astralive/backend/internal/ids"
	"context"
	"log/slog"
	"time"
)

type Coordinator struct {
	Store      *durability.Store
	Dispatcher *durability.Dispatcher
	Log        *slog.Logger
}

func (c *Coordinator) Run(ctx context.Context) {
	tick := time.NewTicker(time.Second)
	defer tick.Stop()
	go func() {
		renew := time.NewTicker(2 * time.Second)
		defer renew.Stop()
		for {
			select {
			case <-ctx.Done():
				return
			case <-renew.C:
				bounded, cancel := context.WithTimeout(ctx, 2*time.Second)
				if e := c.Store.Renew(bounded); e != nil {
					c.Log.Warn("run renewal unavailable")
				}
				cancel()
			}
		}
	}()
	for {
		select {
		case <-ctx.Done():
			return
		case <-tick.C:
		}
		bounded, cancel := context.WithTimeout(ctx, 3*time.Second)
		if e := c.Dispatcher.ReconcileUnknown(bounded); e != nil {
			c.Log.Warn("command reconciliation pending")
		}
		cancel()
		bounded, cancel = context.WithTimeout(ctx, 3*time.Second)
		if e := c.SealTerminal(bounded); e != nil {
			c.Log.Warn("terminal cleanup pending")
		}
		if e := c.Sweep(bounded); e != nil {
			c.Log.Warn("recovery scan pending")
		}
		cancel()
	}
}

func (c *Coordinator) Sweep(ctx context.Context) error {
	rows, e := c.Store.DB.Query(ctx, `SELECT l.session_id FROM v05_recovery_leases l JOIN live_sessions s ON s.id=l.session_id JOIN v05_session_runs r USING(session_id,run_epoch)
 WHERE l.expires_at<=clock_timestamp() AND r.status IN ('ACTIVE','STOPPING') AND s.status NOT IN ('ENDED','FAILED') LIMIT 32`)
	if e != nil {
		return e
	}
	var ids []string
	for rows.Next() {
		var id string
		if e = rows.Scan(&id); e != nil {
			rows.Close()
			return e
		}
		ids = append(ids, id)
	}
	e = rows.Err()
	rows.Close()
	if e != nil {
		return e
	}
	for _, id := range ids {
		if e = c.takeover(ctx, id); e != nil {
			c.Log.Warn("session recovery requires review", "sessionId", id)
		}
	}
	return nil
}
func (c *Coordinator) takeover(ctx context.Context, sid string) error {
	tx, e := c.Store.DB.Begin(ctx)
	if e != nil {
		return e
	}
	defer tx.Rollback(ctx)
	// Same Session lock as Stop/Speak. No terminal state is revived.
	t, u, b, e := durability.LockAuthority(ctx, tx, sid)
	if e != nil {
		return e
	}
	var epoch, token int64
	var expired bool
	var status, sessionStatus string
	e = tx.QueryRow(ctx, `SELECT l.run_epoch,l.lease_token,l.expires_at<=clock_timestamp(),r.status,s.status FROM v05_recovery_leases l JOIN v05_session_runs r USING(session_id,run_epoch) JOIN live_sessions s ON s.id=l.session_id WHERE l.session_id=$1 FOR UPDATE OF l,r`, sid).Scan(&epoch, &token, &expired, &status, &sessionStatus)
	if e != nil {
		return e
	}
	if !expired || status == "SEALED" || status == "RECOVERY_REQUIRED" || sessionStatus == "ENDED" || sessionStatus == "FAILED" {
		return nil
	}
	_, e = tx.Exec(ctx, `UPDATE v05_outbox SET delivery_state=CASE WHEN delivery_state='PENDING' THEN 'CANCELLED' ELSE 'UNKNOWN' END,last_error_code='RUN_RETIRED'
 WHERE session_id=$1 AND run_epoch=$2 AND delivery_state IN ('PENDING','CLAIMED');
 `, sid, epoch)
	if e != nil {
		return e
	}
	_, e = tx.Exec(ctx, `UPDATE v05_inbox SET execution_state='UNKNOWN' WHERE session_id=$1 AND run_epoch=$2 AND execution_state='STARTED'`, sid, epoch)
	if e != nil {
		return e
	}
	if e = c.Store.FenceTimeline(ctx, tx, durability.Run{SessionID: sid, Epoch: epoch}, "RUN_RETIRED_UNKNOWN", status == "STOPPING"); e != nil {
		return e
	}
	// STOP is sticky, including expiry while its ACK is missing: cleanup stays STOPPING.
	if status == "STOPPING" {
		_, e = tx.Exec(ctx, `UPDATE v05_recovery_leases SET owner_id=$2,lease_token=lease_token+1,expires_at=clock_timestamp()+interval '10 seconds' WHERE session_id=$1`, sid, c.Store.Owner)
		if e != nil {
			return e
		}
		_, e = tx.Exec(ctx, `UPDATE v05_session_runs SET owner_id=$3,lease_token=$4 WHERE session_id=$1 AND run_epoch=$2`, sid, epoch, c.Store.Owner, token+1)
		if e != nil {
			return e
		}
		_, e = tx.Exec(ctx, `UPDATE v05_outbox SET delivery_state='PENDING',attempt_count=0 WHERE session_id=$1 AND run_epoch=$2 AND command_type='STOP_SESSION' AND delivery_state IN ('UNKNOWN','CANCELLED') AND NOT EXISTS(SELECT 1 FROM v05_inbox i WHERE i.command_id=v05_outbox.command_id AND i.execution_state IN ('STARTED','UNKNOWN','TERMINAL'))`, sid, epoch)
		if e != nil {
			return e
		}
	} else {
		if epoch >= durability.MaxEpoch {
			return durability.ErrFence
		}
		_, e = tx.Exec(ctx, `UPDATE v05_session_runs SET status='SEALED',sealed_at=clock_timestamp() WHERE session_id=$1 AND run_epoch=$2`, sid, epoch)
		if e != nil {
			return e
		}
		_, e = tx.Exec(ctx, `INSERT INTO v05_session_runs(session_id,run_epoch,tenant_id,user_id,owner_id,lease_token,status,provider_binding_id) VALUES($1,$2,$3,$4,$5,$6,'RECOVERY_REQUIRED',$7)`, sid, epoch+1, t, u, c.Store.Owner, token+1, b)
		if e != nil {
			return e
		}
		// A cancellation-only replacement run has no active media epoch.
		_, e = tx.Exec(ctx, `INSERT INTO v05_timeline_epochs(session_id,run_epoch,timeline_epoch,tenant_id,user_id,status,reservation_token,expected_previous_epoch,origin_sample,reason) VALUES($1,$2,1,$3,$4,'SEALED',$5,0,0,'RECOVERY_FENCE_ONLY')`, sid, epoch+1, t, u, ids.New("epoch"))
		if e != nil {
			return e
		}
		_, e = tx.Exec(ctx, `UPDATE v05_recovery_leases SET run_epoch=$2,owner_id=$3,lease_token=$4,expires_at=clock_timestamp()+interval '10 seconds',renewed_at=clock_timestamp() WHERE session_id=$1`, sid, epoch+1, c.Store.Owner, token+1)
		if e != nil {
			return e
		}
		r := durability.Run{SessionID: sid, Epoch: epoch + 1, Token: token + 1, Status: "RECOVERY_REQUIRED"}
		// Installs only a cancellation barrier. No session recreation, generation or speech continuation.
		_, e = c.Store.Enqueue(ctx, tx, r, "BEGIN_RUN", "recovery-fence", ids.New("trace"), "", map[string]any{"expectedPreviousEpoch": epoch, "fenceOnly": true})
		if e != nil {
			return e
		}
	}
	_, e = tx.Exec(ctx, `INSERT INTO v05_recovery_audit(session_id,run_epoch,action,reason_code) VALUES($1,$2,'TAKEOVER','CONSERVATIVE_NO_REPLAY')`, sid, epoch)
	if e != nil {
		return e
	}
	if e = tx.Commit(ctx); e == nil {
		c.Log.Info("recovery takeover", "sessionId", sid, "previousRunEpoch", epoch, "disposition", "RECOVERY_REQUIRED")
	}
	return e
}

// Terminal business state is sticky even if its final Runtime event or binding cleanup was lost.
func (c *Coordinator) SealTerminal(ctx context.Context) error {
	tx, e := c.Store.DB.Begin(ctx)
	if e != nil {
		return e
	}
	defer tx.Rollback(ctx)
	rows, e := tx.Query(ctx, `SELECT r.session_id,r.run_epoch FROM v05_session_runs r JOIN live_sessions se ON se.id=r.session_id WHERE se.status IN ('ENDED','FAILED') AND r.status<>'SEALED' FOR UPDATE OF se,r SKIP LOCKED`)
	if e != nil {
		return e
	}
	type retired struct {
		sid   string
		epoch int64
	}
	var list []retired
	for rows.Next() {
		var x retired
		if e = rows.Scan(&x.sid, &x.epoch); e != nil {
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
		if e = c.Store.FenceTimeline(ctx, tx, durability.Run{SessionID: x.sid, Epoch: x.epoch}, "TERMINAL_SESSION", true); e != nil {
			return e
		}
		_, e = tx.Exec(ctx, `UPDATE v05_session_runs SET status='SEALED',sealed_at=clock_timestamp() WHERE session_id=$1 AND run_epoch=$2`, x.sid, x.epoch)
		if e != nil {
			return e
		}
		_, e = tx.Exec(ctx, `UPDATE v05_outbox SET delivery_state=CASE WHEN delivery_state='PENDING' THEN 'CANCELLED' ELSE 'UNKNOWN' END,last_error_code='TERMINAL_SESSION' WHERE session_id=$1 AND run_epoch=$2 AND delivery_state IN ('PENDING','CLAIMED')`, x.sid, x.epoch)
		if e != nil {
			return e
		}
		_, e = tx.Exec(ctx, `UPDATE utterances u SET status='CANCELLED',completed_at=clock_timestamp() FROM v05_outbox o WHERE o.session_id=$1 AND o.run_epoch=$2 AND o.utterance_id=u.id AND u.status='QUEUED' AND NOT EXISTS(SELECT 1 FROM v05_inbox i WHERE i.command_id=o.command_id AND i.execution_state IN ('STARTED','UNKNOWN','TERMINAL'))`, x.sid, x.epoch)
		if e != nil {
			return e
		}
	}
	return tx.Commit(ctx)
}

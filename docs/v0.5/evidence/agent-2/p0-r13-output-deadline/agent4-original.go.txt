package authority

import (
 "testing"
 "time"
)

// Final authority publication must fail closed if the Room output lease expires
// after the first SQL check, while the Grant/Permit remain otherwise valid.
func TestAgent4OutputExpiryBeforeConsumeCommit(t *testing.T) {
 f:=newFixture(t,true); f.ready()
 f.exec("UPDATE dl05_room_outputs SET expires_at=clock_timestamp()+interval '150 milliseconds' WHERE room_id=$1",f.control.Room)
 f.s.Validate=func(n string,v Document) error {
  if n=="CommitReceiverConsumeResponse" {time.Sleep(220*time.Millisecond)}
  return OfficialValidate(n,v)
 }
 out,err:=f.s.Call(f.ctx,f.guardian,"CommitReceiverConsume",f.consumeQ)
 if err==nil && out["consumeAuthorized"]==true {
  var expired bool
  if e:=f.s.DB.QueryRow(f.ctx,"SELECT expires_at<=clock_timestamp() FROM dl05_room_outputs WHERE room_id=$1",f.control.Room).Scan(&expired);e!=nil {t.Fatal(e)}
  t.Errorf("true consume committed after room output expiry=%v; persistent latches=%d",expired,f.count("dl05_receiver_consumptions"))
 }
}

func TestAgent4AuthorityBudgetCappedByOutputExpiry(t *testing.T) {
 f:=newFixture(t,true);f.ready()
 f.exec("UPDATE dl05_room_outputs SET expires_at=clock_timestamp()+interval '250 milliseconds' WHERE room_id=$1",f.control.Room)
 out:=f.call(f.guardian,"QueryReceiverAuthority",f.private(Document{"references":clone(obj(f.consumeQ,"references"))}))
 snap:=obj(out,"snapshot")
 var until time.Time
 if e:=f.s.DB.QueryRow(f.ctx,"SELECT expires_at FROM dl05_room_outputs WHERE room_id=$1",f.control.Room).Scan(&until);e!=nil {t.Fatal(e)}
 if date(snap,"validUntil").After(until) || number(obj(snap,"timing"),"remainingProofMs")>250 {
  t.Errorf("snapshot proof budget=%dms, validUntil exceeds Room output expiry=%v",number(obj(snap,"timing"),"remainingProofMs"),date(snap,"validUntil").After(until))
 }
}

func TestAgent4PermitCappedByOutputExpiry(t *testing.T) {
 f:=newFixture(t,true)
 f.call(f.runtime,"JournalPrepareAnswer",f.prepareQ)
 f.exec("UPDATE dl05_room_outputs SET expires_at=clock_timestamp()+interval '250 milliseconds' WHERE room_id=$1",f.control.Room)
 out:=f.permitFor(f.unit)
 var until time.Time
 if e:=f.s.DB.QueryRow(f.ctx,"SELECT expires_at FROM dl05_room_outputs WHERE room_id=$1",f.control.Room).Scan(&until);e!=nil {t.Fatal(e)}
 if date(out,"expiresAt").After(until) || number(out,"ttlMs")>250 {
  t.Errorf("new permit ttl=%dms, expiresAt exceeds Room output expiry=%v",number(out,"ttlMs"),date(out,"expiresAt").After(until))
 }
}

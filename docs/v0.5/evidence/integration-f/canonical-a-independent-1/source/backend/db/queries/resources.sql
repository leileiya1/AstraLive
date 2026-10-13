-- name: CreateAvatar :one
INSERT INTO avatars (id,name,engine) VALUES ($1,$2,$3) RETURNING *;
-- name: GetAvatar :one
SELECT * FROM avatars WHERE id=$1;
-- name: ListAvatars :many
SELECT * FROM avatars ORDER BY created_at DESC;
-- name: DeleteAvatar :execrows
DELETE FROM avatars WHERE id=$1;
-- name: SetAvatarStatus :execrows
UPDATE avatars SET status=$2,updated_at=now() WHERE id=$1;
-- name: CreateVoice :one
INSERT INTO voices (id,name,provider,provider_voice_id) VALUES ($1,$2,$3,$4) RETURNING *;
-- name: GetVoice :one
SELECT * FROM voices WHERE id=$1;
-- name: ListVoices :many
SELECT * FROM voices ORDER BY created_at DESC;
-- name: DeleteVoice :execrows
DELETE FROM voices WHERE id=$1;
-- name: CreateProduct :one
INSERT INTO products (id,name,description,price,currency,stock,sizes) VALUES ($1,$2,$3,$4,$5,$6,$7) RETURNING *;
-- name: UpdateProduct :one
UPDATE products SET name=$2,description=$3,price=$4,currency=$5,stock=$6,sizes=$7,updated_at=now() WHERE id=$1 RETURNING *;
-- name: GetProduct :one
SELECT * FROM products WHERE id=$1;
-- name: ListProducts :many
SELECT * FROM products ORDER BY created_at DESC;
-- name: CreateKnowledgeBase :one
INSERT INTO knowledge_bases (id,metadata) VALUES ($1,$2) RETURNING *;
-- name: GetKnowledgeBase :one
SELECT * FROM knowledge_bases WHERE id=$1;
-- name: CreateJob :one
INSERT INTO jobs (id,kind,resource_id) VALUES ($1,$2,$3) RETURNING *;
-- name: GetJob :one
SELECT * FROM jobs WHERE id=$1;
-- name: CompleteJob :execrows
UPDATE jobs SET status='COMPLETED',updated_at=now() WHERE id=$1 AND status='PENDING';
-- name: CreateRoom :one
INSERT INTO live_rooms (id,name,avatar_id,voice_id,knowledge_base_id,system_prompt,active_product_id) VALUES ($1,$2,$3,$4,$5,$6,$7) RETURNING *;
-- name: UpdateRoom :one
UPDATE live_rooms SET name=$2,avatar_id=$3,voice_id=$4,knowledge_base_id=$5,system_prompt=$6,active_product_id=$7,updated_at=now() WHERE id=$1 RETURNING *;
-- name: GetRoom :one
SELECT * FROM live_rooms WHERE id=$1;
-- name: ListRooms :many
SELECT * FROM live_rooms ORDER BY created_at DESC;
-- name: CreateSession :one
INSERT INTO live_sessions (id,room_id) VALUES ($1,$2) RETURNING *;
-- name: GetSession :one
SELECT * FROM live_sessions WHERE id=$1;
-- name: CreateUtterance :one
INSERT INTO utterances (id,session_id,source,text,priority,interrupt_policy,trace_id) VALUES ($1,$2,$3,$4,$5,$6,$7) RETURNING *;
-- name: GetUtterance :one
SELECT * FROM utterances WHERE id=$1;
-- name: GetIdempotency :one
SELECT * FROM idempotency_keys WHERE key=$1 AND route=$2 AND expires_at>now();
-- name: PutIdempotency :exec
INSERT INTO idempotency_keys (key,route,request_hash,response_status,response_body,expires_at) VALUES ($1,$2,$3,$4,$5,$6) ON CONFLICT (key,route) DO NOTHING;
-- name: RecentEvents :many
SELECT envelope FROM runtime_events WHERE session_id=$1 ORDER BY created_at DESC LIMIT $2;
-- name: TransitionSession :execrows
UPDATE live_sessions SET status=$3,updated_at=now(),started_at=CASE WHEN $3='LIVE' THEN now() ELSE started_at END,ended_at=CASE WHEN $3='ENDED' THEN now() ELSE ended_at END WHERE id=$1 AND status=$2;
-- name: TransitionUtterance :execrows
UPDATE utterances SET status=$3,updated_at=now(),started_at=CASE WHEN $3='PLAYING' THEN now() ELSE started_at END,completed_at=CASE WHEN $3 IN ('COMPLETED','INTERRUPTED','FAILED','CANCELLED') THEN now() ELSE completed_at END WHERE id=$1 AND status=$2;
-- name: SetRuntimeOperation :execrows
UPDATE live_sessions SET runtime_operation_id=$2,updated_at=now() WHERE id=$1;
-- name: FailSession :execrows
UPDATE live_sessions SET status='FAILED',failure_code=$2,failure_message=$3,updated_at=now() WHERE id=$1 AND status=$4;
-- name: FailUtterance :execrows
UPDATE utterances SET status='FAILED',failure_code=$2,completed_at=now(),updated_at=now() WHERE id=$1 AND status='QUEUED';
-- name: InsertRuntimeEvent :one
INSERT INTO runtime_events (event_id,session_id,event_type,utterance_id,trace_id,occurred_at,envelope) VALUES ($1,$2,$3,$4,$5,$6,$7) ON CONFLICT (event_id) DO NOTHING RETURNING event_id;
-- name: GetLatestLiveSessionByRoom :one
SELECT * FROM live_sessions WHERE room_id=$1 AND status IN ('LIVE','DEGRADED') ORDER BY created_at DESC LIMIT 1;

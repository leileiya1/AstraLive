"""Explicit TCP1.2 immutable staging; never uses legacy Credit/idle jobs."""
import asyncio
import copy
import hashlib
import math
import struct
import time
from dataclasses import dataclass, field
from uuid import uuid4

from gpu_worker import staging_contract as c
from .session_binding import service_token


class StagingFailure(RuntimeError):
    def __init__(self, code="STAGING_RETIRED"):
        super().__init__(code);self.code=code


def correlation(header):
    name=header["type"]
    for field in ("nonce","chunk_sequence","renewal_sequence","control_id","pose_ack_id"):
        if field in header:return name,header[field]
    return name,None


@dataclass
class Stage:
    identity: dict
    begin: dict
    frames: list = field(default_factory=list)
    storage_acks: set = field(default_factory=set)
    encoded_bytes: int = 0
    descriptor: dict | None = None
    produced: object = None
    commit: dict | None = None
    pose: dict | None = None
    released: dict | None = None
    fenced: bool = False
    reusable: bool = False
    failed: Exception | None = None
    deadline: float = 0
    renew_task: object = None


class StagingClient:
    def __init__(self, endpoint,sid,worker_ref,settings):
        self.endpoint,self.sid,self.worker_ref,self.settings=endpoint,sid,worker_ref,settings
        self.reader=self.writer=self.rx=None;self.ready=None;self.epoch=None
        self.pending={};self.write_lock=asyncio.Lock();self.active=None;self.rtt_ms=0
        self.highest=0;self.failed=None

    async def _read(self):
        prefix=await self.reader.readexactly(8);size,payload_size=struct.unpack("!II",prefix)
        if not 1<=size<=16384 or payload_size>2097152:raise StagingFailure("STAGING_BUDGET_EXCEEDED")
        header=c.decode_header(await self.reader.readexactly(size));payload=await self.reader.readexactly(payload_size)
        c.validate_message(header,payload)
        if header.get("session_id")!=self.sid or self.epoch is not None and header.get("worker_epoch")!=self.epoch:
            raise StagingFailure("STAGING_IDENTITY_MISMATCH")
        return header,payload

    async def _write(self,header,payload=b""):
        async with self.write_lock:
            c.validate_message(header,payload);data=c.canonical_bytes(header)
            self.writer.write(struct.pack("!II",len(data),len(payload))+data+payload)
            await asyncio.wait_for(self.writer.drain(),2)

    def common(self,stage=None):
        value={"contract_revision":c.REVISION,"session_id":self.sid,"worker_epoch":self.epoch}
        if stage is not None:value["identity"]=stage.identity
        return value

    async def exchange(self,header,response,payload=b"",timeout=5):
        if self.failed:raise self.failed
        marker=correlation({**header,"type":response})
        if marker in self.pending:raise StagingFailure("STAGING_CONFLICT")
        future=asyncio.get_running_loop().create_future();self.pending[marker]=future
        try:
            await self._write(header,payload)
            return await asyncio.wait_for(future,timeout)
        finally:self.pending.pop(marker,None)

    async def connect(self):
        begun=time.monotonic()
        try:
            self.reader,self.writer=await asyncio.wait_for(asyncio.open_connection("127.0.0.1",self.endpoint["port"]),2)
            auth={"type":"Auth","protocol_version":1,"internal_version":"1.2","session_id":self.sid,
                  "token":service_token(self.endpoint["tokenFile"]),"requested_capabilities":[c.CAPABILITY],
                  "requested_limits_revision":self.settings.limits_revision}
            await self._write(auth);self.ready,_=await asyncio.wait_for(self._read(),15)
            c.validate_negotiation(auth,self.ready)
            expected="sha256:"+self.endpoint["assetSHA256"].removeprefix("sha256:")
            if self.ready["simulation"] or self.ready["input_asset_sha256"]!=expected or self.ready["profile_gate_ref"]!=self.settings.short_gate_sha256:
                raise StagingFailure("STAGING_IDENTITY_MISMATCH")
            self.epoch=self.ready["worker_epoch"];self.highest=self.ready["highest_generation_id"]
            self.rtt_ms=math.ceil((time.monotonic()-begun)*1000)
            self.rx=asyncio.create_task(self.receive_loop(),name="staging-tcp-reader")
        except BaseException:
            await self.close();raise

    async def receive_loop(self):
        try:
            while True:
                header,payload=await self._read();name=header["type"]
                stage=self.active
                if "identity" in header and (stage is None or header["identity"]!=stage.identity):
                    raise StagingFailure("STAGING_IDENTITY_MISMATCH")
                if name=="StageError":raise StagingFailure(header["code"])
                if name=="StageVideo":
                    if stage.fenced or header["frame_sequence"]!=len(stage.frames) or header["sample_end"]>stage.begin["source_samples"]:
                        raise StagingFailure("STAGING_SEQUENCE_GAP")
                    if header["provenance"]["source"]!="GPU_INFERENCE" or header["provenance"]["workerRef"]!=self.worker_ref:
                        raise StagingFailure("STAGING_IDENTITY_MISMATCH")
                    stage.encoded_bytes+=len(payload)
                    if stage.encoded_bytes>self.ready["selected_limits"]["runtime_artifact_bytes"]:
                        raise StagingFailure("STAGING_BUDGET_EXCEEDED")
                    receipt=stage.identity["stageId"]+":"+str(header["frame_sequence"])
                    stage.frames.append((copy.deepcopy(header),bytes(payload),receipt))
                    await self._write({"type":"StageReceived",**self.common(stage),"frame_sequence":header["frame_sequence"],
                        "payload_sha256":header["payload_sha256"],"native_rgb_sha256":header["native_rgb_sha256"],"storage_receipt_id":receipt})
                elif name=="StageReceivedAck":
                    seq=header["frame_sequence"]
                    if seq>=len(stage.frames):raise StagingFailure("STAGING_SEQUENCE_GAP")
                    original,_,receipt=stage.frames[seq]
                    if any(header[k]!=original[k] for k in ("payload_sha256","native_rgb_sha256")) or header["storage_receipt_id"]!=receipt:
                        raise StagingFailure("STAGING_CONFLICT")
                    stage.storage_acks.add(seq)
                elif name=="StageProduced":
                    d=header["descriptor"]
                    for key in ("original_samples","pad_samples","source_samples","pcm_sha256","source_format","request_fingerprint"):
                        if d[key]!=stage.begin[key]:raise StagingFailure("STAGING_CONFLICT")
                    if d["limits"]!=self.ready["selected_limits"] or d["provenance"]["source"]!="GPU_INFERENCE" or d["provenance"]["cache_id"]!=self.ready["cache_id"]:
                        raise StagingFailure("STAGING_IDENTITY_MISMATCH")
                    if len(stage.frames)!=d["frame_count"] or stage.storage_acks!=set(range(d["frame_count"])):
                        raise StagingFailure("STAGING_SEQUENCE_GAP")
                    digest=hashlib.sha256()
                    for _,data,_ in stage.frames:digest.update(struct.pack("!Q",len(data)));digest.update(data)
                    if d["video_bytes"]!=stage.encoded_bytes or d["video_stream_sha256"]!="sha256:"+digest.hexdigest():
                        raise StagingFailure("STAGING_CONFLICT")
                    stage.descriptor=header;stage.produced.set_result(header)
                else:
                    future=self.pending.get(correlation(header))
                    if future is None or future.done():raise StagingFailure("STAGING_CONFLICT")
                    future.set_result(header)
        except asyncio.CancelledError:raise
        except Exception as exc:
            self.failed=exc if isinstance(exc,StagingFailure) else StagingFailure("STAGING_RETIRED")
            if self.active:
                self.active.fenced=True;self.active.failed=self.failed
                if not self.active.produced.done():self.active.produced.set_exception(self.failed)
            for future in self.pending.values():
                if not future.done():future.set_exception(self.failed)

    async def health(self):
        began=time.monotonic();nonce=uuid4().hex
        answer=await self.exchange({"type":"StageHealth",**self.common(),"nonce":nonce},"StageHealthAck")
        if answer["nonce"]!=nonce:raise StagingFailure("STAGING_CONFLICT")
        self.rtt_ms=math.ceil((time.monotonic()-began)*1000);return answer

    async def status(self,stage):
        began=time.monotonic();nonce=uuid4().hex
        answer=await self.exchange({"type":"StageStatus",**self.common(stage),"nonce":nonce},"StageStatusResult")
        self.rtt_ms=math.ceil((time.monotonic()-began)*1000);return answer

    async def lease_fields(self,command,request,journal,guard):
        guard();began=time.monotonic();grant=await journal.request("POST","/grant",{"sessionId":self.sid,"runEpoch":command["runEpoch"]})
        received=time.monotonic();guard()
        if grant["status"]!="ACTIVE" or grant["leaseToken"]!=request.leaseToken or command["commandSeq"]<grant["barrierSeq"]:
            raise StagingFailure("STAGING_RETIRED")
        a_rtt=math.ceil((received-began)*1000);age=math.ceil((time.monotonic()-received)*1000)
        lease=min(10000,grant["remainingMs"]-a_rtt-age-self.rtt_ms-200)
        if lease<=0:raise StagingFailure("STAGING_LEASE_EXPIRED")
        return {"a_grant":{**{k:grant[k] for k in ("sessionId","runEpoch","leaseToken","barrierSeq","remainingMs")},"commandSeq":command["commandSeq"]},
            "a_rtt_ms":a_rtt,"grant_age_ms":age,"worker_rtt_ms":self.rtt_ms,"safety_ms":200,"lease_ms":lease}

    async def begin(self,identity,pcm,original,command,request,journal,guard):
        if self.active is not None and not self.active.reusable:raise StagingFailure("STAGING_RETIRED")
        await self.health();guard()
        begin={"type":"StageBegin",**self.common(),"identity":identity,"command_request_fingerprint":command["requestFingerprint"],
            "cache_id":self.ready["cache_id"],"pcm_sha256":c.bytes_digest(pcm),"original_samples":original,
            "pad_samples":len(pcm)//2-original,"source_samples":len(pcm)//2,"source_format":copy.deepcopy(c.SOURCE_FORMAT["properties"]),
            "limits_revision":self.settings.limits_revision,**await self.lease_fields(command,request,journal,guard)}
        begin["source_format"]={k:v["const"] for k,v in begin["source_format"].items()}
        begin["request_fingerprint"]=c.stage_begin_fingerprint(begin)
        stage=Stage(copy.deepcopy(identity),copy.deepcopy(begin),produced=asyncio.get_running_loop().create_future())
        self.active=stage;self.highest=identity["workerGenerationId"]
        stage.deadline=time.monotonic()+begin["lease_ms"]/1000
        response=await self.exchange(begin,"StageBegun")
        if response["request_fingerprint"]!=begin["request_fingerprint"] or response["limits"]!=self.ready["selected_limits"]:
            raise StagingFailure("STAGING_CONFLICT")
        stage.renew_task=asyncio.create_task(self.renew(stage,command,request,journal,guard),name="staging-fresh-A-renewal")
        credit=response["audio_credit_samples"];offset=sequence=0
        while offset<len(pcm)//2:
            guard();self.check(stage)
            count=min(6400,len(pcm)//2-offset)
            if credit<count:
                state=await self.status(stage);credit=state["audio_credit_samples"]
                if state["publication_fenced"]:raise StagingFailure("STAGING_RETIRED")
                if credit<count:await asyncio.sleep(.02);continue
            data=pcm[offset*2:(offset+count)*2]
            packet={"type":"StageAudio",**self.common(stage),"chunk_sequence":sequence,"first_sample_index":offset,
                "sample_count":count,"final_chunk":offset+count==len(pcm)//2,"chunk_sha256":c.bytes_digest(data)}
            reply=await self.exchange(packet,"StageAudioAccepted",data)
            if reply["chunk_sequence"]!=sequence or reply["chunk_sha256"]!=packet["chunk_sha256"]:raise StagingFailure("STAGING_CONFLICT")
            credit=reply["audio_credit_samples"];offset+=count;sequence+=1
        await asyncio.wait_for(asyncio.shield(stage.produced),60);self.check(stage);guard();return stage

    def check(self,stage):
        if stage.failed:raise stage.failed
        if stage.fenced or time.monotonic()>=stage.deadline:raise StagingFailure("STAGING_LEASE_EXPIRED")

    async def renew(self,stage,command,request,journal,guard):
        sequence=0;started=time.monotonic()
        try:
            while not stage.released and not stage.fenced:
                await asyncio.sleep(1);guard();self.check(stage)
                if time.monotonic()-started>=59:raise StagingFailure("STAGING_LEASE_EXPIRED")
                sequence+=1
                packet={"type":"StageRenew",**self.common(stage),"renewal_sequence":sequence,**await self.lease_fields(command,request,journal,guard)}
                packet["renewal_fingerprint"]=c.renewal_fingerprint(packet);sent=time.monotonic()
                reply=await self.exchange(packet,"StageRenewAck")
                if reply["renewal_fingerprint"]!=packet["renewal_fingerprint"] or reply["renewal_sequence"]!=sequence:raise StagingFailure("STAGING_CONFLICT")
                stage.deadline=sent+reply["lease_remaining_ms"]/1000-(time.monotonic()-sent)-.1
        except asyncio.CancelledError:raise
        except Exception as exc:stage.fenced=True;stage.failed=exc

    async def arm(self,stage,proof,guard):
        guard();self.check(stage)
        packet={"type":"StageCommit",**self.common(stage),"commit_proof":proof,"commit_proof_fingerprint":c.commit_fingerprint(stage.identity,proof)}
        reply=await self.exchange(packet,"StageCommitAck")
        if reply["descriptor_sha256"]!=proof["descriptor_sha256"] or reply["commit_proof_fingerprint"]!=packet["commit_proof_fingerprint"]:
            raise StagingFailure("STAGING_CONFLICT")
        stage.commit=packet;guard();self.check(stage)

    async def pose(self,stage,proof,guard):
        guard();self.check(stage)
        packet={"type":"StagePoseConsumed",**self.common(stage),"pose_proof":proof,"pose_proof_fingerprint":c.pose_fingerprint(stage.identity,proof)}
        c.validate_pose_consumed(packet,stage.commit)
        reply=await self.exchange(packet,"StagePoseConsumedAck")
        if reply["pose_proof_fingerprint"]!=packet["pose_proof_fingerprint"] or reply["latest_consumed_sequence"]!=proof["latest_consumed_sequence"]:
            raise StagingFailure("STAGING_CONFLICT")
        stage.pose=packet;return reply

    async def release(self,stage,complete=False,reason="STOP"):
        control=uuid4().hex
        if not complete:
            stage.fenced=True
            await self.exchange({"type":"StageCancel",**self.common(stage),"control_id":control,"reason":reason},"StageFenced",timeout=10)
        packet={"type":"StageRelease",**self.common(stage),"control_id":control,"reason":"COMPLETE" if complete else "CANCELLED",
            "descriptor_sha256":stage.descriptor["descriptor_sha256"] if stage.descriptor else None,
            "commit_proof_fingerprint":stage.commit["commit_proof_fingerprint"] if stage.commit else None,
            "pose_proof_fingerprint":stage.pose["pose_proof_fingerprint"] if stage.pose else None,
            "latest_consumed_sequence":stage.pose["pose_proof"]["latest_consumed_sequence"] if stage.pose else -1}
        reply=await self.exchange(packet,"StageReleased",timeout=15)
        if complete and (reply["terminal_disposition"]!="PROVEN_COMPLETE" or not reply["reusable"]):raise StagingFailure("STAGING_RETIRED")
        stage.released=reply;stage.reusable=reply["reusable"]
        if stage.renew_task:stage.renew_task.cancel();await asyncio.gather(stage.renew_task,return_exceptions=True)
        return reply

    async def close(self):
        if self.rx:self.rx.cancel();await asyncio.gather(self.rx,return_exceptions=True);self.rx=None
        if self.writer:self.writer.close();await asyncio.wait_for(self.writer.wait_closed(),2);self.writer=None


class StagingAvatarEngine:
    """Bound adapter lifecycle with no legacy native idle/publication loop."""
    def __init__(self,endpoint,sid,worker_ref,settings):
        self.link=StagingClient(endpoint,sid,worker_ref,settings);self.settings=settings
        self.degraded=False;self.generation_id=0;self.speaking=False
    async def prepare(self,config):await self.link.connect()
    async def start(self):pass
    async def interrupt(self,generation):
        stage=self.link.active
        if stage and not stage.released:
            await self.link.release(stage,reason="FORCE")
        self.generation_id=generation
    async def stop(self):
        stage=self.link.active
        if stage and not stage.released:await self.link.release(stage,reason="STOP")
        await self.link.close()
    async def push_audio(self,chunk):raise StagingFailure("STAGING_UNSUPPORTED")
    async def push_video(self,frame):raise StagingFailure("STAGING_UNSUPPORTED")

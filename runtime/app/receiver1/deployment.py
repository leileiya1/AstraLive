"""Trusted inherited-FD process bootstrap, separate from frozen wire RPC.

This consumes a one-use anonymous pipe created by the Go supervisor. It never
enrolls a principal, writes SQL, confirms installation, stages or opens output.
Backend process pins/physical-source verification remain independently required.
"""
import base64
import json
import os
import stat
import psutil
from dataclasses import dataclass

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from astralive_contracts import durable_live_v2 as dto
from .transport import AuthorityTransport, InstallationReader, Credential, ProcessIdentity, TransportFailure, identity
from .wire import GuardianWire


def _native(v):
    if (type(v) is not dict or set(v) != {"PID", "UID", "Birth"}
            or type(v['PID']) is not int or v['PID'] <= 0
            or type(v['UID']) is not int or v['UID'] < 0
            or type(v['Birth']) is not str or not 0 < len(v['Birth']) <= 128):
        raise TransportFailure("UNAUTHENTICATED")
    return ProcessIdentity(v['PID'], v['UID'], v['Birth'])


@dataclass(frozen=True, repr=False)
class Deployment:
    principal_id: str
    incarnation: str
    role: str
    binding: object
    parent: ProcessIdentity
    credential: Credential
    signing_key: object
    key_id: str
    control_provisioning: object

    def __repr__(self): return "Deployment(<redacted>)"
    __str__ = __repr__

    def guardian_ports(self, backend_socket):
        if self.role != 'OUTPUT_GUARDIAN':
            raise TransportFailure('FORBIDDEN')
        return (GuardianWire(), AuthorityTransport(backend_socket, self.parent, self.credential),
                InstallationReader(backend_socket, self.parent, self.credential))

    def control_pin(self, factory):
        """Assemble Agent5's existing ProcessPin from private FD provenance.

        factory is injected so the unmerged Guardian core is not imported by
        production Runtime. No request-body enrollment path calls this method.
        """
        cp = self.control_provisioning
        if self.role != 'OUTPUT_GUARDIAN' or type(cp) is not dict or set(cp) != {
                'principalId','incarnation','role','scope','identity','credentialHash'}:
            raise TransportFailure('FORBIDDEN')
        scope = (self.binding.tenantId, self.binding.ownerId, self.binding.roomId)
        if (cp['role'] != 'CONTROL_REGISTRAR' or tuple(cp['scope']) != scope
                or _native(cp['identity']) != self.parent
                or identity(self.parent.pid) != self.parent):
            raise TransportFailure('UNAUTHENTICATED')
        try:
            digest = bytes.fromhex(cp['credentialHash'])
            if len(digest) != 32: raise ValueError()
            return factory(cp['principalId'], 'CONTROL_REGISTRAR', cp['incarnation'],
                           scope, self.parent.pid, self.parent.uid,
                           psutil.Process(self.parent.pid).create_time(), digest)
        except Exception:
            raise TransportFailure('UNAUTHENTICATED') from None


def load_inherited(expected_role, fd=3):
    """Deployment configuration, never a JSON HTTP enrollment endpoint.

    Runtime can fake its own local objects but cannot mint a credential matching
    the Backend's independently provisioned process/UID/birth/scope pin.
    """
    try:
        if not stat.S_ISFIFO(os.fstat(fd).st_mode):
            raise TransportFailure('UNAUTHENTICATED')
        with os.fdopen(fd, 'rb') as source:
            raw = source.read(16385)
        if len(raw) > 16384:
            raise TransportFailure('UNAUTHENTICATED')
        def pairs(items):
            out = {}
            for k,v in items:
                if k in out: raise TransportFailure('UNAUTHENTICATED')
                out[k]=v
            return out
        v = json.loads(raw, object_pairs_hook=pairs)
        required = {'credential','principalId','incarnation','role','keyId','privateKey','binding','processIdentity','parentIdentity'}
        if set(v) not in (required, required | {'controlProvisioning'}) or expected_role not in {'OUTPUT_GUARDIAN','REGISTERED_RUNTIME','OBSERVER'} or v['role'] != expected_role:
            raise TransportFailure('UNAUTHENTICATED')
        if _native(v['processIdentity']) != identity(os.getpid()) or _native(v['parentIdentity']) != identity(os.getppid()):
            raise TransportFailure('UNAUTHENTICATED')
        # Runtime and Observer processes never hold a signing key or CONTROL.
        if expected_role in {'REGISTERED_RUNTIME','OBSERVER'} and (v['privateKey'] or v['keyId'] or 'controlProvisioning' in v):
            raise TransportFailure('FORBIDDEN')
        binding = dto.decode('ReceiverBootstrapBinding', dto.canonical_json(v['binding']))
        key = None
        if expected_role == 'OUTPUT_GUARDIAN':
            private = base64.b64decode(v['privateKey'], validate=True)
            if len(private) != 64 or not v['keyId']: raise TransportFailure('UNAUTHENTICATED')
            key = Ed25519PrivateKey.from_private_bytes(private[:32])
        return Deployment(v['principalId'],v['incarnation'],expected_role,binding,_native(v['parentIdentity']),
                          Credential(v['credential'].encode('ascii')),key,v['keyId'],v.get('controlProvisioning'))
    except TransportFailure:
        raise
    except Exception:
        raise TransportFailure('UNAUTHENTICATED') from None

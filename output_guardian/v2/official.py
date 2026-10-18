"""Consume Agent4's sole SDK/deployment ports; no new wire or listener.

Only the trusted host assembly calls these helpers. Physical installation and
production output exclusivity are separate mandatory Registrar preconditions.
"""

import psutil

from runtime.app.receiver1.deployment import Deployment
from runtime.app.receiver1.transport import ProcessIdentity, identity

from .gate import require
from .ipc import ProcessPin
from .receiver import Receiver


def receiver_from_deployment(
    deployment, backend_socket, outputs, journal, *, required_sinks, **session_origins
):
    require(
        isinstance(deployment, Deployment) and deployment.role == "OUTPUT_GUARDIAN",
        "FORBIDDEN",
    )
    require(identity(deployment.parent.pid) == deployment.parent, "UNAUTHENTICATED")
    wire, authority, installations = deployment.guardian_ports(backend_socket)
    b = deployment.binding
    return Receiver(
        wire,
        authority,
        installations,
        outputs,
        journal,
        guardian_principal=deployment.principal_id,
        guardian_incarnation=deployment.incarnation,
        signing_key=deployment.signing_key,
        key_id=deployment.key_id,
        scope=(b.tenantId, b.ownerId, b.roomId),
        required_sinks=required_sinks,
        **session_origins,
    )


def producer_pin(provision, installed_binding, wire):
    """Native verifier metadata from trusted Registrar's ProducerProvision.

    Never called by HTTP or from Runtime JSON. Initial FD binding may precede
    Registrar's fresh principal installation; compare against the FULL installed
    binding, never substitute bootstrap placeholders/current execution slots.
    """
    wire.validate("ReceiverBootstrapBinding", installed_binding)
    required = {
        "principalId",
        "incarnation",
        "role",
        "scope",
        "identity",
        "credentialHash",
    }
    require(type(provision) is dict and set(provision) == required, "FORBIDDEN")
    scope = tuple(installed_binding[k] for k in ("tenantId", "ownerId", "roomId"))
    require(
        provision["role"] == "REGISTERED_RUNTIME"
        and tuple(provision["scope"]) == scope,
        "FORBIDDEN",
    )
    require(
        provision["principalId"] == installed_binding["runtimePrincipalId"]
        and provision["incarnation"] == installed_binding["runtimeIncarnation"],
        "FORBIDDEN",
    )
    native = provision["identity"]
    require(
        type(native) is dict and set(native) == {"PID", "UID", "Birth"},
        "UNAUTHENTICATED",
    )
    require(
        type(native["PID"]) is int
        and native["PID"] > 0
        and type(native["UID"]) is int
        and native["UID"] >= 0
        and type(native["Birth"]) is str
        and 0 < len(native["Birth"]) <= 128,
        "UNAUTHENTICATED",
    )
    actual = identity(native["PID"])
    require(
        actual == ProcessIdentity(native["PID"], native["UID"], native["Birth"]),
        "UNAUTHENTICATED",
    )
    try:
        digest = bytes.fromhex(provision["credentialHash"])
    except (ValueError, TypeError):
        require(False, "UNAUTHENTICATED")
    require(len(digest) == 32, "UNAUTHENTICATED")
    return ProcessPin(
        provision["principalId"],
        provision["role"],
        provision["incarnation"],
        scope,
        actual.pid,
        actual.uid,
        psutil.Process(actual.pid).create_time(),
        digest,
    )

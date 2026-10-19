import copy
import os
from dataclasses import replace

import psutil
import pytest

from astralive_contracts import durable_live_v2 as dto
from astralive_contracts.durable_live_v2.codec import SecretString
from output_guardian.model import Closed
from output_guardian.v2.official import producer_pin, receiver_from_deployment
from runtime.app.receiver1.deployment import Deployment
from runtime.app.receiver1.transport import (
    AuthorityTransport,
    Credential,
    InstallationReader,
    identity,
)
from runtime.app.receiver1.wire import GuardianWire


@pytest.mark.asyncio
async def test_receiver_consume_official_secret_deepcopy(domain):
    d = domain
    q = d.r.wire.decode("ReceiverConsumeRequest", d.r.wire.canonical(d.q))
    ticket = q["consumeTicket"]
    assert isinstance(ticket, SecretString) and copy.deepcopy(ticket) is ticket
    assert d.q["consumeTicket"] not in repr(copy.deepcopy(q))
    out = await d.r.consume(d.runtime, q)
    assert (
        out["consumeAuthorized"]
        and out["consumption"]["binding"]["generationId"] == d.r.staged["generationId"]
    )


def test_deployment_guardian_ports_and_constructor_use_only_official_sdk(domain):
    # The separate native Go suite verifies inherited-FD bootstrap/real SQL.
    # This unit test is an explicit trusted Deployment object fixture.
    d = domain
    b = dto.decode("ReceiverBootstrapBinding", d.r.wire.canonical(d.r.staged))
    deployment = Deployment(
        d.r.guardian_principal,
        d.r.incarnation,
        "OUTPUT_GUARDIAN",
        b,
        identity(os.getpid()),
        Credential(b"A" * 43),
        d.r.signing_key,
        d.r.key_id,
        None,
    )
    wire, transport, reader = deployment.guardian_ports("/unused-owned-test.sock")
    assert (
        isinstance(wire, GuardianWire)
        and isinstance(transport, AuthorityTransport)
        and isinstance(reader, InstallationReader)
    )
    r = receiver_from_deployment(
        deployment,
        "/unused-owned-test.sock",
        d.outputs,
        d.journal,
        required_sinks=d.r.required_sinks,
    )
    assert isinstance(r.wire, GuardianWire) and r.incarnation == d.r.incarnation
    assert r.gate.state == "FENCED" and r.staged is None
    with pytest.raises(Closed):
        receiver_from_deployment(
            replace(deployment, role="REGISTERED_RUNTIME"),
            "/unused",
            d.outputs,
            d.journal,
            required_sinks=d.r.required_sinks,
        )


def test_native_producer_provision_cannot_substitute_registration_identity(domain):
    d = domain
    me = identity(os.getpid())
    provision = dict(
        principalId=d.r.staged["runtimePrincipalId"],
        incarnation=d.r.staged["runtimeIncarnation"],
        role="REGISTERED_RUNTIME",
        scope=list(d.r.scope),
        credentialHash="ab" * 32,
        identity=dict(PID=me.pid, UID=me.uid, Birth=me.birth),
    )
    pin = producer_pin(provision, d.r.staged, d.r.wire)
    assert pin.created == psutil.Process().create_time() and pin.uid == me.uid
    for field, value in (
        ("principalId", "other"),
        ("incarnation", "old"),
        ("role", "CONTROL_REGISTRAR"),
        ("scope", ["other", "o", "r"]),
    ):
        with pytest.raises(Closed):
            producer_pin(dict(provision, **{field: value}), d.r.staged, d.r.wire)
    bad = dict(provision, identity=dict(PID=me.pid, UID=me.uid, Birth="old-process"))
    with pytest.raises(Closed):
        producer_pin(bad, d.r.staged, d.r.wire)

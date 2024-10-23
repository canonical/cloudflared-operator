# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

# pylint: disable=protected-access,too-many-arguments,too-many-positional-arguments

"""Unit tests."""

from unittest import mock

import ops
import ops.testing

import src.charm
from charm import CloudflaredCharm


def test_install(monkeypatch):
    """
    arrange: none.
    act: run install event.
    assert: charm should install the charmed-cloudflared snap.
    """
    context = ops.testing.Context(CloudflaredCharm)
    magic_mock = mock.MagicMock()
    monkeypatch.setattr(src.charm.snap, "_system_set", magic_mock)
    context.run(context.on.install(), ops.testing.State())

    magic_mock.assert_called_once_with("experimental.parallel-instances", "true")


def test_initial_state():
    """
    arrange: none.
    act: run config-changed event without any tunnel-token input.
    assert: charm should enter the waiting state.
    """
    context = ops.testing.Context(CloudflaredCharm)
    out = context.run(context.on.config_changed(), ops.testing.State())
    assert out.unit_status == ops.WaitingStatus("waiting for tunnel token")


def test_conflict_config_integration():
    """
    arrange: create a scenario with cloudflared-router integrations and tunnel-token config at the
        same time.
    act: run the config-changed event.
    assert: cloudflared charm should enter blocked state.
    """
    context = ops.testing.Context(CloudflaredCharm)
    relation_secret = ops.testing.Secret(tracked_content={"tunnel-token": "foo"})
    relation = ops.testing.Relation(
        "cloudflared-route",
        remote_app_data={"tunnel_token_secret_id": relation_secret.id},
    )
    config_secret = ops.testing.Secret(tracked_content={"tunnel-token": "foobar"})

    out = context.run(
        context.on.config_changed(),
        ops.testing.State(
            secrets=[relation_secret, config_secret],
            config={"tunnel-token": config_secret.id},
            relations=[relation],
        ),
    )

    assert out.unit_status == ops.BlockedStatus(
        "tunnel-token is provided by both the config and integration"
    )


def test_invalid_integration_data():
    """
    arrange: create a scenario with invalid data inside cloudflared-router integrations.
    act: run the config-changed event.
    assert: cloudflared charm should enter blocked state.
    """
    context = ops.testing.Context(CloudflaredCharm)
    relation_secret = ops.testing.Secret(tracked_content={"token": "foo"})
    relation = ops.testing.Relation(
        "cloudflared-route",
        remote_app_data={"tunnel_token_secret_id": relation_secret.id},
    )

    out = context.run(
        context.on.config_changed(),
        ops.testing.State(
            secrets=[relation_secret],
            relations=[relation],
        ),
    )

    assert out.unit_status == ops.BlockedStatus(
        "received invalid data from cloudflared-route integration: "
        "secret doesn't have 'tunnel-token' field"
    )

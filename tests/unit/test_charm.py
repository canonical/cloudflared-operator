# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

# pylint: disable=protected-access

"""Unit tests."""

import ops
import ops.testing


def test_install(cloudflared_charm_cls):
    """
    arrange: none.
    act: run install event.
    assert: charm should install the charmed-cloudflared snap.
    """
    context = ops.testing.Context(cloudflared_charm_cls)

    context.run(context.on.install(), ops.testing.State())

    cloudflared_charm_cls._install_cloudflared_snap.assert_called_once()


def test_config_tunnel_token(cloudflared_charm_cls):
    """
    arrange: create a scenario with tunnel-token charm config.
    act: run the config-changed event.
    assert: cloudflared charm should pass the tunnel-token to the snap.
    """
    context = ops.testing.Context(cloudflared_charm_cls)
    secret = ops.testing.Secret(tracked_content={"tunnel-token": "foobar"})

    context.run(
        context.on.config_changed(),
        ops.testing.State(secrets=[secret], config={"tunnel-token": secret.id}),
    )

    cloudflared_charm_cls._config_cloudflared_snap.assert_called_once_with({"tokens": "foobar"})


def test_cloudflared_route_integration(cloudflared_charm_cls):
    """
    arrange: create a scenario with integrations with cloudflared-router providers.
    act: run the relation-changed event.
    assert: cloudflared charm should pass the tunnel-token from integrations to the snap.
    """
    context = ops.testing.Context(cloudflared_charm_cls)
    secret_1 = ops.testing.Secret(tracked_content={"tunnel-token": "foo"})
    relation_1 = ops.testing.Relation(
        "cloudflared-route",
        remote_app_name="config1",
        remote_app_data={"tunnel_token_secret_id": secret_1.id},
    )
    secret_2 = ops.testing.Secret(tracked_content={"tunnel-token": "bar"})
    relation_2 = ops.testing.Relation(
        "cloudflared-route",
        remote_app_name="config2",
        remote_app_data={"tunnel_token_secret_id": secret_2.id},
    )

    context.run(
        context.on.relation_changed(relation=relation_1),
        ops.testing.State(secrets=[secret_1, secret_2], relations=[relation_1, relation_2]),
    )

    cloudflared_charm_cls._config_cloudflared_snap.assert_called_once_with({"tokens": "foo,bar"})


def test_conflict_config_integration(cloudflared_charm_cls):
    """
    arrange: create a scenario with cloudflared-router integrations and tunnel-token config at the
        same time.
    act: run the config-changed event.
    assert: cloudflared charm should enter blocked state.
    """
    context = ops.testing.Context(cloudflared_charm_cls)
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
        "tunnel-token is provided in both the config and integration"
    )

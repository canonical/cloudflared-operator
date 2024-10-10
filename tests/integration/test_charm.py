#!/usr/bin/env python3

# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

# pylint: disable=protected-access,too-many-arguments,too-many-positional-arguments

"""Integration tests."""

import json
import logging
import time

logger = logging.getLogger(__name__)


def wait_for_tunnel_healthy(cloudflare_api, tunnel_token):
    """Wait for a cloudflared tunnel to become healthy.

    Args:
        cloudflare_api (obj): Cloudflare API object.
        tunnel_token (str): Tunnel token.

    Raises:
        TimeoutError: If tunnel fails to become healthy in given timeout.
    """
    deadline = time.time() + 300
    while time.time() < deadline:
        tunnel_status = cloudflare_api.get_tunnel_status_by_token(tunnel_token)
        logger.info("tunnel status: %s", tunnel_status)
        if tunnel_status != "healthy":
            time.sleep(10)
        else:
            return
    raise TimeoutError("timeout waiting for tunnel healthy")


async def test_tunnel_token_config(ops_test, model, cloudflare_api, cloudflared_charm):
    """
    arrange: deploy the cloudflared charm.
    act: provide the tunnel-token charm config.
    assume: cloudflared tunnels provided in the charm config is up and healthy
    """
    base_charm = await model.deploy(
        "chrony", channel="latest/edge", config={"sources": "ntp://ntp.ubuntu.com"}
    )
    await model.integrate(base_charm.name, cloudflared_charm.name)
    tunnel_token = cloudflare_api.create_tunnel_token()
    _, secret_id, _ = await ops_test.juju(
        "add-secret", "test-tunnel-token", f"tunnel-token={tunnel_token}"
    )
    secret_id = secret_id.strip()
    await model.grant_secret("test-tunnel-token", cloudflared_charm.name)
    await cloudflared_charm.set_config({"tunnel-token": secret_id})
    await model.wait_for_idle()
    # required for deploying in LXD containers
    await ops_test.juju("exec", "--application", base_charm.name, "--", "sudo", "reboot")
    await model.wait_for_idle()
    wait_for_tunnel_healthy(cloudflare_api, tunnel_token)


async def test_cloudflared_route_integration(
    ops_test,
    model,
    cloudflare_api,
    cloudflared_charm,
    cloudflared_route_provider_1,
    cloudflared_route_provider_2,
):
    """
    arrange: deploy the cloudflared charm and cloudflared-route provider charms.
    act: provide some cloudflared tunnel tokens using cloudflared-route provider charms.
    assume: cloudflared tunnels provided in the integration is up and healthy.
    """
    await cloudflared_charm.set_config({"tunnel-token": ""})
    await model.integrate(
        f"{cloudflared_charm.name}:cloudflared-route", cloudflared_route_provider_1.name
    )
    await model.integrate(
        f"{cloudflared_charm.name}:cloudflared-route", cloudflared_route_provider_2.name
    )
    await model.wait_for_idle()
    tunnel_token_1 = cloudflare_api.create_tunnel_token()
    tunnel_token_2 = cloudflare_api.create_tunnel_token()
    action = await cloudflared_route_provider_1.units[0].run_action(
        "rpc", method="set_tunnel_token", args=json.dumps([tunnel_token_1])
    )
    await action.wait()
    action = await cloudflared_route_provider_2.units[0].run_action(
        "rpc", method="set_tunnel_token", args=json.dumps([tunnel_token_2])
    )
    await action.wait()
    await model.wait_for_idle()
    # required for deploying in LXD containers
    await ops_test.juju("exec", "--application", cloudflared_charm.name, "--", "sudo", "reboot")
    await model.wait_for_idle()
    wait_for_tunnel_healthy(cloudflare_api, tunnel_token_1)
    wait_for_tunnel_healthy(cloudflare_api, tunnel_token_2)

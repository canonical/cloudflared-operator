#!/usr/bin/env python3

# Copyright 2025 Canonical Ltd.
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


async def test_update_snap_channel(ops_test, model, cloudflared_charm):
    """
    arrange: deploy the cloudflared charm.
    act: update the charmed-cloudflared-snap-channel charm configuration.
    assume: cloudflared charm should refresh all charmed-cloudflared snap instances.
    """
    await cloudflared_charm.set_config({"charmed-cloudflared-snap-channel": ""})
    await model.wait_for_idle()
    _, snap_list, _ = await ops_test.juju("exec", "--unit", "chrony/0", "--", "snap", "list")
    assert "charmed-cloudflared_" in snap_list
    for line in snap_list.splitlines():
        if "charmed-cloudflared_" in line:
            assert "latest/edge" in line


async def test_nameserver(
    ops_test,
    model,
    cloudflare_api,
    cloudflared_charm,
    cloudflared_route_provider_1,
    dnsmasq,
    dnsmasq_ip,
):
    """
    arrange: deploy the cloudflared charm and cloudflared-route provider charms.
    act: provide cloudflared tunnel token with a specific nameserver setting for cloudflared
        using cloudflared-route provider charms.
    assume: cloudflared tunnels should use the given nameserver.
    """
    await cloudflared_charm.set_config({"tunnel-token": ""})
    await model.wait_for_idle()
    tunnel_token = cloudflare_api.create_tunnel_token()
    logger.info("use dnsmasq nameserver: %s", dnsmasq_ip)
    action = await cloudflared_route_provider_1.units[0].run_action(
        "rpc", method="set_nameserver", args=json.dumps([dnsmasq_ip])
    )
    await action.wait()
    action = await cloudflared_route_provider_1.units[0].run_action(
        "rpc", method="set_tunnel_token", args=json.dumps([tunnel_token])
    )
    await action.wait()
    await model.wait_for_idle()
    # required for deploying in LXD containers
    await ops_test.juju("exec", "--application", cloudflared_charm.name, "--", "sudo", "reboot")
    await model.wait_for_idle()
    wait_for_tunnel_healthy(cloudflare_api, tunnel_token)

    _, dnsmasq_logs, _ = await ops_test.juju(
        "exec", "--unit", f"{dnsmasq.name}/0", "--", "cat", "/var/log/dnsmasq.log"
    )

    assert "argotunnel.com" in dnsmasq_logs


async def test_remove(ops_test, model, cloudflared_charm):
    """
    arrange: deploy the cloudflared charm and cloudflared-route provider charms.
    act: remove the cloudflared charm.
    assume: cloudflared charm should uninstall all charmed-cloudflared snap instances.
    """
    _, snap_list, _ = await ops_test.juju("exec", "--unit", "chrony/0", "--", "snap", "list")
    assert "charmed-cloudflared_" in snap_list
    logger.info("snap list before removal: %s", snap_list)
    await ops_test.juju("remove-relation", cloudflared_charm.name, "chrony")
    await model.wait_for_idle(apps=[cloudflared_charm.name], wait_for_exact_units=0)
    _, snap_list, _ = await ops_test.juju("exec", "--unit", "chrony/0", "--", "snap", "list")
    assert "charmed-cloudflared_" not in snap_list
    logger.info("snap list after removal: %s", snap_list)
    await model.integrate("chrony", cloudflared_charm.name)


async def test_secret_config_permission(
    ops_test, model, cloudflared_charm, cloudflared_route_provider_1, cloudflared_route_provider_2
):
    """
    arrange: create a tunnel token juju secret without granting the secret access to the charm.
    act: configure the charm with the incorrect juju secret.
    assume: cloudflared charm should enter error state.
    """
    await ops_test.juju(
        "remove-relation", cloudflared_charm.name, cloudflared_route_provider_1.name
    )
    await ops_test.juju(
        "remove-relation", cloudflared_charm.name, cloudflared_route_provider_2.name
    )
    _, secret_id, _ = await ops_test.juju(
        "add-secret", "error-tunnel-token", "tunnel-token=foobar"
    )
    secret_id = secret_id.strip()
    await cloudflared_charm.set_config({"tunnel-token": secret_id})
    await model.wait_for_idle(raise_on_error=False)
    _, juju_status, _ = await ops_test.juju("status")
    logger.info("current juju status: %s", juju_status)
    assert "error" in juju_status

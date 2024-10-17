#!/usr/bin/env python3

# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

# pylint: disable=protected-access

"""Integration test fixtures."""

import json
import logging
import os
import pathlib
import random
import string
import textwrap
from datetime import datetime

import juju.application
import juju.model
import pytest
import pytest_asyncio
import requests

PROJECT_BASE = pathlib.Path(__file__).parent.parent.parent.resolve()


logger = logging.getLogger(__name__)


class CloudflareAPI:
    """Cloudflare API."""

    def __init__(self, account_id, api_token) -> None:
        """Initialize the Cloudflare API.

        Args:
            account_id: cloudflare account ID.
            api_token: cloudflare API token.
        """
        self._endpoint = f"https://api.cloudflare.com/client/v4/accounts/{account_id}/cfd_tunnel"
        self._session = requests.Session()
        self._session.headers.update(
            {"Authorization": f"Bearer {api_token}", "Content-Type": "application/json"}
        )
        self._created_tunnels: list[str] = []
        self._tunnel_token_lookup: dict[str, str] = {}

    def _create_tunnel(self) -> str:
        """Create a Tunnel.

        Returns:
            Cloudflare tunnel ID.
        """
        name = datetime.now().strftime("%Y%m%d-%H%M%S-")
        # bandit complains about using random instead of secrets here
        name = name + "".join(random.choices(string.ascii_letters + string.digits, k=4))  # nosec
        response = self._session.post(
            self._endpoint, json={"name": name, "config_src": "cloudflare"}, timeout=10
        )
        response.raise_for_status()
        tunnel_id = response.json()["result"]["id"]
        logger.info("created tunnel %s", tunnel_id)
        self._created_tunnels.append(tunnel_id)
        return tunnel_id

    def _get_tunnel_token(self, tunnel_id: str) -> str:
        """Get tunnel token.

        Args:
            tunnel_id: cloudflare tunnel ID.

        Returns:
            Tunnel token.
        """
        response = self._session.get(f"{self._endpoint}/{tunnel_id}/token", timeout=10)
        response.raise_for_status()
        tunnel_token = response.json()["result"]
        self._tunnel_token_lookup[tunnel_token] = tunnel_id
        return tunnel_token

    def create_tunnel_token(self) -> str:
        """Create a tunnel and return its tunnel token.

        Returns:
            Tunnel token.
        """
        tunnel_id = self._create_tunnel()
        return self._get_tunnel_token(tunnel_id)

    def _get_tunnel_status(self, tunnel_id: str) -> str:
        """Get tunnel status.

        Args:
            tunnel_id: cloudflare tunnel ID.

        Returns:
            Tunnel status.
        """
        response = self._session.get(f"{self._endpoint}/{tunnel_id}", timeout=10)
        response.raise_for_status()
        return response.json()["result"]["status"]

    def get_tunnel_status_by_token(self, tunnel_token: str) -> str:
        """Get tunnel status by its tunnel token.

        Args:
            tunnel_token: cloudflare tunnel token.

        Returns:
            Tunnel status.
        """
        tunnel_id = self._tunnel_token_lookup[tunnel_token]
        return self._get_tunnel_status(tunnel_id)

    def delete_tunnel(self, tunnel_id: str) -> None:
        """Delete a tunnel.

        Args:
            tunnel_id: cloudflare tunnel ID.
        """
        logger.info("deleting tunnel %s", tunnel_id)
        response = self._session.delete(f"{self._endpoint}/{tunnel_id}", timeout=10)
        response.raise_for_status()


@pytest.fixture(scope="module")
def cloudflare_api():
    """Cloudflare API fixture."""
    account_id = os.environ["CLOUDFLARE_ACCOUNT_ID"]
    api_token = os.environ["CLOUDFLARE_API_TOKEN"]
    api = CloudflareAPI(account_id=account_id, api_token=api_token)

    yield api

    for tunnel_id in api._created_tunnels:
        try:
            api.delete_tunnel(tunnel_id)
        except requests.exceptions.RequestException:
            logger.exception("failed to delete tunnel %s", tunnel_id)


@pytest.fixture(scope="module", name="model")
def model_fixture(ops_test) -> juju.model.Model:
    """Testing juju model fixture."""
    assert ops_test.model
    return ops_test.model


@pytest_asyncio.fixture(scope="module")
async def cloudflared_charm(model, pytestconfig: pytest.Config) -> juju.application.Application:
    """Deploy the cloudflared charm."""
    charm = pytestconfig.getoption("--charm-file")
    return await model.deploy(f"./{charm}", num_units=0)


SRC_OVERWRITE = json.dumps(
    {
        "any_charm.py": textwrap.dedent(
            """\
            import ops
            from cloudflared_route import CloudflaredRouteProvider
            from any_charm_base import AnyCharmBase

            class AnyCharm(AnyCharmBase):
                def __init__(self, *args, **kwargs):
                    super().__init__(*args, **kwargs)
                    self.cloudflared_route = CloudflaredRouteProvider(
                        charm=self,
                        relation_name="provide-cloudflared-route"
                    )
                    self.unit.status = ops.ActiveStatus()

                def set_tunnel_token(self, tunnel_token):
                    return self.cloudflared_route.set_tunnel_token(tunnel_token)

                def unset_tunnel_token(self):
                    self.cloudflared_route.unset_tunnel_token()

                def set_nameserver(self, nameserver):
                    return self.cloudflared_route.set_nameserver(nameserver)
            """
        ),
        "cloudflared_route.py": (
            PROJECT_BASE / "lib/charms/cloudflare_configurator/v0/cloudflared_route.py"
        ).read_text(),
    }
)


@pytest_asyncio.fixture(scope="module")
async def cloudflared_route_provider_1(model, cloudflared_charm) -> juju.application.Application:
    """Deploy a cloudflared-route requirer using any-charm."""
    charm = await model.deploy(
        "any-charm",
        "cloudflared-route-provider-one",
        config={
            "src-overwrite": SRC_OVERWRITE,
        },
        channel="latest/edge",
    )
    await model.integrate(f"{cloudflared_charm.name}:cloudflared-route", charm.name)
    return charm


@pytest_asyncio.fixture(scope="module")
async def cloudflared_route_provider_2(model) -> juju.application.Application:
    """Deploy a cloudflared-route requirer using any-charm."""
    charm = await model.deploy(
        "any-charm",
        "cloudflared-route-provider-two",
        config={
            "src-overwrite": SRC_OVERWRITE,
        },
        channel="latest/edge",
    )
    await model.integrate(f"{cloudflared_charm.name}:cloudflared-route", charm.name)
    return charm


@pytest_asyncio.fixture(name="dnsmasq", scope="module")
async def dnsmasq_fixture(ops_test, model) -> juju.application.Application:
    """Deploy a dnsmasq server."""
    dnsmasq = await model.deploy(
        "ubuntu",
        "dnsmasq",
        channel="latest/edge",
    )
    await model.wait_for_idle()
    await ops_test.juju("exec", "--application", dnsmasq.name, "--", "apt", "update")
    await ops_test.juju(
        "exec", "--application", dnsmasq.name, "--", "apt", "install", "dnsmasq", "-y"
    )
    await ops_test.juju(
        "exec",
        "--application",
        dnsmasq.name,
        "--",
        "bash",
        "-c",
        "echo server=1.1.1.1 >> /etc/dnsmasq.conf",
    )
    await ops_test.juju(
        "exec",
        "--application",
        dnsmasq.name,
        "--",
        "bash",
        "-c",
        "echo bind-interfaces >> /etc/dnsmasq.conf",
    )
    await ops_test.juju(
        "exec",
        "--application",
        dnsmasq.name,
        "--",
        "bash",
        "-c",
        "echo log-queries >> /etc/dnsmasq.conf",
    )
    await ops_test.juju(
        "exec",
        "--application",
        dnsmasq.name,
        "--",
        "bash",
        "-c",
        "echo log-facility=/var/log/dnsmasq.log >> /etc/dnsmasq.conf",
    )
    return dnsmasq


@pytest_asyncio.fixture(scope="module")
async def dnsmasq_ip(ops_test, dnsmasq) -> str:
    """Get the IP address of dnsmasq."""
    _, status, _ = await ops_test.juju("status", "--format", "json")
    status = json.loads(status)
    units = status["applications"][dnsmasq.name]["units"]
    return list(units.values())[0]["public-address"]

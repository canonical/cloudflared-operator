#!/usr/bin/env python3

# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

# Learn more at: https://juju.is/docs/sdk

"""Cloudflared charm service."""

import logging
import typing

import ops
from charms.cloudflare_configurator.v0.cloudflared_route import CloudflaredRouteRequirer
from charms.grafana_agent.v0.cos_agent import COSAgentProvider
from charms.operator_libs_linux.v2 import snap

logger = logging.getLogger(__name__)


class CloudflaredCharm(ops.CharmBase):
    """Cloudflared charm service."""

    def __init__(self, *args: typing.Any):
        """Construct.

        Args:
            args: Arguments passed to the CharmBase parent constructor.
        """
        super().__init__(*args)
        self.framework.observe(self.on.install, self._on_install)
        self.framework.observe(self.on.config_changed, self._reconcile)
        self.framework.observe(self.on.secret_changed, self._reconcile)
        self.framework.observe(self.on["cloudflared-route"].relation_changed, self._reconcile)
        self._cloudflared_route = CloudflaredRouteRequirer(self)
        try:
            tunnel_tokens = self._get_tunnel_tokens()
        except ValueError:
            tunnel_tokens = []
        self._grafana_agent = COSAgentProvider(
            self,
            metrics_endpoints=[
                {"path": "/metrics", "port": metrics_port}
                for metrics_port in range(15300, 15300 + len(tunnel_tokens))
            ],
            dashboard_dirs=["./src/grafana_dashboards"],
        )

    def _on_install(self, _: ops.EventBase) -> None:
        """Install the charmed-cloudflared snap."""
        self._install_cloudflared_snap()

    def _reconcile(self, _: ops.EventBase) -> None:
        """Handle changed configuration."""
        try:
            tunnel_tokens = self._get_tunnel_tokens()
        except ValueError:
            self.unit.status = ops.BlockedStatus(
                "tunnel-token is provided in both the config and integration"
            )
            return
        self._config_cloudflared_snap({"tokens": ",".join(tunnel_tokens)})
        self.unit.status = ops.ActiveStatus()

    def _install_cloudflared_snap(self) -> None:  # pragma: nocover
        """Install the charmed-cloudflared snap."""
        snap.install_local("./src/charmed-cloudflared_2024.9.1_amd64.snap.zip", dangerous=True)

    def _config_cloudflared_snap(self, config: dict[str, str]) -> None:  # pragma: nocover
        """Configure charmed-cloudflared snap.

        Args:
            config: charmed-cloudflared configuration.
        """
        charmed_cloudflared = snap.SnapCache()["charmed-cloudflared"]
        charmed_cloudflared.set(config)

    def _get_tunnel_tokens(self) -> list[str]:
        """Receive tunnel tokens from all configuration sources.

        Returns:
            Cloudflared tunnel tokens.

        Raises:
            ValueError: If there's a conflict between different configuration sources.
        """
        config_tunnel_tokens = self._get_tunnel_tokens_from_config()
        integration_tunnel_tokens = self._get_tunnel_token_from_integration()
        if config_tunnel_tokens and integration_tunnel_tokens:
            raise ValueError("received tunnel-tokens from config and integration")
        return config_tunnel_tokens or integration_tunnel_tokens

    def _get_tunnel_tokens_from_config(self) -> list[str]:
        """Receive tunnel tokens from charm configuration.

        Returns:
            Cloudflared tunnel tokens.
        """
        tokens = []
        secret_id = typing.cast(str, self.config.get("tunnel-token"))
        if secret_id:
            secret = self.model.get_secret(id=secret_id)
            tokens.append(secret.get_content(refresh=True)["tunnel-token"])
        return tokens

    def _get_tunnel_token_from_integration(self) -> list[str]:
        """Receive tunnel tokens from charm integrations.

        Returns:
            Cloudflared tunnel tokens.
        """
        return self._cloudflared_route.get_tunnel_tokens()


if __name__ == "__main__":  # pragma: nocover
    ops.main.main(CloudflaredCharm)

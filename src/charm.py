#!/usr/bin/env python3

# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

# Learn more at: https://juju.is/docs/sdk

"""Cloudflared charm service."""

import logging
import subprocess  # nosec
import typing

import ops
from charms.cloudflare_configurator.v0.cloudflared_route import CloudflaredRouteRequirer
from charms.grafana_agent.v0.cos_agent import COSAgentProvider
from charms.operator_libs_linux.v2 import snap

logger = logging.getLogger(__name__)

CLOUDFLARED_ROUTE_INTEGRATION_NAME = "cloudflared-route"
# this is not a hardcoded password
TUNNEL_TOKEN_CONFIG_NAME = "tunnel-token"  # nosec


class InvalidConfig(ValueError):
    """Charm received invalid configurations."""


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
        self._snap_client = snap.SnapClient()
        self._cloudflared_route = CloudflaredRouteRequirer(self)
        self._grafana_agent = COSAgentProvider(
            self,
            metrics_endpoints=[
                {"path": "/metrics", "port": metrics_port}
                for metrics_port in self._get_instance_metrics_ports().values()
            ],
            dashboard_dirs=["./src/grafana_dashboards"],
        )

    def _on_install(self, _: ops.EventBase) -> None:
        """Install the charmed-cloudflared snap."""
        # pylint: disable=protected-access
        snap._system_set("experimental.parallel-instances", "true")

    def _reconcile(self, _: ops.EventBase) -> None:
        """Handle changed configuration."""
        try:
            metrics_ports = self._get_instance_metrics_ports()
            tunnel_tokens = self._get_instance_tunnel_tokens()
        except InvalidConfig as exc:
            logger.exception("charm received invalid configuration")
            self.unit.status = ops.BlockedStatus(str(exc))
            return
        for remove_instance in self._installed_cloudflared_snaps() - metrics_ports.keys():
            self._remove_cloudflared_snap(remove_instance)
        for install_instance in metrics_ports.keys() - self._installed_cloudflared_snaps():
            self._install_cloudflared_snap(install_instance)

        for instance, tunnel_token in tunnel_tokens.items():
            self._config_cloudflared_snap(
                name=instance,
                config={
                    "tunnel-token": tunnel_token,
                    "metrics-port": metrics_ports[instance],
                },
            )
        self.unit.status = ops.ActiveStatus()

    @staticmethod
    def _install_cloudflared_snap(name: str) -> None:  # pragma: nocover
        """Install the charmed-cloudflared snap.

        Args:
            name: snap instance name (charmed-cloudflared_relation1 or charmed-cloudflared_config0)
        """
        subprocess.check_call(  # nosec
            [
                "snap",
                "install",
                "--name",
                name,
                "--dangerous",
                "./src/charmed-cloudflared_2024.9.1_amd64.snap.zip",
            ]
        )

    @staticmethod
    def _config_cloudflared_snap(
        name: str, config: dict[str, str | int]
    ) -> None:  # pragma: nocover
        """Configure charmed-cloudflared snap.

        Args:
            name: snap instance name (charmed-cloudflared_relation1 or charmed-cloudflared_config0)
            config: charmed-cloudflared configuration.
        """
        charmed_cloudflared = snap.SnapCache()[name]
        if all(charmed_cloudflared.get(key) == str(value) for key, value in config.items()):
            return
        charmed_cloudflared.set(config, typed=True)

    @staticmethod
    def _remove_cloudflared_snap(name: str) -> None:  # pragma: nocover
        """Remove charmed-cloudflared snap.

        Args:
            name: snap instance name (charmed-cloudflared_relation1 or charmed-cloudflared_config0)
        """
        snap.remove(name)

    def _installed_cloudflared_snaps(self) -> set[str]:  # pragma: nocover
        """Get installed charmed-cloudflared snap instances.

        Returns:
            A set of installed charmed-cloudflared snap instances.
        """
        installed_charmed_cloudflared = set()
        installed_snaps = self._snap_client.get_installed_snaps()
        for installed_snap in installed_snaps:
            if installed_snap["name"].startswith("charmed-cloudflared"):
                installed_charmed_cloudflared.add(installed_snap["name"])
        return installed_charmed_cloudflared

    def _get_instance_tunnel_tokens(self) -> dict[str, str]:
        """Get tunnel tokens for all charmed-cloudflared snap instances.

        Returns:
            A mapping of charmed-cloudflared snap instance name to tunnel tokens.

        Raises:
            InvalidConfig: If the tunnel-token charm configuration is invalid.
        """
        tunnel_tokens = {}
        tunnel_token_config = typing.cast(str | None, self.config.get(TUNNEL_TOKEN_CONFIG_NAME))
        if tunnel_token_config:
            try:
                secret = self.model.get_secret(id=tunnel_token_config)
                secret_value = secret.get_content(refresh=True)["tunnel-token"]
                tunnel_tokens["charmed-cloudflared_config0"] = secret_value
            except (ops.SecretNotFoundError, ops.ModelError, KeyError) as exc:
                raise InvalidConfig("invalid tunnel-token config") from exc
        relations = self.model.relations[CLOUDFLARED_ROUTE_INTEGRATION_NAME]
        if tunnel_tokens and relations:
            raise InvalidConfig("tunnel-token is provided by both the config and integration")
        for relation in relations:
            tunnel_token = self._cloudflared_route.get_tunnel_token(relation)
            if tunnel_token:
                tunnel_tokens[f"charmed-cloudflared_relation{relation.id}"] = tunnel_token
        return tunnel_tokens

    def _get_instance_metrics_ports(self) -> dict[str, int]:
        """Get metric ports for all charmed-cloudflared snap instances.

        Returns:
            A mapping of charmed-cloudflared snap instance name to metrics ports.
        """
        metrics_ports = {}
        if self.config.get(TUNNEL_TOKEN_CONFIG_NAME):
            metrics_ports["charmed-cloudflared_config0"] = 15299
        for relation in self.model.relations[CLOUDFLARED_ROUTE_INTEGRATION_NAME]:
            if relation.app is None:
                continue
            metrics_ports[f"charmed-cloudflared_relation{relation.id}"] = 15300 + relation.id
        return metrics_ports


if __name__ == "__main__":  # pragma: nocover
    ops.main(CloudflaredCharm)

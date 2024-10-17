#!/usr/bin/env python3

# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

# Learn more at: https://juju.is/docs/sdk

"""Cloudflared charm service."""

import collections
import logging
import pathlib
import subprocess  # nosec
import typing

import ops
from charms.cloudflare_configurator.v0.cloudflared_route import (
    CloudflaredRouteRequirer,
    InvalidIntegration,
)
from charms.grafana_agent.v0.cos_agent import COSAgentProvider
from charms.operator_libs_linux.v2 import snap

logger = logging.getLogger(__name__)

CLOUDFLARED_ROUTE_INTEGRATION_NAME = "cloudflared-route"
# this is not a hardcoded password
TUNNEL_TOKEN_CONFIG_NAME = "tunnel-token"  # nosec
CHARMED_CLOUDFLARED_SNAP_NAME = "charmed-cloudflared"


class InvalidConfig(ValueError):
    """Charm received invalid configurations."""


CloudflaredSpec = collections.namedtuple("CloudflaredSpec", "tunnel_token nameserver")


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
        # https://snapcraft.io/docs/parallel-installs
        # pylint: disable=protected-access
        snap._system_set("experimental.parallel-instances", "true")

    def _reconcile(self, _: ops.EventBase) -> None:
        """Handle changed configuration."""
        try:
            metrics_ports = self._get_instance_metrics_ports()
            tunnel_specs = self._get_instance_tunnel_specs()
        except InvalidConfig as exc:
            logger.exception("charm received invalid configuration")
            self.unit.status = ops.BlockedStatus(str(exc))
            return
        installed_charmed_cloudflared = set()
        installed_snaps = self._snap_client.get_installed_snaps()
        for installed_snap in installed_snaps:
            if installed_snap["name"].startswith(CHARMED_CLOUDFLARED_SNAP_NAME):
                installed_charmed_cloudflared.add(installed_snap["name"])
        required_snap_instances = set(metrics_ports.keys())
        for remove_instance in installed_charmed_cloudflared - required_snap_instances:
            logger.info("removing charmed-cloudflared instance: %s", remove_instance)
            snap.remove(remove_instance)
        for install_instance in required_snap_instances - installed_charmed_cloudflared:
            logger.info("installing charmed-cloudflared instance: %s", install_instance)
            # snap charm library doesn't support parallel instances
            subprocess.check_call(  # nosec
                [
                    "snap",
                    "install",
                    "./src/charmed-cloudflared_2024.9.1_amd64.snap.zip",
                    "--name",
                    install_instance,
                    "--dangerous"
                ]
            )
        for instance, tunnel_spec in tunnel_specs.items():
            charmed_cloudflared = snap.SnapCache()[instance]
            self._update_cloudflared_resolv_conf(instance, tunnel_spec.nameserver)
            config = {
                "tunnel-token": tunnel_spec.tunnel_token,
                "metrics-port": metrics_ports[instance],
            }
            if all(charmed_cloudflared.get(key) == str(value) for key, value in config.items()):
                continue
            logger.info("configuring charmed-cloudflared instance: %s", instance)
            charmed_cloudflared.set(config, typed=True)
        self.unit.status = ops.ActiveStatus()

    def _update_cloudflared_resolv_conf(self, name: str, nameserver: str | None) -> None:
        """Updates the resolv.conf file for the specified charmed-cloudflared snap instance.

        Args:
            name: The name of the charmed-cloudflared snap instance.
            nameserver: The nameserver to set for the instance. If None, the system default is used
        """
        if nameserver is None:
            resolv_conf = pathlib.Path("/etc/resolv.conf").read_text(encoding="utf-8")
        else:
            resolv_conf = f"nameserver {nameserver}"
        current_resolv_conf = pathlib.Path(f"/var/snap/{name}/current/etc/resolv.conf")
        if (
            not current_resolv_conf.exists()
            or current_resolv_conf.read_text(encoding="utf-8") != resolv_conf
        ):
            current_resolv_conf.write_text(resolv_conf, encoding="utf-8")

    def _get_instance_tunnel_specs(self) -> dict[str, CloudflaredSpec]:
        """Get cloudflared configurations for all charmed-cloudflared snap instances.

        Returns:
            A mapping of charmed-cloudflared snap instance name to cloudflared configurations.

        Raises:
            InvalidConfig: If the tunnel-token charm configuration is invalid.
            RuntimeError: If the relation ID exceeds maximum allowed value.
        """
        tunnel_token_config = typing.cast(str | None, self.config.get(TUNNEL_TOKEN_CONFIG_NAME))
        relations = self.model.relations[CLOUDFLARED_ROUTE_INTEGRATION_NAME]
        if tunnel_token_config and relations:
            raise InvalidConfig("tunnel-token is provided by both the config and integration")
        if tunnel_token_config:
            try:
                secret = self.model.get_secret(id=tunnel_token_config)
                secret_value = secret.get_content(refresh=True)["tunnel-token"]
                return {
                    f"{CHARMED_CLOUDFLARED_SNAP_NAME}_config0": CloudflaredSpec(
                        tunnel_token=secret_value,
                        nameserver=None,
                    )
                }
            except (ops.SecretNotFoundError, ops.ModelError, KeyError) as exc:
                raise InvalidConfig("invalid tunnel-token config") from exc
        tunnel_tokens = {}
        for relation in relations:
            try:
                tunnel_token = self._cloudflared_route.get_tunnel_token(relation)
            except InvalidIntegration as exc:
                raise InvalidConfig(
                    "received invalid data from "
                    f"{CLOUDFLARED_ROUTE_INTEGRATION_NAME} integration: {exc}"
                ) from exc
            if relation.id > 999999:
                raise RuntimeError("relation id exceeds maximum allowed value")
            if tunnel_token:
                tunnel_tokens[f"{CHARMED_CLOUDFLARED_SNAP_NAME}_rel{relation.id}"] = (
                    CloudflaredSpec(
                        tunnel_token=tunnel_token,
                        nameserver=self._cloudflared_route.get_nameserver(relation),
                    )
                )
        return tunnel_tokens

    def _get_instance_metrics_ports(self) -> dict[str, int]:
        """Get metric ports for all charmed-cloudflared snap instances.

        Returns:
            A mapping of charmed-cloudflared snap instance name to metrics ports.
        """
        metrics_ports = {}
        if self.config.get(TUNNEL_TOKEN_CONFIG_NAME):
            metrics_ports[f"{CHARMED_CLOUDFLARED_SNAP_NAME}_config0"] = 15299
        for relation in self.model.relations[CLOUDFLARED_ROUTE_INTEGRATION_NAME]:
            if relation.app is None:
                continue
            metrics_ports[f"{CHARMED_CLOUDFLARED_SNAP_NAME}_rel{relation.id}"] = (
                15300 + relation.id
            )
        return metrics_ports


if __name__ == "__main__":  # pragma: nocover
    ops.main(CloudflaredCharm)

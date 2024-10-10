#!/usr/bin/env python3

# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

"""Unit test fixtures."""

import pytest

import charm


@pytest.fixture(scope="function", name="snaps")
def snaps_fixture() -> dict[str, dict[str, str | int]]:
    """Snap system stub."""
    return {}


@pytest.fixture(scope="function")
def cloudflared_charm_cls(monkeypatch, snaps):
    """Patch the cloudflared charm."""
    monkeypatch.setattr(
        charm.CloudflaredCharm,
        "_install_cloudflared_snap",
        lambda self, name: snaps.update({name: {}}),
    )
    monkeypatch.setattr(
        charm.CloudflaredCharm,
        "_config_cloudflared_snap",
        lambda self, name, config: snaps.update({name: config}),
    )
    monkeypatch.setattr(
        charm.CloudflaredCharm,
        "_remove_cloudflared_snap",
        lambda self, name: snaps.pop(name),
    )
    monkeypatch.setattr(
        charm.CloudflaredCharm, "_installed_cloudflared_snaps", lambda self: set(snaps)
    )
    return charm.CloudflaredCharm

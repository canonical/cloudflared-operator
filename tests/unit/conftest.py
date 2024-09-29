#!/usr/bin/env python3

# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

"""Unit test fixtures."""

import unittest.mock

import pytest

import charm


@pytest.fixture(scope="function")
def cloudflared_charm_cls(monkeypatch):
    """Patch the cloudflared charm."""
    monkeypatch.setattr(
        charm.CloudflaredCharm, "_install_cloudflared_snap", unittest.mock.MagicMock()
    )
    monkeypatch.setattr(
        charm.CloudflaredCharm, "_config_cloudflared_snap", unittest.mock.MagicMock()
    )
    return charm.CloudflaredCharm

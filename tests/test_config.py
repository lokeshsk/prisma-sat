"""
Unit tests for configuration management.
"""

import os
from prisma_pilot.config import PrismaConfig


def test_config_properties(monkeypatch):
    monkeypatch.setenv("PRISMA_USER", "test_user")
    monkeypatch.setenv("PRISMA_PASS", "test_pass")

    cfg = PrismaConfig()
    assert cfg.username == "test_user"
    assert cfg.password == "test_pass"
    assert cfg.has_credentials is True


def test_config_fallback_properties(monkeypatch):
    monkeypatch.delenv("PRISMA_USER", raising=False)
    monkeypatch.delenv("PRISMA_PASS", raising=False)
    monkeypatch.setenv("PRISMA_USERNAME", "fallback_user")
    monkeypatch.setenv("PRISMA_PASSWORD", "fallback_pass")

    cfg = PrismaConfig()
    assert cfg.username == "fallback_user"
    assert cfg.password == "fallback_pass"
    assert cfg.has_credentials is True

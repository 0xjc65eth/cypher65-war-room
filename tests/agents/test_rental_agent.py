"""
Unit tests for RentalAgent.
Tests provider connection status based on env vars.
"""

import os
import pytest


class TestRentalAgentRun:

    def test_mrr_credentials_set_marks_connected(self, monkeypatch):
        """MRR_API_KEY + MRR_API_SECRET → mrr.connected=True."""
        monkeypatch.setenv("MRR_API_KEY", "test-key-123")
        monkeypatch.setenv("MRR_API_SECRET", "test-secret-456")

        from hermes.agents.rental_agent import RentalAgent

        agent = RentalAgent()
        result = agent.run({})

        assert result["agent"] == "RentalAgent"
        assert result["analysis"]["providers"]["mrr"]["connected"] is True
        assert result["analysis"]["status"] == "CONNECTED"

    def test_no_credentials_marks_disconnected(self, monkeypatch):
        """No MRR env vars → all providers disconnected."""
        monkeypatch.delenv("MRR_API_KEY", raising=False)
        monkeypatch.delenv("MRR_API_SECRET", raising=False)

        from hermes.agents.rental_agent import RentalAgent

        agent = RentalAgent()
        result = agent.run({})

        assert result["analysis"]["providers"]["mrr"]["connected"] is False
        assert result["analysis"]["providers"]["braiins"]["connected"] is False
        assert "DATA SOURCE NOT CONNECTED" in result["analysis"]["status"]

    def test_three_providers_listed(self, monkeypatch):
        """All three providers (braiins, mrr, nicehash) are present."""
        monkeypatch.delenv("MRR_API_KEY", raising=False)
        monkeypatch.delenv("MRR_API_SECRET", raising=False)

        from hermes.agents.rental_agent import RentalAgent

        agent = RentalAgent()
        result = agent.run({})

        providers = result["analysis"]["providers"]
        assert "braiins" in providers
        assert "mrr" in providers
        assert "nicehash" in providers
        assert providers["braiins"]["name"] == "Braiins Hashpower"
        assert providers["mrr"]["name"] == "MiningRigRentals"
        assert providers["nicehash"]["name"] == "NiceHash"

    def test_message_when_disconnected(self, monkeypatch):
        """Disconnected → message mentions setting MRR_API_KEY."""
        monkeypatch.delenv("MRR_API_KEY", raising=False)
        monkeypatch.delenv("MRR_API_SECRET", raising=False)

        from hermes.agents.rental_agent import RentalAgent

        agent = RentalAgent()
        result = agent.run({})

        assert "Set MRR_API_KEY" in result["analysis"]["message"]

    def test_message_when_connected(self, monkeypatch):
        """Connected → message mentions integration status."""
        monkeypatch.setenv("MRR_API_KEY", "key")
        monkeypatch.setenv("MRR_API_SECRET", "secret")

        from hermes.agents.rental_agent import RentalAgent

        agent = RentalAgent()
        result = agent.run({})

        assert "MiningRigRentals connected" in result["analysis"]["message"]

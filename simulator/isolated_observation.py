"""Harness-only fixed identity adapters; public CLI defaults remain testnet11."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "integration"))
from network_identity import ISOLATED_REHEARSAL
from testnet_probe import _observe_for_identity
from confirmation import _confirm_for_identity


def observe_isolated(call, requested_coin=None, puzzle=None, amount=None):
    return _observe_for_identity(call, ISOLATED_REHEARSAL, requested_coin, puzzle, amount)


def confirm_isolated(call, expected_spend, expected_children, depth, previous_anchor=None):
    return _confirm_for_identity(call, ISOLATED_REHEARSAL, expected_spend, expected_children, depth, previous_anchor)

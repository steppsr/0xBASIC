"""Fixed harness-only offline adapters. No input/CLI network selector."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "integration"))
from network_identity import ISOLATED_REHEARSAL
from prepare_fee import _prepare_for_identity
from verify_signed_fee import _verify_for_identity


def prepare_isolated(binary, manifest, observation, solution, max_fee, max_age=300):
    return _prepare_for_identity(binary, manifest, observation, solution, max_fee, ISOLATED_REHEARSAL, max_age)


def verify_isolated(binary, manifest, observation, solution, preparation, response, max_fee, max_age=300):
    return _verify_for_identity(binary, manifest, observation, solution, preparation, response, max_fee, ISOLATED_REHEARSAL, max_age)

"""Harness-only fixed simulator dispatch adapter; no input-selected identity."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "integration"))
from network_identity import ISOLATED_REHEARSAL
from submission_attempt import _read_for_identity
from submission_dispatch import _dispatch_for_identity, _worker_main


def dispatch_isolated(args):
    return _dispatch_for_identity(args, ISOLATED_REHEARSAL)


def read_isolated_attempt(path):
    return _read_for_identity(path, ISOLATED_REHEARSAL)


if __name__ == "__main__":
    _worker_main(ISOLATED_REHEARSAL)

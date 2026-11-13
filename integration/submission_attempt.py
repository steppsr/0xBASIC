"""Internal single-attempt persistence boundary; no RPC adapter or public CLI."""
import copy
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile

from testnet_probe import require
from network_identity import PUBLIC_TESTNET, validate as validate_identity

MAX_BYTES = 16 * 1024
IDENTIFIERS = {"bundle_id", "bundle_sha256", "input_id", "preparation_sha256", "signature_response_sha256"}
OUTCOMES = {"reply-success", "reply-pending", "reply-failure", "unknown"}


def _encoded(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def _context(value):
    require(type(value) is dict and set(value) == IDENTIFIERS, "Invalid attempt identifiers")
    require(all(type(v) is str and re.fullmatch("[0-9a-f]{64}", v) for v in value.values()),
            "Invalid attempt identifier")
    return copy.deepcopy(value)


def _document(context, outcome, identity=PUBLIC_TESTNET):
    validate_identity(identity)
    body = {"schema_version": 1, "validation": "submission-attempt-record-only" if identity is PUBLIC_TESTNET else "isolated-submission-attempt-record-only",
            "network": identity.network(),
            "context": _context(context), "outcome": outcome,
            "automatic_retry_allowed": False, "confirmation_established": False}
    return {**body, "sha256": hashlib.sha256(_encoded(body)).hexdigest()}


def read_attempt(path):
    return _read_for_identity(path, PUBLIC_TESTNET)


def _read_for_identity(path, identity):
    validate_identity(identity)
    path = Path(path)
    require(not path.is_symlink(), "Attempt symlink forbidden")
    with path.open("rb") as handle:
        data = handle.read(MAX_BYTES + 1)
    require(len(data) <= MAX_BYTES, "Attempt exceeds size bound")
    def pairs(items):
        result = {}
        for key, value in items:
            require(key not in result, "Duplicate attempt key")
            result[key] = value
        return result
    def invalid(_):
        raise ValueError("Non-finite attempt number")
    doc = json.loads(data.decode("utf-8"), object_pairs_hook=pairs, parse_constant=invalid)
    require(type(doc) is dict and set(doc) == {"schema_version", "validation", "network", "context", "outcome",
            "automatic_retry_allowed", "confirmation_established", "sha256"}, "Invalid attempt schema")
    require(doc["outcome"] is None or (type(doc["outcome"]) is str and doc["outcome"] in OUTCOMES),
            "Invalid attempt outcome")
    # Canonical byte comparison also rejects bool/int substitutions and extra fields.
    require(_encoded(doc) == _encoded(_document(doc["context"], doc["outcome"], identity)), "Invalid attempt content/hash")
    return {**doc, "dispatch_may_have_occurred": True, "fresh_chain_validation_required": True}


def _finish(path, initial, context, outcome, identity=PUBLIC_TESTNET):
    validate_identity(identity)
    require(not path.is_symlink(), "Attempt symlink forbidden")
    with path.open("rb") as handle:
        require(handle.read(MAX_BYTES + 1) == initial, "Attempt changed outside writer")
    data = _encoded(_document(context, outcome, identity)) + b"\n"
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as handle:
            temporary = Path(handle.name)
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        temporary.replace(path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _attempt(path, context, dispatch):
    return _attempt_for_identity(path, context, dispatch, PUBLIC_TESTNET)


def _attempt_for_identity(path, context, dispatch, identity):
    """Persist intent, call a prevalidated adapter once, persist its normalized outcome.

    Caller MUST verify signed bytes/approval and fresh node state before entry.
    No production caller exists yet. The callback must bind the exact verified
    bundle and return a normalized reply label; this module cannot verify that.
    """
    validate_identity(identity)
    context = _context(context)
    require(callable(dispatch), "Missing dispatch adapter")
    path = Path(path)
    require(not path.is_symlink(), "Attempt symlink forbidden")
    initial = _encoded(_document(context, None, identity)) + b"\n"
    # No implicit directory creation or reuse of an existing attempt.
    # A creation/fsync failure may leave a partial file, but never calls dispatch.
    with path.open("xb") as handle:
        handle.write(initial)
        handle.flush()
        os.fsync(handle.fileno())
    try:
        outcome = dispatch()
        require(type(outcome) is str and outcome in OUTCOMES - {"unknown"}, "Invalid adapter reply")
    except (Exception, KeyboardInterrupt):
        # If saving unknown fails, the original intent remains conservative.
        _finish(path, initial, context, "unknown", identity)
        raise
    _finish(path, initial, context, outcome, identity)
    return _read_for_identity(path, identity)

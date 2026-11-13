"""Internal single-bundle push transport; callers must supply independently verified bytes."""
import json
import re

from testnet_probe import Transport, require, uint

MAX_REQUEST = 1024 * 1024


def _hex(value, size=None):
    require(type(value) is str and re.fullmatch(r"(?:0x)?(?:[0-9a-fA-F]{2})+", value) is not None,
            "Invalid bundle hex")
    raw = value.removeprefix("0x")
    require(size is None or len(raw) == size * 2, "Invalid bundle field length")


def _freeze(bundle):
    require(type(bundle) is dict and set(bundle) == {"coin_spends", "aggregated_signature"}, "Invalid bundle schema")
    _hex(bundle["aggregated_signature"], 96)
    spends = bundle["coin_spends"]
    require(type(spends) is list and len(spends) == 1, "Expected one spend")
    spend = spends[0]
    require(type(spend) is dict and set(spend) == {"coin", "puzzle_reveal", "solution"}, "Invalid spend schema")
    coin = spend["coin"]
    require(type(coin) is dict and set(coin) == {"parent_coin_info", "puzzle_hash", "amount"}, "Invalid coin schema")
    _hex(coin["parent_coin_info"], 32)
    _hex(coin["puzzle_hash"], 32)
    uint(coin["amount"])
    _hex(spend["puzzle_reveal"])
    _hex(spend["solution"])
    data = json.dumps({"spend_bundle": bundle}, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    require(len(data) <= MAX_REQUEST, "Submission request too large")
    return data


def _reply(value):
    require(type(value) is dict and set(value) == {"success", "status"}
            and value["success"] is True and type(value["status"]) is str
            and value["status"] in {"SUCCESS", "PENDING"}, "Ambiguous submission reply")
    return {"SUCCESS": "reply-success", "PENDING": "reply-pending"}[value["status"]]


class _SubmissionTransport(Transport):
    """Separate mutating allowlist; no CLI, approval or live-state validation here.

    Inherits explicit loopback mutual TLS, no proxy/redirect/retry, bounded
    response and socket timeout. Socket timeout is not a total deadline.
    """
    def __init__(self, url, ca, cert, key, bundle, timeout=10):
        self._request = _freeze(bundle)
        self._used = False
        super().__init__(url, ca, cert, key, timeout)

    def validate_request(self, route, request):
        require(route == "push_tx" and type(request) is dict and set(request) == {"spend_bundle"}
                and _freeze(request["spend_bundle"]) == self._request, "Submission request differs")

    def call(self, route, request):
        # This check also covers callers using inherited call instead of push.
        self.validate_request(route, request)
        require(not self._used, "Submission transport already used")
        self._used = True  # A failed connection may still have delivered data.
        return _reply(super().call(route, json.loads(self._request)))

    def push(self):
        return self.call("push_tx", json.loads(self._request))

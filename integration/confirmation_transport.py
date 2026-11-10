"""Explicit mutual-TLS transport for TN-4 confirmation reads; no submission."""
from testnet_probe import Transport, hex32, require, uint


class ConfirmationTransport(Transport):
    """Adds two read routes without expanding the original TN-1 allowlist.

    Inherits explicit loopback endpoint and CA/client credentials, bounded
    responses, strict envelopes, per-socket timeouts and connection cleanup.
    """

    def validate_request(self, route, request):
        if route == "get_block_record_by_height":
            require(type(request) is dict and set(request) == {"height"}, "Invalid block request")
            uint(request["height"], 32)
        elif route == "get_puzzle_and_solution":
            require(type(request) is dict and set(request) == {"coin_id", "height"}, "Invalid spend request")
            hex32(request["coin_id"])
            uint(request["height"], 32)
        else:
            super().validate_request(route, request)

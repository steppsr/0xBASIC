"""Review a verified fee bundle offline, or explicitly dispatch that exact bundle once."""
import argparse
import json
from pathlib import Path
import sys

from owner_keys import no_network
from submission_dispatch import _dispatch
from verify_signed_fee import verify_signed


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for field in ("binary", "manifest", "observation", "solution", "preparation", "signature-response"):
        parser.add_argument("--" + field, required=True, type=Path)
    parser.add_argument("--max-fee", required=True, type=int)
    parser.add_argument("--max-observation-age", type=int, default=300)
    parser.add_argument("--review-only", action="store_true")
    parser.add_argument("--approve-bundle-id", dest="approved_bundle_id")
    parser.add_argument("--endpoint")
    for field in ("ca-cert", "client-cert", "client-key", "attempt"):
        parser.add_argument("--" + field, type=Path)
    parser.add_argument("--duration", type=float)
    parser.add_argument("--timeout", type=float)
    args = parser.parse_args()
    dispatch_options = (args.approved_bundle_id, args.endpoint, args.ca_cert, args.client_cert,
                        args.client_key, args.attempt, args.duration, args.timeout)
    if args.review_only:
        if any(value is not None for value in dispatch_options):
            parser.error("Review mode accepts no approval, TLS, attempt or dispatch timing arguments")
    elif any(value is None for value in dispatch_options):
        parser.error("Submission requires approve-bundle-id, endpoint, ca-cert, client-cert, client-key, attempt, duration and timeout")
    try:
        if args.review_only:
            sys.addaudithook(no_network)
            verified = verify_signed(args.binary, args.manifest, args.observation, args.solution, args.preparation,
                                     args.signature_response, args.max_fee, args.max_observation_age)
            print(json.dumps({"schema_version": 1, "validation": "offline-submission-review-only",
                "bundle_id": verified["bundle_id"], "bundle_sha256": verified["bundle_sha256"],
                "preparation_sha256": verified["preparation_sha256"], "signature_response_sha256": verified["signature_response_sha256"],
                "network": verified["network"], "preparation": verified["preparation"],
                "confirmation_established": False, "transactions_submitted": 0}, sort_keys=True, indent=2))
            return 0
        result = _dispatch(args)
        outcome = result["outcome"]
        if outcome not in {"reply-success", "reply-pending"}:
            raise RuntimeError("Unexpected submission outcome")
        print(f"SUBMISSION REPLY: {outcome}; confirmation is not established; inspect the attempt and monitor separately")
        return 0 if outcome == "reply-success" else 3
    except (Exception, KeyboardInterrupt):
        print("FAIL: review or submission did not complete; any attempt file may record an unknown outcome; do not automatically retry", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

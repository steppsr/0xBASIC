"""Dedicated rehearsal process for verified dispatch; never run in the live node process."""
import argparse
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from isolated_dispatch import dispatch_isolated, read_isolated_attempt
import submission_dispatch
from smoke import require


class LostReply(RuntimeError):
    pass


def run(args):
    work = args.work
    a = SimpleNamespace(binary=args.binary, manifest=args.manifest, observation=work / "observation.json",
        solution=work / "solution.json", preparation=work / "preparation.json", signature_response=work / "signature-response.json",
        attempt=work / "dispatch-attempt.json", max_fee=20, max_observation_age=300, duration=30, timeout=10,
        approved_bundle_id=args.bundle_id, endpoint=args.endpoint, ca_cert=args.ca, client_cert=args.cert, client_key=args.key)
    original = submission_dispatch._worker_for_identity
    calls = []
    def dispatch_once(*inputs):
        calls.append(1)
        reply = original(*inputs)
        if args.lose_reply:
            require(reply == "reply-success", "Fault injection needs successful node reply")
            raise LostReply("Rehearsal fault after worker reply, before outcome persistence")
        return reply
    with patch.object(submission_dispatch, "_worker_for_identity", side_effect=dispatch_once):
        try:
            saved = dispatch_isolated(a)
        except LostReply:
            require(args.lose_reply, "Unexpected reply loss")
            saved = read_isolated_attempt(a.attempt)
    require(len(calls) == 1 and saved["context"]["bundle_id"] == args.bundle_id, "Dispatch count or identity differs")
    require(saved["outcome"] == ("unknown" if args.lose_reply else "reply-success"), "Unexpected attempt outcome")
    return {"attempt": saved, "worker_calls": len(calls), "reply_loss_injected": args.lose_reply,
            "automatic_retry_performed": False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for field in ("binary", "manifest", "work", "ca", "cert", "key"):
        parser.add_argument("--" + field, required=True, type=Path)
    parser.add_argument("--endpoint", required=True)
    parser.add_argument("--bundle-id", required=True)
    parser.add_argument("--lose-reply", action="store_true")
    args = parser.parse_args()
    from full_node_smoke import contained
    args.work = contained(args.work)
    result = run(args)
    output = args.work / "dispatch-result.json"
    with output.open("x", encoding="utf-8") as handle:
        json.dump(result, handle, sort_keys=True, indent=2)
        handle.write("\n")


if __name__ == "__main__":
    main()

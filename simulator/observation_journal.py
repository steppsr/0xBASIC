"""Single-writer atomic observation history; never authorizes automatic recovery."""
import copy
import hashlib
import json
import os
from pathlib import Path
import tempfile

from smoke import require

STAGES = ("ready", "fees-confirmed", "depth-pending", "depth-confirmed", "reorged",
          "pending-timeout", "reconfirming", "reconfirmed", "rpc-closed")
MAX_BYTES = 8 * 1024 * 1024


def encoded(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def digest(value):
    return hashlib.sha256(encoded(value)).hexdigest()


def read_history(path):
    path = Path(path)
    require(not path.is_symlink(), "Journal symlink forbidden")
    with path.open("rb") as handle:
        data = handle.read(MAX_BYTES + 1)
    return decode_history(data)


def decode_history(data):
    require(len(data) <= MAX_BYTES, "Journal exceeds bound")
    def pairs(items):
        out = {}
        for key, value in items:
            require(key not in out, "Duplicate journal key")
            out[key] = value
        return out
    def invalid(_):
        raise ValueError("Invalid JSON number")
    doc = json.loads(data.decode("utf-8"), object_pairs_hook=pairs, parse_constant=invalid)
    require(type(doc) is dict and set(doc) == {"schema_version", "context", "records"}
            and type(doc["schema_version"]) is int and doc["schema_version"] == 1
            and type(doc["context"]) is dict and type(doc["records"]) is list, "Invalid journal schema")
    require(len(doc["records"]) <= len(STAGES), "Too many journal records")
    previous = digest(doc["context"])
    for index, record in enumerate(doc["records"]):
        require(type(record) is dict and set(record) == {"sequence", "stage", "observation", "previous", "sha256"}, "Invalid journal record")
        require(type(record["sequence"]) is int and record["sequence"] == index + 1
                and record["stage"] == STAGES[index] and type(record["observation"]) is dict
                and record["previous"] == previous, "Journal sequence/context mismatch")
        body = {k: v for k, v in record.items() if k != "sha256"}
        require(record["sha256"] == digest(body), "Journal digest mismatch")
        previous = record["sha256"]
    return {"validation": "historical-observations-only", "fresh_chain_validation_required": True,
            "automatic_resume_allowed": False, "journal_sha256": hashlib.sha256(data).hexdigest(), **doc}


class Journal:
    """Fresh run only. Existing histories can be read, never resumed by this class."""
    def __init__(self, path, context):
        self.path = Path(path)
        require(type(context) is dict and not self.path.exists() and not self.path.is_symlink(), "Journal must be a fresh file")
        self.doc = {"schema_version": 1, "context": copy.deepcopy(context), "records": []}
        self.last_bytes = None
        self._write(self.doc)

    def _write(self, doc):
        data = encoded(doc) + b"\n"
        require(len(data) <= MAX_BYTES and not self.path.is_symlink(), "Invalid journal destination/size")
        if self.last_bytes is not None:
            require(self.path.read_bytes() == self.last_bytes, "Journal changed outside writer")
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(dir=self.path.parent, delete=False) as handle:
                temporary = Path(handle.name)
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            temporary.replace(self.path)
            self.doc, self.last_bytes = copy.deepcopy(doc), data
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)

    def record(self, stage, observation):
        require(len(self.doc["records"]) < len(STAGES) and stage == STAGES[len(self.doc["records"])]
                and type(observation) is dict, "Unexpected observation stage")
        doc = copy.deepcopy(self.doc)
        previous = doc["records"][-1]["sha256"] if doc["records"] else digest(doc["context"])
        body = {"sequence": len(doc["records"]) + 1, "stage": stage,
                "observation": copy.deepcopy(observation), "previous": previous}
        doc["records"].append({**body, "sha256": digest(body)})
        self._write(doc)

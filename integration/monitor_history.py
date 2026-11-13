"""Single-writer monitor snapshots: historical evidence, never automatic resume authority."""
import copy
import hashlib
import json
import os
from pathlib import Path
import tempfile

from testnet_probe import require

MAX_BYTES = 8 * 1024 * 1024
MAX_RECORDS = 1001


def encoded(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def digest(value):
    return hashlib.sha256(encoded(value)).hexdigest()


def decode(data):
    require(len(data) <= MAX_BYTES, "History exceeds size bound")
    def pairs(items):
        result = {}
        for key, value in items:
            require(key not in result, "Duplicate history key")
            result[key] = value
        return result
    def invalid(_):
        raise ValueError("Non-finite history number")
    doc = json.loads(data.decode("utf-8"), object_pairs_hook=pairs, parse_constant=invalid)
    require(type(doc) is dict and set(doc) == {"schema_version", "context", "records"}
            and type(doc["schema_version"]) is int and doc["schema_version"] == 1
            and type(doc["context"]) is dict and type(doc["records"]) is list
            and len(doc["records"]) <= MAX_RECORDS, "Invalid history schema")
    previous = digest(doc["context"])
    finished = False
    for index, record in enumerate(doc["records"]):
        require(type(record) is dict and set(record) == {"sequence", "kind", "value", "previous", "sha256"}
                and type(record["sequence"]) is int and record["sequence"] == index + 1
                and record["kind"] in {"observation", "finished"} and type(record["value"]) is dict
                and not finished and record["previous"] == previous, "Invalid history order")
        body = {key: value for key, value in record.items() if key != "sha256"}
        require(record["sha256"] == digest(body), "History hash mismatch")
        previous = record["sha256"]
        finished = record["kind"] == "finished"
    return {**doc, "validation": "historical-monitor-observations-only", "history_sha256": hashlib.sha256(data).hexdigest(),
            "fresh_chain_validation_required": True, "automatic_resume_allowed": False}


def read_history(path):
    path = Path(path)
    require(not path.is_symlink(), "History symlink forbidden")
    with path.open("rb") as handle:
        return decode(handle.read(MAX_BYTES + 1))


class History:
    def __init__(self, path, context):
        self.path = Path(path)
        require(type(context) is dict, "Invalid history context")
        self.doc = {"schema_version": 1, "context": copy.deepcopy(context), "records": []}
        self.last = encoded(self.doc) + b"\n"
        require(len(self.last) <= MAX_BYTES and not self.path.is_symlink(), "Invalid history destination/size")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # Exclusive creation refuses existing files and symlinks, even at a race.
        # Failure can leave an incomplete new file; it is never reused or deleted.
        with self.path.open("xb") as handle:
            handle.write(self.last)
            handle.flush()
            os.fsync(handle.fileno())

    def record(self, kind, value):
        require(kind in {"observation", "finished"} and type(value) is dict
                and len(self.doc["records"]) < MAX_RECORDS
                and (not self.doc["records"] or self.doc["records"][-1]["kind"] != "finished"), "Invalid history append")
        require(not self.path.is_symlink(), "History symlink forbidden")
        with self.path.open("rb") as handle:
            require(handle.read(MAX_BYTES + 1) == self.last, "History changed outside writer")
        doc = copy.deepcopy(self.doc)
        previous = doc["records"][-1]["sha256"] if doc["records"] else digest(doc["context"])
        body = {"sequence": len(doc["records"]) + 1, "kind": kind, "value": copy.deepcopy(value), "previous": previous}
        doc["records"].append({**body, "sha256": digest(body)})
        data = encoded(doc) + b"\n"
        require(len(data) <= MAX_BYTES, "History exceeds size bound")
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(dir=self.path.parent, delete=False) as handle:
                temporary = Path(handle.name)
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            temporary.replace(self.path)
            self.doc, self.last = doc, data
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)

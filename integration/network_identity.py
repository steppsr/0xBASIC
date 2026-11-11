"""Reviewed fixed identities; never selected by RPC responses or input documents."""
from dataclasses import dataclass


@dataclass(frozen=True)
class Identity:
    version: str
    name: str
    prefix: str
    genesis: str

    def network(self):
        return {"name": self.name, "prefix": self.prefix, "genesis_challenge": self.genesis}


PUBLIC_TESTNET = Identity("2.7.5", "testnet11", "txch", "37a90eb5185a9c4439a91ddc98bbadce7b4feba060d50116a067de66bf236615")
ISOLATED_REHEARSAL = Identity("2.7.4", "0xbasic-simulator", "txch", "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855")


def validate(identity):
    if identity is not PUBLIC_TESTNET and identity is not ISOLATED_REHEARSAL:
        raise ValueError("Unreviewed identity object")

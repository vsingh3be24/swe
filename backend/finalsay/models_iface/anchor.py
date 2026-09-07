"""Anchor interface (module 3, design.md section 6).

``Anchor.anchor(root_hash) -> AnchorRef`` anchors a daily Merkle root.

- ``LocalHashChainAnchor`` (default): appends an ``anchor_block`` row with
  ``prev_hash`` chaining. Always available and never blocks (GC-3).
- ``PolygonAmoyAnchor`` (opt-in): sends the root to a Polygon Amoy testnet
  contract via web3.py when ``FINALSAY_ANCHOR=polygon`` and creds are set. Any
  failure is caught and downgraded to local so ingestion never blocks (GC-3/R3.5).

web3 is imported lazily inside PolygonAmoyAnchor so the default demo path never
requires it.
"""

from __future__ import annotations

import hashlib
from abc import ABC, abstractmethod
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from finalsay.config import get_settings
from finalsay.models import AnchorBlock


@dataclass
class AnchorRef:
    """Reference to where a root was anchored.

    ``kind`` is 'local' or 'polygon'; ``ref`` is the local block hash (or index)
    or the on-chain transaction hash.
    """

    kind: str
    ref: str


class Anchor(ABC):
    """Interface for anchoring a Merkle root."""

    kind: str = "abstract"

    @abstractmethod
    def anchor(self, root_hash: str) -> AnchorRef:
        """Anchor ``root_hash`` and return a reference to the anchoring record."""
        raise NotImplementedError


class LocalHashChainAnchor(Anchor):
    """Append-only local hash chain over ``anchor_block`` rows.

    Each block's ``this_hash`` = sha256(index || prev_hash || data_hash),
    forming a tamper-evident chain. Always available; never raises.
    """

    kind = "local"

    def __init__(self, db: Session):
        self._db = db

    def anchor(self, root_hash: str) -> AnchorRef:
        last = self._db.scalar(
            select(AnchorBlock).order_by(AnchorBlock.index.desc()).limit(1)
        )
        index = (last.index + 1) if last is not None else 0
        prev_hash = last.this_hash if last is not None else None
        this_hash = self._compute_hash(index, prev_hash, root_hash)
        block = AnchorBlock(
            index=index,
            prev_hash=prev_hash,
            data_hash=root_hash,
            this_hash=this_hash,
        )
        self._db.add(block)
        self._db.flush()
        return AnchorRef(kind=self.kind, ref=this_hash)

    @staticmethod
    def _compute_hash(index: int, prev_hash: str | None, data_hash: str) -> str:
        payload = f"{index}|{prev_hash or ''}|{data_hash}".encode()
        return hashlib.sha256(payload).hexdigest()


class PolygonAmoyAnchor(Anchor):
    """On-chain anchoring via Polygon Amoy testnet (opt-in).

    Falls back to LocalHashChainAnchor on any failure (missing creds, network,
    web3 import error) so ingestion never blocks (GC-3).
    """

    kind = "polygon"

    def __init__(self, db: Session):
        self._db = db
        self._fallback = LocalHashChainAnchor(db)

    def anchor(self, root_hash: str) -> AnchorRef:
        try:
            return self._anchor_onchain(root_hash)
        except Exception:  # noqa: BLE001 - never block ingestion (GC-3)
            return self._fallback.anchor(root_hash)

    def _anchor_onchain(self, root_hash: str) -> AnchorRef:
        settings = get_settings()
        if not (
            settings.polygon_rpc_url
            and settings.polygon_private_key
            and settings.polygon_contract
        ):
            raise RuntimeError("Polygon credentials not configured")

        # Lazy import: web3 must not be required for the default (local) path.
        from web3 import Web3

        w3 = Web3(Web3.HTTPProvider(settings.polygon_rpc_url))
        account = w3.eth.account.from_key(settings.polygon_private_key)
        tx = {
            "from": account.address,
            "to": Web3.to_checksum_address(settings.polygon_contract),
            "value": 0,
            "nonce": w3.eth.get_transaction_count(account.address),
            "gas": 100_000,
            "gasPrice": w3.eth.gas_price,
            "data": ("0x" + root_hash),
        }
        signed = account.sign_transaction(tx)
        tx_hash = w3.eth.send_raw_transaction(signed.rawTransaction)
        return AnchorRef(kind=self.kind, ref=tx_hash.hex())


def get_anchor(db: Session) -> Anchor:
    """Return the configured Anchor. Defaults to local; polygon is opt-in."""
    settings = get_settings()
    if settings.anchor == "polygon":
        return PolygonAmoyAnchor(db)
    return LocalHashChainAnchor(db)

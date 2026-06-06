"""
Offline-fixture helpers — run the WCL-backed features with no creds, no network.

Two pieces make the pipeline fully replayable in a sandbox:
  - ensure_item_db():   decompress the committed item-DB fixture to a cache file
                        and point config.ITEM_DB_PATH at it, so gear/socket logic
                        (e.g. the audit's empty-socket check) runs offline.
  - FIXTURE_WCL_DIR:    where captured/synthetic WCL responses live. Set
                        WCL_FIXTURE_DIR to it and core.wcl_client replays canned
                        JSON instead of calling the API (see wcl_client._fixture).
"""

from __future__ import annotations

import gzip
import os
import shutil
import tempfile

import config

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ITEM_DB_GZ = os.path.join(_ROOT, "tests", "fixtures", "items", "tbc_items.db.gz")
FIXTURE_WCL_DIR = os.path.join(_ROOT, "tests", "fixtures", "wcl")


def ensure_item_db(point_config: bool = True) -> str | None:
    """
    Materialise the committed item-DB fixture to a cache file and (by default)
    point config.ITEM_DB_PATH at it. Idempotent; rebuilds if the fixture is newer.
    Returns the cache path, or None if the fixture is missing.
    """
    if not os.path.exists(ITEM_DB_GZ):
        return None
    cache = os.path.join(tempfile.gettempdir(), "brnzybot_fixture_items.db")
    if (not os.path.exists(cache)
            or os.path.getmtime(cache) < os.path.getmtime(ITEM_DB_GZ)):
        with gzip.open(ITEM_DB_GZ, "rb") as fin, open(cache, "wb") as fout:
            shutil.copyfileobj(fin, fout)
    if point_config:
        config.ITEM_DB_PATH = cache
    return cache


def use_wcl_fixtures(path: str = FIXTURE_WCL_DIR) -> None:
    """Point core.wcl_client at a fixture directory for this process."""
    os.environ["WCL_FIXTURE_DIR"] = path

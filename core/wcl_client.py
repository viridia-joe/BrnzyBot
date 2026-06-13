"""
OpenClaw Raid Analyst — Warcraft Logs API client.

Handles OAuth2 client credentials flow and all GraphQL queries.
Uses stdlib urllib only — no pip packages required.

Hardening (Phase 6):
  - Token persisted to DATA_DIR/wcl_token.json — survives cron restarts
  - Rate limiter enforces minimum gap between WCL requests to avoid 429s
    WCL v2 is points-based; we stay safe with a 0.5s floor between calls.
"""

import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

sys.path.insert(0, os.path.dirname(__file__))
import config

WCL_TOKEN_URL   = "https://www.warcraftlogs.com/oauth/token"
# OAuth tokens are issued by the retail site but are valid for Classic too.
# Classic guild/report data lives at the Classic API endpoint.
WCL_GRAPHQL_URL = "https://classic.warcraftlogs.com/api/v2/client"

_TOKEN_FILE = os.path.join(config.DATA_DIR, "wcl_token.json")

# ---------------------------------------------------------------------------
# Offline fixture transport. When WCL_FIXTURE_DIR is set, the get_* functions
# read canned JSON instead of hitting the API — so the whole pipeline (audit,
# rotationcheck) runs with no creds and no network. tools/capture_wcl.py writes
# these files; the naming below is the contract between capture and replay.
# Zero effect in production (the env var is unset there).
# ---------------------------------------------------------------------------
def _fixture_dir() -> str | None:
    """Replay dir from the env (read live so tests/CLI can toggle it any time)."""
    return os.environ.get("WCL_FIXTURE_DIR") or None


def _fixture(name: str, default=None):
    """Load tests-fixture JSON `<WCL_FIXTURE_DIR>/<name>.json`, or `default`."""
    try:
        with open(os.path.join(_fixture_dir(), f"{name}.json"), encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return default

# ---------------------------------------------------------------------------
# Rate limiter — minimum seconds between WCL GraphQL requests.
# WCL v2 is point-based; staying at ≥0.5s/req puts us well under the limit
# even on the largest reports (Kara ~20 calls).
# ---------------------------------------------------------------------------
_MIN_REQUEST_GAP = 0.5   # seconds
_last_request_at: float = 0.0


def _throttle() -> None:
    global _last_request_at
    elapsed = time.time() - _last_request_at
    if elapsed < _MIN_REQUEST_GAP:
        time.sleep(_MIN_REQUEST_GAP - elapsed)
    _last_request_at = time.time()


# ---------------------------------------------------------------------------
# Circuit breaker — trips after 3 consecutive failures, resets after 60s
# ---------------------------------------------------------------------------
_CB_THRESHOLD  = 3
_CB_RESET_SECS = 60

_cb_failures:    int   = 0
_cb_tripped_at:  float = 0.0


def _cb_check() -> None:
    global _cb_failures, _cb_tripped_at
    if _cb_failures >= _CB_THRESHOLD:
        if time.time() - _cb_tripped_at < _CB_RESET_SECS:
            raise RuntimeError(
                "WCL circuit breaker open — too many recent failures. "
                f"Retrying in {int(_CB_RESET_SECS - (time.time() - _cb_tripped_at))}s."
            )
        _cb_failures = 0  # half-open: allow one attempt


def _cb_success() -> None:
    global _cb_failures
    _cb_failures = 0


def _cb_failure() -> None:
    global _cb_failures, _cb_tripped_at
    _cb_failures += 1
    if _cb_failures >= _CB_THRESHOLD:
        _cb_tripped_at = time.time()


# ---------------------------------------------------------------------------
# Token management — persisted to disk so cron restarts don't re-auth
# ---------------------------------------------------------------------------
def _load_token_from_disk() -> dict:
    """Return cached token dict from disk, or {} if missing/expired."""
    try:
        with open(_TOKEN_FILE) as f:
            data = json.load(f)
        if data.get("token") and time.time() < data.get("expires_at", 0):
            return data
    except (FileNotFoundError, json.JSONDecodeError, KeyError):
        pass
    return {}


def _save_token_to_disk(token: str, expires_at: float) -> None:
    os.makedirs(config.DATA_DIR, exist_ok=True)
    with open(_TOKEN_FILE, "w") as f:
        json.dump({"token": token, "expires_at": expires_at}, f)


def _get_token() -> str:
    """Return a valid OAuth2 access token, refreshing if needed."""
    cached = _load_token_from_disk()
    if cached.get("token"):
        return cached["token"]

    if not config.WCL_CLIENT_ID or not config.WCL_CLIENT_SECRET:
        raise RuntimeError("WCL_CLIENT_ID and WCL_CLIENT_SECRET must be set in environment")

    payload = urllib.parse.urlencode({
        "grant_type":    "client_credentials",
        "client_id":     config.WCL_CLIENT_ID,
        "client_secret": config.WCL_CLIENT_SECRET,
    }).encode()

    req = urllib.request.Request(
        WCL_TOKEN_URL,
        data=payload,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read())
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="replace")
        raise RuntimeError(f"WCL OAuth HTTP {e.code}: {body[:200]}") from e

    token      = data["access_token"]
    expires_at = time.time() + data.get("expires_in", 3600) - 120  # 2-min safety margin
    _save_token_to_disk(token, expires_at)
    return token


# ---------------------------------------------------------------------------
# Core GraphQL executor — with retry + circuit breaker
# ---------------------------------------------------------------------------
_RETRY_ATTEMPTS = 3
_RETRY_BACKOFF  = (1.0, 3.0, 9.0)   # seconds between attempts


def graphql(query: str, variables: dict = None) -> dict:
    """Execute a WCL GraphQL query with retry and circuit breaker."""
    _cb_check()

    last_exc: Exception = RuntimeError("No attempt made")

    for attempt, backoff in enumerate((*_RETRY_BACKOFF, None), start=1):
        _throttle()
        try:
            token = _get_token()
        except RuntimeError:
            _cb_failure()
            raise

        body = json.dumps({"query": query, "variables": variables or {}}).encode()
        req  = urllib.request.Request(
            WCL_GRAPHQL_URL,
            data=body,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type":  "application/json",
            },
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                result = json.loads(resp.read())
        except urllib.error.HTTPError as e:
            body_text = e.read().decode(errors="replace")
            if e.code == 401:
                try:
                    os.remove(_TOKEN_FILE)
                except FileNotFoundError:
                    pass
                last_exc = RuntimeError(f"WCL auth failure: {body_text[:200]}")
                _cb_failure()
                break  # no point retrying a bad token
            if e.code == 429 or e.code >= 500:
                last_exc = RuntimeError(f"WCL HTTP {e.code}: {body_text[:200]}")
                if backoff is not None:
                    time.sleep(backoff)
                continue
            _cb_failure()
            raise RuntimeError(f"WCL GraphQL HTTP {e.code}: {body_text[:300]}") from e
        except (urllib.error.URLError, OSError) as e:
            last_exc = RuntimeError(f"WCL network error: {e}")
            if backoff is not None:
                time.sleep(backoff)
            continue

        if "errors" in result:
            err_msg = str(result["errors"])[:300]
            last_exc = RuntimeError(f"WCL GraphQL errors: {err_msg}")
            if backoff is not None:
                time.sleep(backoff)
            continue

        _cb_success()
        return result["data"]

    _cb_failure()
    raise last_exc


# NOTE: a former get_recent_reports() (guild-wide report discovery) was removed —
# it referenced config.GUILD_NAME/SERVER_SLUG/REGION, which don't exist (only
# DEFAULT_REALM/DEFAULT_REGION do), so it would have crashed if called. Per-guild
# report discovery goes through get_character_recent_reports(name, realm, region).


# ---------------------------------------------------------------------------
# Query: fight list + outcomes (§5.2)
# ---------------------------------------------------------------------------
_FIGHTS_QUERY = """
query ReportFights($code: String!) {
  reportData {
    report(code: $code) {
      startTime
      zone { name }
      fights(killType: All) {
        id
        name
        kill
        encounterID
        difficulty
        hardModeLevel
        startTime
        endTime
        friendlyPlayers
      }
    }
  }
}
"""


def get_fights(report_code: str) -> list[dict]:
    """Returns the fight list for a report."""
    if _fixture_dir():
        return _fixture(f"{report_code}.fights", [])
    data = graphql(_FIGHTS_QUERY, {"code": report_code})
    return (
        data.get("reportData", {})
            .get("report", {})
            .get("fights", [])
    )


def get_report_meta(report_code: str) -> dict:
    """Report-level metadata: {start_time (epoch ms), zone, fights}. One call."""
    if _fixture_dir():
        return {"start_time": None, "zone": "",
                "fights": _fixture(f"{report_code}.fights", [])}
    data = graphql(_FIGHTS_QUERY, {"code": report_code})
    report = (data.get("reportData", {}) or {}).get("report", {}) or {}
    return {
        "start_time": report.get("startTime"),
        "zone": (report.get("zone") or {}).get("name", ""),
        "fights": report.get("fights", []),
    }


# ---------------------------------------------------------------------------
# Query: masterData actors — sourceID → name/class (fetch once per report)
# ---------------------------------------------------------------------------
_MASTER_ACTORS_QUERY = """
query MasterActors($code: String!) {
  reportData {
    report(code: $code) {
      masterData {
        actors(type: "Player") {
          id
          name
          subType
        }
      }
    }
  }
}
"""


def get_master_actors(report_code: str) -> list[dict]:
    """Returns player actors for the report: [{id, name, subType (class)}]."""
    if _fixture_dir():
        return _fixture(f"{report_code}.actors", [])
    data = graphql(_MASTER_ACTORS_QUERY, {"code": report_code})
    return (
        data.get("reportData", {})
            .get("report", {})
            .get("masterData", {})
            .get("actors", [])
    )


# ---------------------------------------------------------------------------
# Query: parse rankings per fight (§5.3)
# ---------------------------------------------------------------------------
_RANKINGS_QUERY = """
query FightRankings($code: String!, $fightIDs: [Int]!) {
  reportData {
    report(code: $code) {
      rankings(fightIDs: $fightIDs)
    }
  }
}
"""


def get_rankings(report_code: str, fight_ids: list[int]) -> dict:
    """Returns raw rankings data for the specified fight IDs."""
    data = graphql(_RANKINGS_QUERY, {"code": report_code, "fightIDs": fight_ids})
    return (
        data.get("reportData", {})
            .get("report", {})
            .get("rankings", {})
    )


# ---------------------------------------------------------------------------
# Query: death events (§5.4)
# ---------------------------------------------------------------------------
_DEATHS_QUERY = """
query DeathEvents($code: String!, $fightID: Int!) {
  reportData {
    report(code: $code) {
      events(fightIDs: [$fightID], dataType: Deaths, limit: 200) {
        data
        nextPageTimestamp
      }
    }
  }
}
"""

_WINDOW_QUERY = """
query PreDeathWindow($code: String!, $fightID: Int!, $startTime: Float!, $endTime: Float!) {
  reportData {
    report(code: $code) {
      events(fightIDs: [$fightID], startTime: $startTime, endTime: $endTime, limit: 100) {
        data
      }
    }
  }
}
"""


def get_deaths(report_code: str, fight_id: int) -> list[dict]:
    """Returns death events for a fight."""
    data = graphql(_DEATHS_QUERY, {"code": report_code, "fightID": fight_id})
    return (
        data.get("reportData", {})
            .get("report", {})
            .get("events", {})
            .get("data", [])
    )


def get_pre_death_window(
    report_code: str, fight_id: int, death_timestamp: float
) -> list[dict]:
    """
    Returns events in the 10-second window before a death.
    death_timestamp is milliseconds since report start (WCL convention).
    """
    data = graphql(_WINDOW_QUERY, {
        "code":      report_code,
        "fightID":   fight_id,
        "startTime": death_timestamp - 10_000,
        "endTime":   death_timestamp,
    })
    return (
        data.get("reportData", {})
            .get("report", {})
            .get("events", {})
            .get("data", [])
    )


# ---------------------------------------------------------------------------
# Query: combatant info — gear + consumables + talents (§5.5)
# ---------------------------------------------------------------------------
_COMBATANT_QUERY = """
query CombatantInfo($code: String!, $fightIDs: [Int], $sourceID: Int) {
  reportData {
    report(code: $code) {
      events(fightIDs: $fightIDs, sourceID: $sourceID, dataType: CombatantInfo,
             startTime: 0, endTime: 999999999999) {
        data
      }
    }
  }
}
"""


def get_combatant_info(report_code: str, fight_id: int | None = None,
                       source_id: int | None = None) -> list[dict]:
    """
    CombatantInfo records (gear[], auras[], talents[], specID, race…).
    Pass `fight_id` for one fight's combatants (audit), or `source_id` to pull a
    single actor's CombatantInfo across the whole report (gear lookup). Both may
    be combined; either may be omitted.
    """
    if _fixture_dir():
        if fight_id is not None:
            rows = _fixture(f"{report_code}.combatant.{fight_id}", [])
        else:
            rows = _fixture(f"{report_code}.combatant.src.{source_id}", None)
            if rows is None:
                rows = _fixture(f"{report_code}.combatant", [])
        return [r for r in rows if source_id is None or r.get("sourceID") == source_id]
    data = graphql(_COMBATANT_QUERY, {
        "code": report_code,
        "fightIDs": [fight_id] if fight_id is not None else None,
        "sourceID": source_id,
    })
    return (
        data.get("reportData", {})
            .get("report", {})
            .get("events", {})
            .get("data", [])
    )


# ---------------------------------------------------------------------------
# Query: a character's most recent reports (for /rotationcheck auto-log)
# ---------------------------------------------------------------------------
_CHAR_REPORTS_QUERY = """
query CharReports($name: String!, $serverSlug: String!, $region: String!, $limit: Int!) {
  characterData {
    character(name: $name, serverSlug: $serverSlug, serverRegion: $region) {
      classID
      recentReports(limit: $limit) {
        data { code startTime }
      }
    }
  }
}
"""


_CHARACTER_QUERY = """
query Character($name: String!, $serverSlug: String!, $region: String!) {
  characterData {
    character(name: $name, serverSlug: $serverSlug, serverRegion: $region) {
      classID
      name
      recentReports(limit: 1) { data { code startTime } }
    }
  }
}
"""


def get_character(name: str, realm: str, region: str = "us") -> dict | None:
    """
    Returns {classID, name, reports:[{code, startTime}]} for a character, or None
    if WCL has no record. Used by gear fetch + auto-register spec detection.
    """
    if _fixture_dir():
        return _fixture(f"character.{name.lower()}", None)
    data = graphql(_CHARACTER_QUERY, {"name": name, "serverSlug": realm, "region": region})
    char = (data.get("characterData") or {}).get("character")
    if not char:
        return None
    return {
        "classID": char.get("classID"),
        "name": char.get("name") or name,
        "reports": (char.get("recentReports") or {}).get("data", []),
    }


def get_character_recent_reports(
    name: str, realm: str, region: str = "us", limit: int = 5
) -> list[dict]:
    """Returns the character's most recent reports: [{code, startTime}]. [] if none."""
    if _fixture_dir():
        return _fixture(f"recent_reports.{name.lower()}", None) or _fixture("recent_reports", [])
    data = graphql(_CHAR_REPORTS_QUERY, {
        "name": name, "serverSlug": realm, "region": region, "limit": limit,
    })
    char = (data.get("characterData") or {}).get("character") or {}
    return (char.get("recentReports") or {}).get("data", [])


# ---------------------------------------------------------------------------
# Query: masterData abilities — gameID → name (resolves cast spell + rank)
# ---------------------------------------------------------------------------
_ABILITIES_QUERY = """
query Abilities($code: String!) {
  reportData {
    report(code: $code) {
      masterData {
        abilities { gameID name type }
      }
    }
  }
}
"""


def get_abilities(report_code: str) -> list[dict]:
    """Returns ability records for the report: [{gameID, name, type}]."""
    if _fixture_dir():
        return _fixture(f"{report_code}.abilities", [])
    data = graphql(_ABILITIES_QUERY, {"code": report_code})
    return (
        data.get("reportData", {})
            .get("report", {})
            .get("masterData", {})
            or {}
    ).get("abilities", [])


# ---------------------------------------------------------------------------
# Query: cast events for a single actor (for /rotationcheck)
# ---------------------------------------------------------------------------
_CASTS_QUERY = """
query Casts($code: String!, $fightID: Int!, $sourceID: Int, $startTime: Float, $limit: Int!) {
  reportData {
    report(code: $code) {
      events(fightIDs: [$fightID], dataType: Casts, sourceID: $sourceID, startTime: $startTime, limit: $limit) {
        data
        nextPageTimestamp
      }
    }
  }
}
"""


def get_casts(
    report_code: str, fight_id: int, source_id: int | None = None,
    max_events: int = 20_000, page_limit: int = 10_000,
) -> list[dict]:
    """
    Returns cast events for a fight, optionally filtered to one actor (source_id).
    Each record has at least: timestamp, type ('cast'/'begincast'), sourceID,
    abilityGameID. Paginates via nextPageTimestamp up to max_events.
    """
    if _fixture_dir():
        rows = _fixture(f"{report_code}.casts.{fight_id}", [])
        return [e for e in rows if source_id is None or e.get("sourceID") == source_id]
    out: list[dict] = []
    start: float | None = None
    for _ in range(10):  # hard page cap as a safety net
        ev = (
            graphql(_CASTS_QUERY, {
                "code": report_code, "fightID": fight_id, "sourceID": source_id,
                "startTime": start, "limit": page_limit,
            })
            .get("reportData", {}).get("report", {})
            .get("events", {}) or {}
        )
        out.extend(ev.get("data", []))
        nxt = ev.get("nextPageTimestamp")
        if not nxt or len(out) >= max_events:
            break
        start = nxt
    return out


# ---------------------------------------------------------------------------
# Query: zone encounter list (for baseline builder --discover)
# ---------------------------------------------------------------------------
_ZONE_ENCOUNTERS_QUERY = """
query ZoneEncounters($zoneID: Int!) {
  worldData {
    zone(id: $zoneID) {
      name
      encounters {
        id
        name
      }
    }
  }
}
"""


def get_zone_encounters(zone_id: int) -> list[dict]:
    """Return [{id, name}] for all encounters in a WCL zone. [] on failure."""
    data = graphql(_ZONE_ENCOUNTERS_QUERY, {"zoneID": zone_id})
    zone = (data.get("worldData") or {}).get("zone") or {}
    return zone.get("encounters") or []


# ---------------------------------------------------------------------------
# Query: global encounter rankings by spec (for baseline builder)
# ---------------------------------------------------------------------------
_ENCOUNTER_RANKINGS_QUERY = """
query EncounterRankings($encounterID: Int!, $className: String!, $specName: String!, $page: Int!) {
  worldData {
    encounter(id: $encounterID) {
      name
      characterRankings(
        className: $className
        specName: $specName
        page: $page
        includeCombatantInfo: false
      )
    }
  }
}
"""


def get_encounter_rankings(
    encounter_id: int,
    class_name: str,
    spec_name: str,
    page: int = 1,
) -> dict:
    """
    Fetch one page of global characterRankings for a boss+spec combination.

    Returns the raw rankings object:
      {page, hasMorePages, count, rankings: [{name, duration, report: {code, fightID}, ...}]}
    Returns {} on failure.
    """
    data = graphql(_ENCOUNTER_RANKINGS_QUERY, {
        "encounterID": encounter_id,
        "className": class_name,
        "specName": spec_name,
        "page": page,
    })
    enc = ((data.get("worldData") or {}).get("encounter") or {})
    raw = enc.get("characterRankings")
    # characterRankings returns JSON blob (not a typed object) — parse if string
    if isinstance(raw, str):
        import json as _json
        try:
            raw = _json.loads(raw)
        except Exception:
            return {}
    return raw or {}

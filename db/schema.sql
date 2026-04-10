-- BrnzyBot database schema
-- Stores per-server config and character registry.
-- Separate from tbc_items.db and gear_cache.db (those stay in ~/.openclaw/data/).

CREATE TABLE IF NOT EXISTS server_config (
    guild_id        TEXT NOT NULL,
    channel_id      TEXT NOT NULL,
    -- Verbosity modes: silent | commands_only | speak_when_spoken_to | chatty
    verbosity       TEXT NOT NULL DEFAULT 'speak_when_spoken_to',
    -- Where to post gear results: 'channel' | 'ephemeral' | 'dm'
    response_target TEXT NOT NULL DEFAULT 'channel',
    -- Canonical #raid-recap channel for raid analyst output (Phase 5)
    recap_channel_id TEXT,
    PRIMARY KEY (guild_id, channel_id)
);

CREATE TABLE IF NOT EXISTS guild_config (
    guild_id        TEXT PRIMARY KEY,
    guild_name      TEXT,
    server_slug     TEXT,   -- WCL/WoW realm slug
    region          TEXT NOT NULL DEFAULT 'us',
    -- Interest threshold for raid analyst (Phase 5)
    interest_threshold INTEGER NOT NULL DEFAULT 5,
    setup_at        TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS characters (
    guild_id        TEXT NOT NULL,
    name_lower      TEXT NOT NULL,   -- lowercase lookup key
    display_name    TEXT NOT NULL,   -- original casing for display
    spec            TEXT NOT NULL,   -- e.g. "destro_warlock"
    realm           TEXT NOT NULL,
    region          TEXT NOT NULL DEFAULT 'us',
    added_by        TEXT,            -- Discord user ID who registered them
    added_at        TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (guild_id, name_lower)
);

CREATE TABLE IF NOT EXISTS pending_intents (
    -- Stores intents awaiting user clarification (e.g. "did you mean affliction?")
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id        TEXT NOT NULL,
    channel_id      TEXT NOT NULL,
    user_id         TEXT NOT NULL,
    intent_json     TEXT NOT NULL,   -- serialized Intent dataclass
    prompt          TEXT NOT NULL,   -- the clarifying question that was asked
    expires_at      TEXT NOT NULL,   -- ISO8601; stale entries are ignored
    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

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
    current_phase   INTEGER NOT NULL DEFAULT 1,
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

CREATE TABLE IF NOT EXISTS usage_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id    TEXT NOT NULL,
    user_id     TEXT NOT NULL,
    command     TEXT NOT NULL,  -- 'gearprio', 'gearcheck', 'nl_gear', 'nl_general'
    logged_at   TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_usage_log_guild_day
    ON usage_log (guild_id, logged_at);

CREATE TABLE IF NOT EXISTS subscriptions (
    guild_id            TEXT PRIMARY KEY,
    stripe_customer_id  TEXT,
    stripe_sub_id       TEXT,
    plan                TEXT NOT NULL DEFAULT 'free',   -- 'free', 'pro'
    status              TEXT NOT NULL DEFAULT 'active', -- 'active', 'past_due', 'canceled'
    updated_at          TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS user_weights (
    guild_id        TEXT NOT NULL,
    user_id         TEXT NOT NULL,
    spec            TEXT NOT NULL,
    weights_json    TEXT NOT NULL,  -- JSON object mapping stat -> float
    updated_at      TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (guild_id, user_id, spec)
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

-- ---------------------------------------------------------------------------
-- BotDuel — Crashin' Thrashin' Robot betting system
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS duels (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id     TEXT    NOT NULL,
    challenger   TEXT    NOT NULL,   -- Discord user ID
    opponent     TEXT    NOT NULL,   -- Discord user ID
    gold_stake   INTEGER NOT NULL DEFAULT 0,
    -- pending | active | pending_confirm | completed | declined | expired | disputed
    status       TEXT    NOT NULL DEFAULT 'pending',
    winner       TEXT,               -- Discord user ID; NULL until resolved
    reported_by  TEXT,               -- user ID who called /botduel result
    confirmed_by TEXT,               -- user ID who confirmed (or admin who resolved)
    message_id   TEXT,               -- Discord message ID of the challenge post
    channel_id   TEXT,               -- channel the challenge was posted in
    created_at   INTEGER NOT NULL,   -- Unix timestamp
    expires_at   INTEGER NOT NULL,   -- challenge expiry (Unix timestamp)
    resolved_at  INTEGER             -- when completed/declined/expired (Unix)
);

CREATE INDEX IF NOT EXISTS idx_duels_guild_status ON duels (guild_id, status);
CREATE INDEX IF NOT EXISTS idx_duels_participants ON duels (guild_id, challenger, opponent);

CREATE TABLE IF NOT EXISTS gold_ledger (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id   TEXT    NOT NULL,
    user_id    TEXT    NOT NULL,   -- Discord user ID
    delta      INTEGER NOT NULL,   -- positive = gained, negative = lost
    reason     TEXT    NOT NULL,   -- 'duel_win' | 'duel_loss' | 'admin_adjust: <text>'
    duel_id    INTEGER,            -- FK -> duels.id; NULL for admin adjustments
    created_at INTEGER NOT NULL    -- Unix timestamp
);

CREATE INDEX IF NOT EXISTS idx_gold_ledger_user ON gold_ledger (guild_id, user_id);

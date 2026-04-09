-- Run this in Supabase SQL Editor

CREATE TABLE IF NOT EXISTS users (
    id BIGSERIAL PRIMARY KEY,
    telegram_id BIGINT UNIQUE NOT NULL,
    username TEXT DEFAULT '',
    first_name TEXT DEFAULT '',
    phone TEXT,
    coins INTEGER DEFAULT 0,
    streak INTEGER DEFAULT 0,
    last_daily TIMESTAMPTZ,
    last_spin TIMESTAMPTZ,
    referral_code TEXT UNIQUE,
    referred_by BIGINT,
    level INTEGER DEFAULT 1,
    xp INTEGER DEFAULT 0,
    total_earned INTEGER DEFAULT 0,
    banned BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS transactions (
    id BIGSERIAL PRIMARY KEY,
    telegram_id BIGINT NOT NULL,
    amount INTEGER NOT NULL,
    type TEXT DEFAULT '',
    reason TEXT DEFAULT '',
    details TEXT DEFAULT '',
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS userbot_sessions (
    id BIGSERIAL PRIMARY KEY,
    telegram_id BIGINT,
    session_string TEXT NOT NULL,
    phone TEXT,
    active BOOLEAN DEFAULT FALSE,
    logged_in_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS bot_settings (
    id BIGSERIAL PRIMARY KEY,
    key TEXT UNIQUE NOT NULL,
    value TEXT DEFAULT '',
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS groups (
    id BIGSERIAL PRIMARY KEY,
    link TEXT NOT NULL,
    status TEXT DEFAULT 'pending',
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_users_telegram_id ON users(telegram_id);
CREATE INDEX IF NOT EXISTS idx_users_referral_code ON users(referral_code);
CREATE INDEX IF NOT EXISTS idx_users_coins ON users(coins DESC);
CREATE INDEX IF NOT EXISTS idx_transactions_telegram_id ON transactions(telegram_id);

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
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS transactions (
    id BIGSERIAL PRIMARY KEY,
    telegram_id BIGINT NOT NULL,
    amount INTEGER NOT NULL,
    reason TEXT DEFAULT '',
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_users_telegram_id ON users(telegram_id);
CREATE INDEX idx_users_referral_code ON users(referral_code);
CREATE INDEX idx_users_coins ON users(coins DESC);
CREATE INDEX idx_transactions_telegram_id ON transactions(telegram_id);

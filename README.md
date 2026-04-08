# CoinBot - Telegram Coin Earning Bot

Feature-rich Telegram bot with coin system, games, and leaderboard.

## Features
- Contact sharing on start with 50 coin welcome bonus
- Daily check-in with streak multiplier (up to 100 coins/day)
- Spin wheel (hourly, prizes up to 100 coins JACKPOT)
- Tasks: Watch Ad (+20), Survey (+30), Share Bot (+15)
- Quiz games with random rewards (15-40 coins)
- Coin flip gambling (bet 10, win 20)
- Mystery boxes (cost 25, win up to 150 Legendary!)
- Referral system (+100 coins per referral)
- Top 10 Leaderboard
- Level & XP system
- Full profile stats & transaction history

## Setup
1. Create bot via @BotFather on Telegram
2. Create Supabase project, run `schema.sql` in SQL Editor
3. Deploy on Render as Docker worker with env vars:
   - `BOT_TOKEN` - from BotFather
   - `SUPABASE_URL` - your project URL
   - `SUPABASE_KEY` - your anon/service key
4. Monitor with UptimeRobot

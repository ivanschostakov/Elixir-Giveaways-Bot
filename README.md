# Elixir Giveaways Bot

Telegram giveaway service that validates participation rules across Telegram, website orders, reviews, and CRM systems.

## Highlights

- Admin workflows for creating and managing giveaways.
- Participant validation through configurable conditions.
- Telegram join and referral conditions.
- Website order and review verification.
- amoCRM and Bitrix24 integrations.
- PostgreSQL persistence with SQLAlchemy and Alembic migrations.
- Configurable daily and weekly reminder workers.

## Project Structure

- `src/bot/`: Telegram handlers, keyboards, states, reminders, and user-facing text.
- `src/condition/`: reusable giveaway eligibility conditions.
- `src/database/`: models, schemas, and CRUD operations.
- `src/integrations/`: CRM and external verification clients.
- `migrations/`: Alembic database migrations.

## Local Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
alembic upgrade head
python run.py
```

The bot requires PostgreSQL and a Telegram bot token. CRM integrations can be configured independently through `.env`.

## Security

- Never commit `.env`, bot tokens, CRM credentials, participant exports, or logs.
- Use separate development credentials when testing integrations.
- Rotate any credential that has previously appeared in Git history.

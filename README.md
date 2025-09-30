# Grokgram

A Telegram bot that receives messages and responds using Grok agent via LangChain.

## Prerequisites

- Python 3.13+

## Setup

1. Activate the virtual environment:

   ```
   source venv/bin/activate
   ```

2. Create a `.env` file from `.env.example` and fill in your tokens:

   ```
   cp .env.example .env
   # Edit .env with your TELEGRAM_BOT_TOKEN, XAI_API_KEY and TELEGRAM_ALERT_CHAT_ID
   ```

3. Run the bot:
   ```
   python main.py
   ```

## Obtaining API Keys

### Telegram Bot Token

- Open Telegram and search for @BotFather.
- Send `/newbot` and follow the instructions to create a new bot.
- Copy the provided token and paste it into `.env` as `TELEGRAM_BOT_TOKEN`.

### xAI API Key

- Sign up or log in at [xAI Console](https://console.x.ai/).
- Navigate to API keys and create a new one.
- Copy the API key and paste it into `.env` as `XAI_API_KEY`.

## Usage

- Start the bot with `/start` in Telegram.
- Send a message prefixed with `1` on the first line so the bot treats it as a query.

## Railway Webhook Notifications

- The FastAPI server embedded in `main.py` exposes `POST /webhook/railway` for Railway notifications.
- Set the following environment variables alongside the existing ones:
  - `TELEGRAM_ALERT_CHAT_ID`: ID of the chat (user or group) that should receive deployment alerts.
  - `WEBHOOK_PORT` (optional): Port for the HTTP server (defaults to `8000`).
  - `WEBHOOK_HOST` (optional): Interface to bind (defaults to `0.0.0.0`).
  - `RAILWAY_WEBHOOK_SECRET` (optional): Shared secret the webhook must send via the `X-Railway-Secret` header.
- Configure Railway to send webhooks to `https://<your-host>:<port>/webhook/railway`.
- The bot will forward the payload summary and the raw JSON body to the Telegram chat specified by `TELEGRAM_ALERT_CHAT_ID`.

## Notes

- The bot uses the `grok-4-fast-non-reasoning` model.
- Ensure your xAI account has sufficient credits for API usage.

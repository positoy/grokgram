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
   # Edit .env with your TELEGRAM_BOT_TOKEN and XAI_API_KEY
   ```

3. (Optional) Configure GitHub Pull Request notifications:

   - Add `GITHUB_PR_CHAT_ID` to `.env` with the Telegram chat ID that should receive
     alerts when a pull request is opened.
   - Optionally set `GITHUB_WEBHOOK_HOST` and `GITHUB_WEBHOOK_PORT` to control where
     the webhook server listens. The default is `0.0.0.0:8000`.
   - Point your GitHub repository webhook to `http://<host>:<port>/github/webhook`
     and select the **Pull requests** event.

4. Run the bot:
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
- Send any text message, and the bot will respond using Grok.

## Notes

- The bot uses the `grok-beta` model.
- Ensure your xAI account has sufficient credits for API usage.

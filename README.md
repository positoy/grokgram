# Grokgram

A Telegram bot that receives messages and responds using Grok agent via LangChain.

## Prerequisites

- Python 3.13+ (로컬 개발용)
- Vercel account (배포용)

## 로컬 개발 Setup

1. Activate the virtual environment:

   ```
   source venv/bin/activate
   ```

2. Create a `.env` file and fill in your tokens:

   ```
   # .env 파일 생성
   TELEGRAM_BOT_TOKEN=your_telegram_bot_token
   XAI_API_KEY=your_xai_api_key
   ```

3. Run the bot locally:

   ```
   python main.py
   ```

## Vercel 배포 (권장)

### 1. Vercel에 프로젝트 연결

```bash
# Vercel CLI 설치 (아직 설치하지 않은 경우)
npm install -g vercel

# Vercel에 로그인
vercel login

# 프로젝트 초기화
vercel

# 또는 기존 프로젝트에 연결
vercel link
```

### 2. 환경변수 설정

Vercel 대시보드에서 환경변수 설정:

```bash
# 또는 CLI로 설정
vercel env add TELEGRAM_BOT_TOKEN
vercel env add XAI_API_KEY
```

### 3. 배포

```bash
vercel --prod
```

### 4. Webhook 설정

배포 완료 후, 제공된 URL을 사용하여 webhook 설정:

```bash
# 환경변수에 VERCEL_URL 추가 (Vercel에서 자동 설정됨)
python set_webhook.py

# 또는 수동으로 설정
curl -X POST "https://api.telegram.org/bot<YOUR_BOT_TOKEN>/setWebhook" \
  -H "Content-Type: application/json" \
  -d '{"url": "https://your-vercel-url.vercel.app/api/webhook"}'
```

### 5. Webhook 정보 확인

```bash
python set_webhook.py info
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

## Architecture

- `main.py`: 로컬 개발용 polling 모드
- `api/webhook.py`: Vercel 서버리스용 webhook 모드
- `system_prompt.py`: Grok system prompt 관리
- `set_webhook.py`: Webhook 설정 유틸리티

## Notes

- The bot uses the `grok-4-fast-non-reasoning` model.
- Ensure your xAI account has sufficient credits for API usage.
- Vercel 서버리스 환경에서는 함수 실행 시간 제한이 있으므로 긴 응답은 분할될 수 있습니다.
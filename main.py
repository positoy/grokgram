import asyncio
import json
import os
from typing import Any

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request, status
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, ContextTypes, filters
import uvicorn
from langchain_xai import ChatXAI
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage
from langchain_core.chat_history import BaseChatMessageHistory
from system_prompt import create_system_prompt

class SimpleChatMessageHistory(BaseChatMessageHistory):
    """간단한 채팅 메시지 히스토리 구현"""

    def __init__(self, max_messages: int = 10):
        super().__init__()
        self.messages = []
        self.max_messages = max_messages

    def add_user_message(self, message: str) -> None:
        """사용자 메시지 추가"""
        self.messages.append(HumanMessage(content=message))
        self._trim_messages()

    def add_ai_message(self, message: str) -> None:
        """AI 메시지 추가"""
        self.messages.append(AIMessage(content=message))
        self._trim_messages()

    def _trim_messages(self) -> None:
        """최대 메시지 개수를 초과하면 오래된 메시지 제거"""
        if len(self.messages) > self.max_messages:
            self.messages = self.messages[-self.max_messages:]

    def clear(self) -> None:
        """메시지 히스토리 초기화"""
        self.messages = []

def validate_and_extract_question(user_message: str) -> str | None:
    """
    사용자의 메시지를 검증하고 "1" 다음의 실제 질문을 추출합니다.

    Args:
        user_message: 사용자가 보낸 원본 메시지

    Returns:
        검증된 질문 (1로 시작하지 않거나 빈 질문인 경우 None)
    """
    # 첫 줄이 "1"로 시작하는지 확인
    first_line = user_message.split('\n')[0].strip()
    if not first_line.startswith('1'):
        return None

    # 첫 줄에서 "1" 부분만 제거하고 나머지 유지
    lines = user_message.split('\n')
    actual_question = lines[0][1:]  # 첫 줄에서 "1" 제거
    if len(lines) > 1:
        # 여러 줄인 경우 나머지 줄들 붙임
        actual_question += '\n' + '\n'.join(lines[1:])
    actual_question = actual_question.strip()

    # 빈 질문인 경우 None 반환
    return actual_question if actual_question else None

load_dotenv()

BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
XAI_API_KEY = os.getenv('XAI_API_KEY')
TELEGRAM_ALERT_CHAT_ID = os.getenv('TELEGRAM_ALERT_CHAT_ID')
RAILWAY_WEBHOOK_SECRET = os.getenv('RAILWAY_WEBHOOK_SECRET')
WEBHOOK_HOST = os.getenv('WEBHOOK_HOST', '0.0.0.0')
WEBHOOK_PORT_RAW = os.getenv('WEBHOOK_PORT', '8000')

try:
    WEBHOOK_PORT = int(WEBHOOK_PORT_RAW)
except ValueError:
    raise RuntimeError(f"WEBHOOK_PORT must be an integer, got: {WEBHOOK_PORT_RAW}")

llm = ChatXAI(
    model_name="grok-4-fast-non-reasoning",
    xai_api_key=XAI_API_KEY,
    xai_api_base="https://api.x.ai/v1",
)

def format_railway_message(payload: dict[str, Any]) -> str:
    """Format a Telegram-friendly message from the Railway webhook payload."""

    project = payload.get('project', {}) or {}
    environment = payload.get('environment', {}) or {}
    deployment = payload.get('deployment', {}) or {}
    service = payload.get('service', {}) or {}
    change = payload.get('change', {}) or {}

    status_text = (deployment.get('status') or change.get('type') or 'update').replace('_', ' ').title()
    lines = [f"[Railway] {status_text}"]

    if project_name := project.get('name'):
        lines.append(f"Project: {project_name}")
    if env_name := environment.get('name'):
        lines.append(f"Environment: {env_name}")
    if service_name := service.get('name'):
        lines.append(f"Service: {service_name}")
    if deployment_id := deployment.get('id'):
        lines.append(f"Deployment ID: {deployment_id}")
    if url := deployment.get('url'):
        lines.append(f"URL: {url}")
    if description := payload.get('description') or change.get('description'):
        lines.append(f"Description: {description}")

    raw_payload = json.dumps(payload, indent=2, ensure_ascii=True)
    max_raw_length = 1500
    if len(raw_payload) > max_raw_length:
        raw_payload = raw_payload[: max_raw_length - 3] + '...'

    lines.append("")
    lines.append("Raw payload:")
    lines.append(raw_payload)

    return '\n'.join(lines)


def create_webhook_app(telegram_app: Application) -> FastAPI:
    """Create a FastAPI app exposing a Railway webhook endpoint."""

    api = FastAPI()

    @api.post('/webhook/railway')
    async def railway_webhook(request: Request) -> dict[str, str]:
        if RAILWAY_WEBHOOK_SECRET:
            provided_secret = request.headers.get('X-Railway-Secret')
            if provided_secret != RAILWAY_WEBHOOK_SECRET:
                raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail='Invalid webhook secret')

        try:
            payload = await request.json()
        except Exception as exc:  # noqa: BLE001 - FastAPI converts this to 400
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail='Invalid JSON payload') from exc

        if not isinstance(payload, dict):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail='Payload must be a JSON object')

        if not TELEGRAM_ALERT_CHAT_ID:
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail='TELEGRAM_ALERT_CHAT_ID is not configured')

        message = format_railway_message(payload)
        await telegram_app.bot.send_message(chat_id=TELEGRAM_ALERT_CHAT_ID, text=message)

        return {'status': 'ok'}

    return api

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    # 메시지가 없는 업데이트는 무시
    if not update.message:
        return

    await update.message.reply_text('Hi! I am a Grok-powered bot.')

async def reset_memory(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """사용자의 대화 메모리를 초기화합니다."""
    # 메시지가 없는 업데이트는 무시
    if not update.message:
        return

    user_id = update.effective_user.id
    if user_id in context.user_data and 'chat_history' in context.user_data[user_id]:
        context.user_data[user_id]['chat_history'].clear()
        await update.message.reply_text('대화 메모리가 초기화되었습니다. 새로운 대화를 시작합니다!')
    else:
        await update.message.reply_text('초기화할 메모리가 없습니다.')

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    # 메시지가 없는 업데이트는 무시
    if not update.message:
        return

    user_message = update.message.text
    user_id = update.effective_user.id

    # 메시지 검증 및 질문 추출
    actual_question = validate_and_extract_question(user_message)
    if actual_question is None:
        # "1"로 시작하지 않거나 빈 질문인 경우 무시
        return

    try:
        # 사용자별 채팅 히스토리 초기화 (없으면 생성)
        if user_id not in context.user_data:
            context.user_data[user_id] = {'chat_history': SimpleChatMessageHistory(max_messages=10)}

        chat_history = context.user_data[user_id]['chat_history']

        # 사용자 메시지 추가
        chat_history.add_user_message(actual_question)

        # LLM에 전달할 메시지 구성 (시스템 메시지 + 채팅 히스토리)
        messages = [
            SystemMessage(content=create_system_prompt(is_mobile=True, is_subjective=False))
        ] + chat_history.messages

        response = llm.invoke(messages)

        # AI 응답을 히스토리에 추가
        chat_history.add_ai_message(response.content)

        await update.message.reply_text(response.content)
    except Exception as e:
        await update.message.reply_text(f'Sorry, something went wrong: {str(e)}')


async def run_bot(application: Application, stop_event: asyncio.Event) -> None:
    """Start the Telegram bot and keep it alive until stop_event is set."""

    await application.initialize()
    await application.start()
    await application.updater.start_polling(allowed_updates=Update.ALL_TYPES)

    try:
        await stop_event.wait()
    finally:
        await application.updater.stop()
        await application.stop()
        await application.shutdown()


async def run_webhook_server(api_app: FastAPI, stop_event: asyncio.Event) -> None:
    """Run the FastAPI server that receives Railway webhooks."""

    config = uvicorn.Config(  # type: ignore[attr-defined]
        api_app,
        host=WEBHOOK_HOST,
        port=WEBHOOK_PORT,
        loop='asyncio',
        log_level=os.getenv('UVICORN_LOG_LEVEL', 'info'),
    )
    server = uvicorn.Server(config)  # type: ignore[attr-defined]

    async def serve() -> None:
        try:
            await server.serve()
        except asyncio.CancelledError:
            server.should_exit = True
            raise

    server_task = asyncio.create_task(serve())

    try:
        await stop_event.wait()
        server.should_exit = True
        await server_task
    finally:
        if not server_task.done():
            server_task.cancel()
            await asyncio.gather(server_task, return_exceptions=True)


async def main_async() -> None:
    if not BOT_TOKEN or not XAI_API_KEY:
        raise RuntimeError('Please set TELEGRAM_BOT_TOKEN and XAI_API_KEY in the environment or .env file')

    application = Application.builder().token(BOT_TOKEN).build()
    application.add_handler(CommandHandler('start', start))
    application.add_handler(CommandHandler('reset', reset_memory))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    webhook_app = create_webhook_app(application)

    stop_event = asyncio.Event()

    try:
        async with asyncio.TaskGroup() as tg:
            tg.create_task(run_bot(application, stop_event))
            tg.create_task(run_webhook_server(webhook_app, stop_event))
            try:
                await asyncio.Future()
            except asyncio.CancelledError:
                stop_event.set()
                raise
    finally:
        stop_event.set()


def main() -> None:
    try:
        asyncio.run(main_async())
    except KeyboardInterrupt:
        pass


if __name__ == '__main__':
    main()

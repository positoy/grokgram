import asyncio
import json
import logging
import os
from typing import Optional

from aiohttp import ContentTypeError, web
from dotenv import load_dotenv
from langchain_core.chat_history import BaseChatMessageHistory
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_xai import ChatXAI
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters

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

logging.basicConfig(level=logging.INFO)

load_dotenv()

BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
XAI_API_KEY = os.getenv('XAI_API_KEY')
GITHUB_CHAT_ID_ENV = os.getenv('GITHUB_PR_CHAT_ID')
WEBHOOK_HOST = os.getenv('GITHUB_WEBHOOK_HOST', '0.0.0.0')
WEBHOOK_PORT = int(os.getenv('GITHUB_WEBHOOK_PORT', '8000'))

telegram_application: Optional[Application] = None
webhook_runner: Optional[web.AppRunner] = None

def _parse_chat_id(chat_id_env: Optional[str]) -> Optional[int]:
    """환경 변수에서 읽은 채팅 ID를 정수로 변환합니다."""

    if not chat_id_env:
        return None

    try:
        return int(chat_id_env)
    except ValueError:
        logging.error("잘못된 GITHUB_PR_CHAT_ID 값입니다: %s", chat_id_env)
        return None


GITHUB_CHAT_ID = _parse_chat_id(GITHUB_CHAT_ID_ENV)

llm = ChatXAI(
    model_name="grok-4-fast-non-reasoning",
    xai_api_key=XAI_API_KEY,
    xai_api_base="https://api.x.ai/v1",
)


async def handle_github_webhook(request: web.Request) -> web.StreamResponse:
    """GitHub Pull Request 웹훅을 처리합니다."""

    if GITHUB_CHAT_ID is None:
        logging.warning("GITHUB_PR_CHAT_ID가 설정되지 않아 웹훅 알림을 보낼 수 없습니다.")
        return web.Response(status=503, text='Chat ID not configured')

    if telegram_application is None:
        logging.warning("텔레그램 애플리케이션이 아직 초기화되지 않았습니다.")
        return web.Response(status=503, text='Bot not ready')

    try:
        payload = await request.json()
    except (json.JSONDecodeError, ContentTypeError):
        logging.exception("잘못된 JSON 페이로드입니다.")
        return web.Response(status=400, text='Invalid JSON payload')

    action = payload.get('action')
    pull_request = payload.get('pull_request')

    # pull_request 필드가 없는 이벤트는 무시합니다.
    if not pull_request:
        return web.Response(status=200, text='Event ignored')

    if action not in {'opened', 'reopened'}:
        logging.info("지원하지 않는 PR 액션입니다: %s", action)
        return web.Response(status=200, text='Action ignored')

    repo_info = payload.get('repository', {})
    sender_info = payload.get('sender', {})

    repo_name = repo_info.get('full_name', '알 수 없는 저장소')
    pr_title = pull_request.get('title', '제목 없음')
    pr_url = pull_request.get('html_url', '')
    sender_login = sender_info.get('login')

    message_lines = [f"📣 {repo_name} 저장소에 새로운 Pull Request가 생성되었습니다."]
    message_lines.append(f"제목: {pr_title}")
    if sender_login:
        message_lines.append(f"작성자: {sender_login}")
    if pr_url:
        message_lines.append(pr_url)

    message = '\n'.join(message_lines)

    try:
        await telegram_application.bot.send_message(chat_id=GITHUB_CHAT_ID, text=message)
    except Exception:
        logging.exception("GitHub PR 알림 전송 중 오류가 발생했습니다.")
        return web.Response(status=500, text='Failed to send message')

    return web.Response(status=200, text='Notification sent')

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

    logging.info(
        "result.0.message.chat.id: %s",
        update.effective_chat.id if update.effective_chat else "Unknown",
    )

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

async def start_webhook_server() -> None:
    """GitHub 웹훅 서버를 시작합니다."""

    global webhook_runner

    if webhook_runner is not None:
        logging.debug("GitHub 웹훅 서버가 이미 실행 중입니다.")
        return

    github_app = web.Application()
    github_app.router.add_post('/github/webhook', handle_github_webhook)

    webhook_runner = web.AppRunner(github_app)
    await webhook_runner.setup()

    site = web.TCPSite(webhook_runner, host=WEBHOOK_HOST, port=WEBHOOK_PORT)
    await site.start()

    logging.info(
        "GitHub 웹훅 서버가 시작되었습니다: http://%s:%s/github/webhook",
        WEBHOOK_HOST,
        WEBHOOK_PORT,
    )


async def stop_webhook_server() -> None:
    """GitHub 웹훅 서버를 종료합니다."""

    global webhook_runner

    if webhook_runner is None:
        return

    await webhook_runner.cleanup()
    webhook_runner = None


async def main() -> None:
    if not BOT_TOKEN or not XAI_API_KEY:
        print("Please set TELEGRAM_BOT_TOKEN and XAI_API_KEY in .env file")
        return

    global telegram_application
    telegram_application = Application.builder().token(BOT_TOKEN).build()
    telegram_application.add_handler(CommandHandler("start", start))
    telegram_application.add_handler(CommandHandler("reset", reset_memory))
    telegram_application.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message)
    )

    await start_webhook_server()

    try:
        await telegram_application.run_polling(
            allowed_updates=Update.ALL_TYPES,
            close_loop=False,
        )
    finally:
        await stop_webhook_server()


if __name__ == '__main__':
    asyncio.run(main())

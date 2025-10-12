import json
import logging
import os
from typing import Optional

from aiohttp import ContentTypeError, web
from dotenv import load_dotenv
from langchain_core.messages import SystemMessage
from langchain.memory import ConversationSummaryMemory
from langchain_xai import ChatXAI
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters

from system_prompt import create_system_prompt

logging.basicConfig(level=logging.INFO)

load_dotenv()

WHITELIST_USER_IDS_ENV = os.getenv('WHITELIST_USER_IDS')
WHITELIST_USER_IDS = []
if WHITELIST_USER_IDS_ENV:
    try:
        WHITELIST_USER_IDS = [int(id.strip()) for id in WHITELIST_USER_IDS_ENV.split(',')]
    except ValueError:
        logging.error("Invalid WHITELIST_USER_IDS format: %s", WHITELIST_USER_IDS_ENV)
        WHITELIST_USER_IDS = []

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

    if not WHITELIST_USER_IDS:
        logging.warning("WHITELIST_USER_IDS가 설정되지 않아 웹훅 알림을 보낼 수 없습니다.")
        return web.Response(status=503, text='Whitelist not configured')

    if telegram_application is None:
        logging.warning("텔레그램 애플리케이션이 아직 초기화되지 않았습니다.")
        return web.Response(status=503, text='Bot not ready')

    # log body of the request
    logging.info("request body: %s", await request.text())

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

    try:
        for user_id in WHITELIST_USER_IDS:
            await telegram_application.bot.send_message(chat_id=user_id, text='\n'.join(message_lines))
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
    if user_id in context.user_data and 'chat_memory' in context.user_data[user_id]:
        context.user_data[user_id]['chat_memory'].clear()
        await update.message.reply_text('대화 메모리가 초기화되었습니다. 새로운 대화를 시작합니다!')
    else:
        await update.message.reply_text('초기화할 메모리가 없습니다.')

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    # 메시지가 없는 업데이트는 무시
    if not update.message:
        return

    user_message = update.message.text
    user_id = update.effective_user.id

    logging.info("user_id: %s", user_id)
    logging.info(
        "result.0.message.chat.id: %s",
        update.effective_chat.id if update.effective_chat else "Unknown",
    )

    # 화이트리스트 체크
    if user_id not in WHITELIST_USER_IDS:
        return

    try:
        # 사용자별 채팅 히스토리 초기화 (없으면 생성)
        if user_id not in context.user_data:
            context.user_data[user_id] = {'chat_memory': ConversationSummaryMemory(llm=llm, return_messages=True)}

        chat_memory = context.user_data[user_id]['chat_memory']

        # 사용자 메시지 추가
        chat_memory.chat_memory.add_user_message(user_message)

        # LLM에 전달할 메시지 구성 (시스템 메시지 + 채팅 히스토리)
        messages = [
            SystemMessage(content=create_system_prompt(is_mobile=True, is_subjective=False))
        ] + chat_memory.chat_memory.messages

        response = llm.invoke(messages)

        # AI 응답을 히스토리에 추가
        chat_memory.chat_memory.add_ai_message(response.content)

        await update.message.reply_text(response.content)
    except Exception as e:
        await update.message.reply_text(f'Sorry, something went wrong: {str(e)}')

async def start_webhook_server() -> None:
    """GitHub 웹훅 서버를 시작합니다."""

    global webhook_runner

    if webhook_runner is not None:
        logging.info("웹훅 서버가 이미 실행 중입니다.")
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


async def on_application_post_init(_application: Application) -> None:
    """텔레그램 애플리케이션 초기화 후 웹훅 서버를 시작합니다."""

    await start_webhook_server()


async def on_application_post_shutdown(_application: Application) -> None:
    """텔레그램 애플리케이션 종료 시 웹훅 서버를 정리합니다."""

    await stop_webhook_server()


def main() -> None:
    if not BOT_TOKEN or not XAI_API_KEY:
        print("Please set TELEGRAM_BOT_TOKEN and XAI_API_KEY in .env file")
        return

    global telegram_application
    telegram_application = (
        Application.builder()
        .token(BOT_TOKEN)
        .post_init(on_application_post_init)
        .post_shutdown(on_application_post_shutdown)
        .build()
    )
    telegram_application.add_handler(CommandHandler("start", start))
    telegram_application.add_handler(CommandHandler("reset", reset_memory))
    telegram_application.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message)
    )

    telegram_application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == '__main__':
    main()

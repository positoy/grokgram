import asyncio
import json
import logging
import os
from dataclasses import dataclass
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


@dataclass(frozen=True)
class BotConfig:
    """봇 실행에 필요한 설정 값 모음."""

    telegram_token: str
    xai_api_key: str
    github_chat_id: Optional[int]
    webhook_host: str
    webhook_port: int


def _parse_chat_id(chat_id_env: Optional[str]) -> Optional[int]:
    """환경 변수에서 읽은 채팅 ID를 정수로 변환합니다."""

    if not chat_id_env:
        return None

    try:
        return int(chat_id_env)
    except ValueError:
        logging.error("잘못된 GITHUB_PR_CHAT_ID 값입니다: %s", chat_id_env)
        return None


def _parse_port(port_env: Optional[str]) -> int:
    """포트 환경 변수를 정수로 파싱합니다."""

    if not port_env:
        return 8000

    try:
        port = int(port_env)
    except ValueError:
        logging.error("잘못된 GITHUB_WEBHOOK_PORT 값입니다: %s", port_env)
        return 8000

    if not 0 <= port <= 65535:
        logging.error("지원하지 않는 포트 범위입니다: %s", port)
        return 8000

    return port


def load_config() -> Optional[BotConfig]:
    """환경 변수에서 봇 설정을 로드합니다."""

    telegram_token = os.getenv('TELEGRAM_BOT_TOKEN')
    xai_api_key = os.getenv('XAI_API_KEY')

    missing: list[str] = []
    if not telegram_token:
        missing.append('TELEGRAM_BOT_TOKEN')
    if not xai_api_key:
        missing.append('XAI_API_KEY')

    if missing:
        logging.error("필수 환경 변수가 설정되지 않았습니다: %s", ', '.join(missing))
        return None

    github_chat_id = _parse_chat_id(os.getenv('GITHUB_PR_CHAT_ID'))
    webhook_host = os.getenv('GITHUB_WEBHOOK_HOST', '0.0.0.0')
    webhook_port = _parse_port(os.getenv('GITHUB_WEBHOOK_PORT'))

    return BotConfig(
        telegram_token=telegram_token,
        xai_api_key=xai_api_key,
        github_chat_id=github_chat_id,
        webhook_host=webhook_host,
        webhook_port=webhook_port,
    )


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

        llm_obj = context.bot_data.get('llm')
        if not isinstance(llm_obj, ChatXAI):
            logging.error("LLM 인스턴스가 초기화되지 않았습니다.")
            await update.message.reply_text('Sorry, the bot is not ready yet.')
            return

        response = await asyncio.to_thread(llm_obj.invoke, messages)

        # AI 응답을 히스토리에 추가
        chat_history.add_ai_message(response.content)

        await update.message.reply_text(response.content)
    except Exception as e:
        await update.message.reply_text(f'Sorry, something went wrong: {str(e)}')


class BotRuntime:
    """텔레그램 봇과 GitHub 웹훅 서버 실행을 관리합니다."""

    def __init__(self, config: BotConfig):
        self._config = config
        self._webhook_runner: Optional[web.AppRunner] = None
        self._bot_ready = asyncio.Event()

        self.telegram_application = self._create_telegram_application()
        self.web_app = web.Application()
        self.web_app.router.add_post('/github/webhook', self._handle_github_webhook)

    def _create_telegram_application(self) -> Application:
        """텔레그램 애플리케이션을 생성하고 핸들러를 등록합니다."""

        application = (
            Application.builder()
            .token(self._config.telegram_token)
            .post_init(self._on_post_init)
            .build()
        )

        application.bot_data['llm'] = ChatXAI(
            model_name="grok-4-fast-non-reasoning",
            xai_api_key=self._config.xai_api_key,
            xai_api_base="https://api.x.ai/v1",
        )

        application.add_handler(CommandHandler("start", start))
        application.add_handler(CommandHandler("reset", reset_memory))
        application.add_handler(
            MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message)
        )

        return application

    async def _on_post_init(self, application: Application) -> None:
        """텔레그램 봇이 초기화된 후 호출되어 준비 상태를 표시합니다."""

        logging.info("텔레그램 애플리케이션 초기화 완료")
        self._bot_ready.set()

    async def _handle_github_webhook(self, request: web.Request) -> web.StreamResponse:
        """GitHub Pull Request 웹훅을 처리합니다."""

        if self._config.github_chat_id is None:
            logging.warning(
                "GITHUB_PR_CHAT_ID가 설정되지 않아 웹훅 알림을 보낼 수 없습니다."
            )
            return web.Response(status=200, text='Chat ID not configured')

        if not self._bot_ready.is_set():
            logging.warning("텔레그램 애플리케이션이 아직 초기화되지 않았습니다.")
            return web.Response(status=503, text='Bot not ready')

        event_type = request.headers.get('X-GitHub-Event')
        if event_type == 'ping':
            return web.Response(status=200, text='pong')

        if event_type and event_type != 'pull_request':
            logging.debug("지원하지 않는 GitHub 이벤트입니다: %s", event_type)
            return web.Response(status=200, text='Event ignored')

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
            await self.telegram_application.bot.send_message(
                chat_id=self._config.github_chat_id,
                text=message,
            )
        except Exception:
            logging.exception("GitHub PR 알림 전송 중 오류가 발생했습니다.")
            return web.Response(status=500, text='Failed to send message')

        return web.Response(status=200, text='Notification sent')

    async def start_webhook_server(self) -> None:
        """GitHub 웹훅 서버를 시작합니다."""

        if self._webhook_runner is not None:
            logging.debug("GitHub 웹훅 서버가 이미 실행 중입니다.")
            return

        self._webhook_runner = web.AppRunner(self.web_app)
        await self._webhook_runner.setup()

        site = web.TCPSite(
            self._webhook_runner,
            host=self._config.webhook_host,
            port=self._config.webhook_port,
        )
        await site.start()

        logging.info(
            "GitHub 웹훅 서버가 시작되었습니다: http://%s:%s/github/webhook",
            self._config.webhook_host,
            self._config.webhook_port,
        )

    async def stop_webhook_server(self) -> None:
        """GitHub 웹훅 서버를 종료합니다."""

        if self._webhook_runner is None:
            return

        await self._webhook_runner.cleanup()
        self._webhook_runner = None

    async def run(self) -> None:
        """텔레그램 봇과 웹훅 서버를 실행합니다."""

        await self.start_webhook_server()

        try:
            await self.telegram_application.run_polling(
                allowed_updates=Update.ALL_TYPES,
                close_loop=False,
            )
        finally:
            await self.stop_webhook_server()


async def main() -> None:
    config = load_config()
    if config is None:
        print("Please set TELEGRAM_BOT_TOKEN and XAI_API_KEY in .env file")
        return

    runtime = BotRuntime(config)
    await runtime.run()


if __name__ == '__main__':
    asyncio.run(main())

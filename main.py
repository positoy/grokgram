import os
import logging
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
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

logging.basicConfig(level=logging.INFO)

load_dotenv()

BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
XAI_API_KEY = os.getenv('XAI_API_KEY')

llm = ChatXAI(
    model_name="grok-4-fast-non-reasoning",
    xai_api_key=XAI_API_KEY,
    xai_api_base="https://api.x.ai/v1",
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

        response = llm.invoke(messages)

        # AI 응답을 히스토리에 추가
        chat_history.add_ai_message(response.content)

        await update.message.reply_text(response.content)
    except Exception as e:
        await update.message.reply_text(f'Sorry, something went wrong: {str(e)}')

def main() -> None:
    if not BOT_TOKEN or not XAI_API_KEY:
        print("Please set TELEGRAM_BOT_TOKEN and XAI_API_KEY in .env file")
        return
    application = Application.builder().token(BOT_TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("reset", reset_memory))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()

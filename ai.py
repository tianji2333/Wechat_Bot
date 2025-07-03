import os
import re
import logging
from http import HTTPStatus
from typing import Dict, Optional, List, Any

from dashscope import Application, MultiModalConversation

# —— 配置 —— #
API_KEY = os.getenv('DASHSCOPE_API_KEY', 'sk-e598553517e84d6fb57b3384382bf925')
APP_ID = '0bf1b585faed4370b949f92a92beaa4d'
SYS_PROMPT = (
    "你是一个上海公交爱好者，喜欢在群聊里和别人用上海话聊天，"
    "人格非常外向，但是要符合用户问的话题，一次消息少发一点，只能发一条消息"
)

# 全局会话历史表
message_table: Dict[str, List[Dict[str, Any]]] = {}

# 初始化日志
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)


class ChatBot:
    def __init__(
            self,
            api_key: str = API_KEY,
            app_id: str = APP_ID,
            system_prompt: str = SYS_PROMPT
    ) -> None:
        if not api_key or not app_id:
            raise ValueError("请先配置 API_KEY 和 APP_ID")
        self.api_key: str = api_key
        self.app_id: str = app_id
        self.system_prompt: str = system_prompt

        # 每个 user 的 session_id
        self._session_table: Dict[str, str] = {}

    def add_user(self, user_name: str) -> None:
        """为新用户初始化对话历史"""
        if user_name not in message_table:
            message_table[user_name] = []
            logging.info(f"新用户加入：{user_name}")

    def add_history(self, user_name: str, role: str, content: Any) -> None:
        """把一条消息追加到指定用户的历史里"""
        if user_name in message_table:
            message_table[user_name].append({"role": role, "content": content})

    @staticmethod
    def _clean_response(text: str) -> str:
        """清洗模型返回的文本，去除多余格式"""
        text = re.sub(r"\[.*?\]", "", text, flags=re.DOTALL)
        text = re.sub(r"\*\*\*|\*\*|\*", "", text)
        text = re.sub(r"^[#\-\t]+", "", text, flags=re.MULTILINE)
        text = re.sub(r"\n+", "\n", text)
        text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL)
        return text.strip()

    def reset_session(self, user: str) -> None:
        """清除某个 user 的会话，让下一次调用当作首次提问"""
        self._session_table.pop(user, None)
        logging.info(f"会话已重置：{user}")

    def chat(self, user: str, prompt: str) -> str:
        """
        向指定 user 提问，返回清洗后的文字答案并更新 session_id。
        """
        sid: Optional[str] = self._session_table.get(user)

        if sid is None:
            full_prompt = f"{self.system_prompt}\n\n{prompt}"
        else:
            full_prompt = prompt

        logging.info(f"→ 请求文字 user={user}, session_id={sid}:\n{full_prompt}")

        try:
            resp = Application.call(
                api_key=self.api_key,
                app_id=self.app_id,
                prompt=full_prompt,
                session_id=sid
            )
        except Exception:
            logging.exception("API 调用异常")
            return "抱歉，调用出错，请稍后再试。"

        if resp.status_code != HTTPStatus.OK:
            logging.error(
                "调用失败 code=%s request_id=%s message=%s",
                resp.status_code, resp.request_id, resp.message
            )
            return "抱歉，调用出错，请稍后再试。"

        raw = resp.output.text or ""
        cleaned = self._clean_response(raw)
        self._session_table[user] = resp.output.session_id
        logging.info(f"← 响应文字 user={user}, new_session_id={resp.output.session_id}:\n{cleaned}")
        return cleaned

    def chat_multimodal(self, user: str, messages: List[Dict[str, Any]]) -> str:
        """
        向指定 user 发送多模态消息（文字 + 图片）。
        messages 格式示例：
        [
          {"role": "system", "content": [{"text": "你是帮手"}]},
          {"role": "user", "content": [{"image": "https://.../dog.jpeg"}, {"text": "图中是什么?"}]}
        ]
        返回文字响应。
        """
        logging.info(f"→ 请求多模态 user={user}, messages={messages}")

        try:
            resp = MultiModalConversation.call(
                api_key=self.api_key,
                model='qwen-vl-max-latest',
                messages=messages
            )
        except Exception:
            logging.exception("多模态 API 调用异常")
            return "抱歉，多模态调用出错，请稍后再试。"

        # 假设返回为 choices[0].message.content 列表中的 text
        choice = resp.output.choices[0].message.content
        # content 可能是 [{'text': '...'}]
        text = ''
        if isinstance(choice, list) and choice:
            first = choice[0]
            text = first.get('text', '')
        cleaned = self._clean_response(text)
        logging.info(f"← 响应多模态 user={user}: {cleaned}")
        return cleaned


# —— 在模块载入时创建全局 bot 实例 —— #
_bot = ChatBot()


# —— 模块级接口 —— #
def add_user(user_name: str) -> None:
    """在 app.py 里直接调用： ai.add_user('alice') """
    _bot.add_user(user_name)


def chat(user: str, prompt: str) -> str:
    """在 app.py 里直接调用： reply = ai.chat('alice', '你好') """
    return _bot.chat(user, prompt)


def chat_multimodal(user: str, messages: List[Dict[str, Any]]) -> str:
    """在 app.py 里直接调用多模态： reply = ai.chat_multimodal('alice', messages) """
    return _bot.chat_multimodal(user, messages)


def reset_session(user: str) -> None:
    """在需要时清除某用户会话历史"""
    _bot.reset_session(user)

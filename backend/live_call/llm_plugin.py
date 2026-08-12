"""A "LLM" plugin that doesn't call an LLM itself — it routes each call turn through
the calling feature's own existing send_message/send_turn function (see
live_call/dispatch.py), the exact function a typed or push-to-talk turn already goes
through. That function does the real Groq call internally, plus prompt-building, safety
checks, and turn persistence — so a Live Call turn is indistinguishable from a typed one
afterward, and none of that logic is duplicated here.
"""

import uuid
from typing import Awaitable, Callable

from livekit.agents import llm
from livekit.agents.types import DEFAULT_API_CONNECT_OPTIONS, NOT_GIVEN, APIConnectOptions, NotGivenOr

TurnHandler = Callable[[str], Awaitable[str]]


def _last_user_text(chat_ctx: llm.ChatContext) -> str:
    for message in reversed(chat_ctx.messages()):
        if message.role == "user":
            return message.text_content or ""
    return ""


class ServiceLLMStream(llm.LLMStream):
    def __init__(
        self,
        service_llm: "ServiceLLM",
        *,
        chat_ctx: llm.ChatContext,
        tools: list,
        conn_options: APIConnectOptions,
        user_text: str,
    ) -> None:
        super().__init__(service_llm, chat_ctx=chat_ctx, tools=tools, conn_options=conn_options)
        self._user_text = user_text
        self._turn_handler = service_llm.turn_handler

    async def _run(self) -> None:
        reply_text = await self._turn_handler(self._user_text)
        self._event_ch.send_nowait(
            llm.ChatChunk(id=str(uuid.uuid4()), delta=llm.ChoiceDelta(role="assistant", content=reply_text))
        )


class ServiceLLM(llm.LLM):
    def __init__(self, turn_handler: TurnHandler) -> None:
        super().__init__()
        self.turn_handler = turn_handler

    def chat(
        self,
        *,
        chat_ctx: llm.ChatContext,
        tools: list | None = None,
        conn_options: APIConnectOptions = DEFAULT_API_CONNECT_OPTIONS,
        parallel_tool_calls: NotGivenOr[bool] = NOT_GIVEN,
        tool_choice: NotGivenOr[object] = NOT_GIVEN,
        extra_kwargs: NotGivenOr[dict] = NOT_GIVEN,
    ) -> llm.LLMStream:
        return ServiceLLMStream(
            self,
            chat_ctx=chat_ctx,
            tools=tools or [],
            conn_options=conn_options,
            user_text=_last_user_text(chat_ctx),
        )

from dataclasses import dataclass
from typing import Any, TypeVar, overload

import httpx
from ollama import AsyncClient as OllamaAsyncClient
from pydantic import BaseModel

from browser_use.llm.base import BaseChatModel
from browser_use.llm.exceptions import ModelProviderError
from browser_use.llm.messages import BaseMessage
from browser_use.llm.ollama.serializer import OllamaMessageSerializer
from browser_use.llm.views import ChatInvokeCompletion

T = TypeVar('T', bound=BaseModel)


@dataclass
class ChatOllama(BaseChatModel):
    """
    A wrapper around Ollama's chat model.
    """

    model: str

    # # Model params
    # TODO (matic): Why is this commented out?
    # temperature: float | None = None

    # Client initialization parameters
    host: str | None = None
    timeout: float | httpx.Timeout | None = None
    client_params: dict[str, Any] | None = None

    # Static
    @property
    def provider(self) -> str:
        return 'ollama'

    def _get_client_params(self) -> dict[str, Any]:
        """Prepare client parameters dictionary."""
        return {
            'host': self.host,
            'timeout': self.timeout,
            'client_params': self.client_params,
        }

    def get_client(self) -> OllamaAsyncClient:
        """
        Returns an OllamaAsyncClient client.
        """
        return OllamaAsyncClient(host=self.host, timeout=self.timeout, **self.client_params or {})

    @property
    def name(self) -> str:
        return self.model

    @overload
    async def ainvoke(self, messages: list[BaseMessage], output_format: None = None) -> ChatInvokeCompletion[str]: ...

    @overload
    async def ainvoke(self, messages: list[BaseMessage], output_format: type[T]) -> ChatInvokeCompletion[T]: ...

    async def ainvoke(
        self, messages: list[BaseMessage], output_format: type[T] | None = None
    ) -> ChatInvokeCompletion[T] | ChatInvokeCompletion[str]:
        ollama_messages = OllamaMessageSerializer.serialize_messages(messages)

        try:
            # Special handling for gpt-oss models
            if self.model.startswith("gpt-oss"):
                print(f"\n🔍 DEBUG: Sending {len(messages)} messages to {self.model}")
                print(f"🔍 DEBUG: output_format = {output_format}")
                for i, msg in enumerate(messages):
                    print(f"Message {i+1} ({getattr(msg, 'role', 'unknown')}): {str(msg)[:200]}...")

                # Always get unstructured output
                response = await self.get_client().chat(
                    model=self.model,
                    messages=ollama_messages,
                )
                content = response.message.content or ''
                print(f"🔍 DEBUG: Got unstructured response:")
                print(f"Response content: '{content}'")
                print(f"Response length: {len(content)}")

                if output_format is not None and content:
                    import json
                    try:
                        raw = content.strip()
                        if not raw.startswith('{'):
                            import re
                            json_match = re.search(r'\{.*\}', raw, re.DOTALL)
                            if json_match:
                                raw = json_match.group(0)
                        parsed_json = json.loads(raw)
                        print(f"✅ DEBUG: Successfully parsed JSON: {list(parsed_json.keys())}")
                        structured_output = output_format.model_validate(parsed_json)
                        return ChatInvokeCompletion(completion=structured_output, usage=None)
                    except (json.JSONDecodeError, Exception) as e:
                        print(f"❌ DEBUG: Failed to parse JSON: {e}")
                        print(f"Raw content: {raw}")
                        return ChatInvokeCompletion(completion=raw, usage=None)
                elif not content:
                    raise Exception(f"Empty response from {self.model}")
                else:
                    return ChatInvokeCompletion(completion=content, usage=None)
            else:
                # Default behavior for other models
                if output_format is None:
                    response = await self.get_client().chat(
                        model=self.model,
                        messages=ollama_messages,
                    )
                    return ChatInvokeCompletion(completion=response.message.content or '', usage=None)
                else:
                    schema = output_format.model_json_schema()
                    response = await self.get_client().chat(
                        model=self.model,
                        messages=ollama_messages,
                        format=schema,
                    )
                    completion = response.message.content or ''
                    if output_format is not None:
                        completion = output_format.model_validate_json(completion)
                    return ChatInvokeCompletion(completion=completion, usage=None)

        except Exception as e:
            print(f"🔍 DEBUG: Exception in ainvoke: {e}")
            import traceback
            traceback.print_exc()
            raise ModelProviderError(message=str(e), model=self.name) from e

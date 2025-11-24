from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Any, Callable

from browser_use.llm.anthropic.chat import ChatAnthropic
from browser_use.llm.azure.chat import ChatAzureOpenAI
from browser_use.llm.browser_use.chat import ChatBrowserUse
from browser_use.llm.deepseek.chat import ChatDeepSeek
from browser_use.llm.groq.chat import ChatGroq
from browser_use.llm.google.chat import ChatGoogle
from browser_use.llm.openai.chat import ChatOpenAI
from browser_use.config import CONFIG


@dataclass
class ProviderOption:
        """LLM provider definition for CLI selection."""

        name: str
        env_keys: tuple[str, ...]
        default_model: str
        builder: Callable[[str, float, str | None], Any]

        def is_available(self, api_keys: dict[str, str | None]) -> bool:
                return any(api_keys.get(key) for key in self.env_keys)

        def create_client(self, model_name: str, temperature: float, api_key: str | None) -> Any:
                return self.builder(model_name, temperature, api_key)


PROVIDER_OPTIONS: tuple[ProviderOption, ...] = (
        ProviderOption(
                name='browseruse',
                env_keys=('BROWSER_USE_API_KEY',),
                default_model='bu-latest',
                builder=lambda model, temperature, api_key: ChatBrowserUse(model=model, temperature=temperature, api_key=api_key),
        ),
        ProviderOption(
                name='openai',
                env_keys=('OPENAI_API_KEY',),
                default_model='gpt-5-mini',
                builder=lambda model, temperature, api_key: ChatOpenAI(model=model, temperature=temperature, api_key=api_key),
        ),
        ProviderOption(
                name='azure',
                env_keys=('AZURE_OPENAI_KEY', 'AZURE_OPENAI_API_KEY'),
                default_model='gpt-4o-mini',
                builder=lambda model, temperature, api_key: ChatAzureOpenAI(model=model, temperature=temperature, api_key=api_key),
        ),
        ProviderOption(
                name='anthropic',
                env_keys=('ANTHROPIC_API_KEY',),
                default_model='claude-3-5-sonnet-latest',
                builder=lambda model, temperature, api_key: ChatAnthropic(model=model, temperature=temperature, api_key=api_key),
        ),
        ProviderOption(
                name='google',
                env_keys=('GOOGLE_API_KEY',),
                default_model='gemini-2.5-flash',
                builder=lambda model, temperature, api_key: ChatGoogle(model=model, temperature=temperature, api_key=api_key),
        ),
        ProviderOption(
                name='deepseek',
                env_keys=('DEEPSEEK_API_KEY',),
                default_model='deepseek-chat',
                builder=lambda model, temperature, api_key: ChatDeepSeek(model=model, temperature=temperature, api_key=api_key),
        ),
        ProviderOption(
                name='groq',
                env_keys=('GROQ_API_KEY',),
                default_model='meta-llama/llama-4-scout-17b-16e-instruct',
                builder=lambda model, temperature, api_key: ChatGroq(model=model, temperature=temperature, api_key=api_key),
        ),
)


def gather_api_keys(model_config: dict[str, Any]) -> dict[str, str | None]:
        """Collect API keys from config and environment variables."""

        api_keys = model_config.get('api_keys', {}) if model_config else {}

        # Always fall back to environment variables to detect available providers
        for option in PROVIDER_OPTIONS:
                for env_key in option.env_keys:
                        api_keys.setdefault(env_key, os.getenv(env_key))

        return api_keys


def pick_provider_option(model_name: str | None, api_keys: dict[str, str | None]) -> ProviderOption | None:
        """Pick a provider based on explicit model name or available API keys."""

        if model_name:
                lowered_name = model_name.lower()
                for option in PROVIDER_OPTIONS:
                        if lowered_name.startswith(option.name) or lowered_name.startswith(option.name.split('-')[0]):
                                return option
                        if option.name == 'openai' and lowered_name.startswith('gpt'):
                                return option
                        if option.name == 'anthropic' and lowered_name.startswith('claude'):
                                return option
                        if option.name == 'google' and lowered_name.startswith('gemini'):
                                return option
                        if option.name == 'deepseek' and 'deepseek' in lowered_name:
                                return option
                        if option.name == 'groq' and ('groq' in lowered_name or 'llama' in lowered_name):
                                return option

        # No explicit model name: pick the first available provider
        for option in PROVIDER_OPTIONS:
                if option.is_available(api_keys):
                        return option

        return None


def resolve_model_name(model_name: str | None, provider: ProviderOption) -> str:
        """Resolve the model name, falling back to provider defaults."""

        if model_name:
                return model_name
        return provider.default_model


def get_llm(config: dict[str, Any]):
        """Get the language model based on config and available API keys."""

        model_config = config.get('model', {})
        requested_model = model_config.get('name')
        if not requested_model:
                requested_model = CONFIG.DEFAULT_LLM or None

        temperature = model_config.get('temperature', 0.0)
        api_keys = gather_api_keys(model_config)

        provider = pick_provider_option(requested_model, api_keys)
        if not provider:
                raise RuntimeError(
                        'No API keys found. Please update your config or set one of: '
                        'BROWSER_USE_API_KEY, OPENAI_API_KEY, AZURE_OPENAI_KEY, ANTHROPIC_API_KEY, GOOGLE_API_KEY, '
                        'DEEPSEEK_API_KEY, or GROQ_API_KEY.'
                )

        model_name = resolve_model_name(requested_model, provider)

        if not provider.is_available(api_keys):
                raise RuntimeError(
                        f'{provider.name} API key not found. Please update your config or set {" or ".join(provider.env_keys)} environment variable(s).'
                )

        api_key = next((api_keys.get(key) for key in provider.env_keys if api_keys.get(key)), None)

        return provider.create_client(model_name, temperature, api_key)


def is_scroll_at_bottom(widget: Any) -> bool:
        """Determine if a scrollable widget is currently at the bottom.

        Works with Textual scrollable widgets by checking common attributes.
        Returns True if we can't determine the scroll state to preserve auto-scroll.
        """

        try:
                max_y = getattr(widget, 'max_scroll_y', None)
                if max_y is None:
                        return True

                current_y = getattr(widget, 'scroll_y', None)
                if current_y is None:
                        scroll_offset = getattr(widget, 'scroll_offset', None)
                        current_y = getattr(scroll_offset, 'y', None) if scroll_offset is not None else None

                if current_y is None:
                        return True

                return current_y >= max_y
        except Exception:
                return True


class RichLogHandler(logging.Handler):
        """Custom logging handler that redirects logs to a RichLog-like widget."""

        def __init__(self, rich_log: Any):
                super().__init__()
                self.rich_log = rich_log

        def emit(self, record: logging.LogRecord) -> None:
                try:
                        msg = self.format(record)
                        at_bottom = is_scroll_at_bottom(self.rich_log)
                        self.rich_log.write(msg)
                        if at_bottom and hasattr(self.rich_log, 'scroll_end'):
                                try:
                                        self.rich_log.scroll_end(animate=False)
                                except Exception:
                                        pass
                except Exception:
                        self.handleError(record)


def pause_agent_run(agent: Any, output_log: Any | None = None) -> bool:
        """Pause the agent if it is currently running."""

        if agent and getattr(agent, 'running', False) and hasattr(agent, 'pause'):
                agent.pause()
                if output_log:
                        output_log.write('[orange]\n⏸️  Agent paused. Press Enter to resume.[/]')
                return True
        return False


def resume_agent_run(agent: Any, output_log: Any | None = None) -> bool:
        """Resume the agent if it is paused."""

        is_paused = bool(
                agent
                and hasattr(agent, 'state')
                and getattr(agent.state, 'paused', False)
                and hasattr(agent, 'resume')
        )

        if is_paused:
                agent.resume()
                if output_log:
                        output_log.write('\n[green]▶️  Agent resumed.[/]')
                return True
        return False

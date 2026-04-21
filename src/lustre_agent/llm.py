from langchain_anthropic import ChatAnthropic
from .config import settings


def get_llm(model: str | None = None) -> ChatAnthropic:
    return ChatAnthropic(
        model=model or settings.model,
        anthropic_api_key=settings.anthropic_api_key,
        anthropic_api_url=settings.anthropic_base_url,
        default_headers={
            "Authorization": f"Bearer {settings.anthropic_api_key}",
            "User-Agent": "claude-code/2.1.78",
        },
    )

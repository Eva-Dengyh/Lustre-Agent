from pydantic import Field
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    model_config = {"env_file": ".env", "populate_by_name": True}

    anthropic_api_key: str
    anthropic_base_url: str = "https://api.anthropic.com"
    model: str = Field("claude-sonnet-4-5", alias="lustre_model")


settings = Settings()

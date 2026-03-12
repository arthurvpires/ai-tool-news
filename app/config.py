from pydantic import Field
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Telegram
    TELEGRAM_BOT_TOKEN: str = "your_bot_token"
    TELEGRAM_CHAT_ID: str = "your_chat_id"

    # OpenAI or Groq
    OPENAI_API_KEY: str = "your_openai_api_key"
    GROQ_API_KEY: str = "your_groq_api_key"

    # App Config
    SCHEDULER_SEARCHING_TWEETS_MINUTES: int = Field(default=5)
    SCHEDULER_TELEGRAM_SENDING_MINUTES: int = Field(default=1)
    DATABASE_URL: str = Field(default="sqlite:///./ai_database.db")

    class Config:
        env_file = ".env"
        extra = "ignore"


settings = Settings()

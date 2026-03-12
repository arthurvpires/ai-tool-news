from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    # Telegram
    TELEGRAM_BOT_TOKEN: str = "your_bot_token"
    TELEGRAM_CHAT_ID: str = "your_chat_id"
    
    # OpenAI or Groq
    OPENAI_API_KEY: str = "your_openai_api_key"
    GROQ_API_KEY: str = "your_groq_api_key"
    
    # App Config
    SCHEDULER_INTERVAL_MINUTES: int = 5
    DATABASE_URL: str = "sqlite:///./ai_news.db"

    class Config:
        env_file = ".env"

settings = Settings()

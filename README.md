# AI News Scout Bot 🤖

An automated AI news aggregator that monitors top AI companies on Twitter/X, filters them using AI (Groq/OpenAI), and publishes the most relevant technical updates to a Telegram channel—including native video player support!

## Features
- **Twitter Tracking**: Monitors accounts like OpenAI, Claude, Google, and Perplexity via Nitter RSS (robust instance pool).
- **AI-Powered Filtering**: Uses a strict "Scout" prompt with Groq (Llama-3.1) or OpenAI to filter out marketing noise and only keep real technical/product updates.
- **Native Video Support**: High-quality video downloads using `yt-dlp` to ensure a real video player experience on Telegram.
- **Externalized Prompts**: System prompts are stored in `app/prompts.yaml` for easy tuning without code changes.
- **Auto-Scheduler**: Runs periodically (default: 5 min) using `APScheduler`.
- **Duplicate Prevention**: Uses a local SQLite database to ensure the same news is never posted twice.

## Getting Started

### 1. Prerequisites
- Python 3.10+
- A Telegram Bot Token (from [@BotFather](https://t.me/botfather))
- A Groq API Key (free/fast) or OpenAI API Key

### 2. Installation
```bash
# Clone the repository
# git clone <your-repo-url>
# cd ai-news-bot

# Create and activate virtual environment
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
```

### 3. Configuration
Copy `.env.example` to `.env` and fill in your keys:
```env
TELEGRAM_BOT_TOKEN=your_token_here
TELEGRAM_CHAT_ID=your_chat_id_here
GROQ_API_KEY=your_key_here
OPENAI_API_KEY=optional_key_here
```

### 4. Code Standards (Linting)
We use `ruff` to keep the code clean and standardized:
```bash
# Check for errors and linting issues
ruff check .

# Automatically fix and format the code
ruff format .
```

## Project Structure
- `app/collectors`: RSS fetching logic.
- `app/analyzer`: GPT/Groq analysis engine.
- `app/telegram`: Messaging and video download management.
- `app/prompts.yaml`: The "personality" and filtering rules of the bot.
- `newsletter.db`: SQLite database for processed IDs.


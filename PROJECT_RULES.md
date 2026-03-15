# 📜 Project Rules & Periodicity

This document defines the operational rules, scheduling (periodicity), and AI interaction guidelines for the AI Newsletter Bot.

> [!IMPORTANT]
> **AI Interaction Rule**: Whenever an AI assistant (coding agent) modifies this project, it **MUST** review this file. If the changes affect the scheduling, core logic, or project structure, the AI **MUST** update this file to reflect the new state.
> 
> **How to ensure AI Compliance**: AI agents typically scan the root directory for documentation files (`README.md`, `PROJECT_RULES.md`, etc.) at the start of a session. Keeping this file in the root directory ensures visibility.

## 🕒 Periodicity (Schedule)

All times are in **Brasília Time (BRT / UTC-3)**.

### Weekdays (Monday - Friday)
- **Regular Updates**: Sent between **08:00 and 19:00**.
- **Frequency**: Every few minutes (as per `SCHEDULER_TELEGRAM_SENDING_MINUTES`).
- **Logic**: Sends the most relevant "pending" news item one by one.

### Weekends (Saturday - Sunday)
- **Consolidated Summary**: Sent at **20:00**.
- **Regular Updates**: **PAUSED**. No individual news items are sent.
- **Content**: A single AI-generated summary of the most relevant news (score ≥ 7) from the previous 24 hours.

## 📡 Data Collection (Twitter/Nitter)

### 1. Strategy
- **Nitter RSS**: The system fetches news from X (Twitter) via Nitter RSS feeds to bypass API limits and stay undetected.
- **Source Config**: Sources are managed in `app/collectors/twitter_sources.json`.

### 2. Prioritization
- **Official Sources** (Companies/Founders) are processed **FIRST**.
- **Secondary Sources** (Influencers/Reporters) are processed **SECOND**.
- This ensures that if both an official account and an influencer post the same news, the system prioritizes the official data for the database and deduplication.

## 🤖 AI & Technical Rules

### 1. Centralized AI Client
- All LLM interactions (OpenAI/Groq) **MUST** use the `AIClient` class in `app/analyzer/ai_client.py`.
- Do **NOT** initialize `OpenAI()` or `Groq()` clients directly in other modules.
- Maintain the provider-based fallback loop.

### 2. News Prioritization
- **Official Sources** take precedence over **Secondary Sources** (influencers).
- If multiple sources report the same news, the system should favor the official announcement.

### 3. Deduplication
- Every new item must be compared against recent relevant items (last 5-10) using the `deduplicator` prompt.
- High confidence matches (> 0.7) should be skipped to avoid spam.

### 4. Code Quality
- All time-based logic must explicitly use the `BRT` timezone.
- Use structured parsing (Pydantic models) for all AI outputs.
- Keep `prompts.yaml` organized and modular.

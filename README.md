# Telegram Userbot

A Python system that simulates live human conversation in Telegram groups using multiple user accounts and AI-generated responses (Grok API).

## Features

- 🤖 Multiple user sessions acting as real participants
- 💬 AI-generated messages (Grok API) with per-session personas
- 🧠 Conversation context window (sliding history)
- ⌨️ Typing indicator simulation before each message
- ⏱️ Random delays between messages
- 🔁 Anti-consecutive: same account never sends two messages in a row
- 📨 Admin DM → new topic in group
- 💬 Real-user reply detection → bot replies in-thread
- 🎭 Optional media/emoji sending based on message sentiment

## Setup

### 1. Clone & install dependencies

```bash
git clone <repo>
cd telegram_userbot
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 2. Configure environment

```bash
cp .env.example .env
```

Edit `.env` with your:
- `TELEGRAM_API_ID` and `TELEGRAM_API_HASH` from [my.telegram.org/apps](https://my.telegram.org/apps)
- `GROK_API_KEY` from [x.ai](https://x.ai)

### 3. Configure sessions and groups

```bash
cp config.yaml.example config.yaml
```

Edit `config.yaml`:
- Add your StringSessions under `sessions`
- Set group IDs and prompts under `groups`
- Adjust `delay_min` / `delay_max` and `context_window`

### 4. Run

```bash
python main.py
```

## Architecture

```
main.py
├── SessionManager      — loads and authenticates all StringSessions
├── ContextManager      — sliding window of group chat history
├── AIClient            — Grok API wrapper
├── Orchestrator        — picks next bot, manages timing loop
│   ├── Bot (session 1)
│   ├── Bot (session 2)
│   └── Bot (session N)
├── AdminHandler        — listens to admin DMs → starts new topic
└── ReplyHandler        — detects real-user replies → routes to correct bot
```

## Project Structure

```
telegram_userbot/
├── src/
│   ├── __init__.py
│   ├── config.py           # Pydantic config models
│   ├── session_manager.py  # StringSession loading
│   ├── context_manager.py  # Conversation history
│   ├── ai_client.py        # Grok API integration
│   ├── orchestrator.py     # Bot selection & timing loop
│   ├── admin_handler.py    # Admin DM → group topic
│   ├── reply_handler.py    # Real-user reply routing
│   ├── media_sender.py     # Emoji / GIF sending
│   └── bot.py              # Single bot session logic
├── main.py
├── config.yaml.example
├── .env.example
├── requirements.txt
└── README.md
```

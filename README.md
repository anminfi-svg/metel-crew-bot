# METEL Crew Finder Bot

A Telegram bot to help people find a crew for METEL.

## Setup

### 1. Clone the repo and enter the directory

```bash
git clone <repo-url>
cd metel-crew-bot
```

### 2. Create and activate a virtual environment

```bash
python3 -m venv venv
source venv/bin/activate   # On Windows: venv\Scripts\activate
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

### 4. Configure the bot token

Copy `.env.example` to `.env` and paste your Telegram bot token:

```bash
cp .env.example .env
```

Then edit `.env`:

```
TELEGRAM_BOT_TOKEN=your_token_here
```

Get a token by talking to [@BotFather](https://t.me/BotFather) on Telegram and creating a new bot.

### 5. Run the bot

```bash
python bot.py
```

Open Telegram, find your bot, and send `/start`.

## Project structure

```
metel-crew-bot/
├── bot.py           # Main bot logic
├── requirements.txt
├── .env             # Your secret token (never commit this)
├── .env.example     # Safe template to share
└── .gitignore
```

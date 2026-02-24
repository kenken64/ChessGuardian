# ChessGuardian

AI-powered chess analysis app. Play moves on an interactive board and get position analysis from OpenAI.

## Features

- **Interactive chessboard** — drag-and-drop pieces with move validation, undo, and board flipping
- **AI analysis** — get best move suggestions and position evaluations powered by OpenAI (o4-mini)
- **Game persistence** — save, load, and delete games stored in SQLite, scoped per browser session
- **Mobile responsive** — fluid board layout that scales from desktop down to small phones
- **Dockerized** — production-ready with gunicorn, deployable to Railway
- **Telegram bot mode** — play against Stockfish via Telegram with board image updates

## Quick Start

### Prerequisites

- Python 3.10+
- An [OpenAI API key](https://platform.openai.com/api-keys)

### Local Setup

```bash
git clone https://github.com/kenken64/ChessGuardian.git
cd ChessGuardian

pip install -r requirements.txt

cp .env.example .env
# Edit .env and add your OPENAI_API_KEY

python app.py
```

Open http://localhost:5000

### Docker

```bash
docker build -t chessguardian .
docker run -p 8080:8080 \
  -e OPENAI_API_KEY=sk-your-key \
  -e SECRET_KEY=your-secret-key \
  -v chessguardian-data:/data \
  chessguardian
```

Open http://localhost:8080

### Telegram Bot (Standalone)

```bash
cp .env.example .env
# Add OPENAI_API_KEY and TELEGRAM_BOT_TOKEN

python telegram_bot.py
```

Telegram commands:
- `/start` or `/newgame` — start a new game, Stockfish (White) plays first
- `/move <move>` — play SAN (like `Nf6`) or UCI (like `e7e5`)
- `/board` — render current board as image
- `/analyze` — get AI analysis for current position
- `/resign` — resign current game
- `/help` — show command help

## Deploy to Railway

1. Fork or push this repo to GitHub
2. Create a new project in [Railway](https://railway.com) and connect the repo
3. Add environment variables in the Railway dashboard:
   - `OPENAI_API_KEY` — your OpenAI API key
   - `SECRET_KEY` — a random string (generate with `python -c "import secrets; print(secrets.token_hex(32))"`)
4. Add a **Volume** mounted at `/data` to persist the SQLite database across deploys
5. Deploy — Railway auto-detects the Dockerfile

## Environment Variables

| Variable | Required | Description |
|---|---|---|
| `OPENAI_API_KEY` | Yes | OpenAI API key for chess analysis |
| `SECRET_KEY` | Yes (production) | Flask session secret key |
| `TELEGRAM_BOT_TOKEN` | For bot mode | Telegram bot token from BotFather |
| `BOT_MODE` | No | If set (any non-empty value), Docker runs `telegram_bot.py` instead of gunicorn |
| `DATABASE_URL` | No | SQLAlchemy database URI (defaults to SQLite) |

### Docker Bot Mode

Run the Telegram bot in the same image by setting `BOT_MODE`:

```bash
docker run --rm \
  -e BOT_MODE=telegram \
  -e OPENAI_API_KEY=sk-your-key \
  -e TELEGRAM_BOT_TOKEN=123456:ABCDEF \
  chessguardian
```

## Project Structure

```
ChessGuardian/
├── app.py              # Flask app, API endpoints
├── telegram_bot.py     # Standalone Telegram bot (async python-telegram-bot)
├── models.py           # SQLAlchemy Game model
├── requirements.txt    # Python dependencies
├── Dockerfile          # Production Docker image
├── .env.example        # Environment variable template
├── templates/
│   └── index.html      # Main page
└── static/
    ├── css/
    │   └── style.css   # Styles + responsive layout
    └── js/
        └── game.js     # Board logic, AI calls, game persistence
```

## Tech Stack

- **Backend** — Flask, SQLAlchemy, gunicorn
- **Frontend** — jQuery, [chessboard.js](https://chessboardjs.com/), [chess.js](https://github.com/jhlywa/chess.js)
- **AI** — OpenAI API (o4-mini)
- **Database** — SQLite

## License

MIT

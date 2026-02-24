import asyncio
import json
import logging
import os
from dataclasses import dataclass, field
from io import BytesIO
from typing import Dict, Optional

import cairosvg
import chess
import chess.svg
from dotenv import load_dotenv
from openai import OpenAI
from stockfish import Stockfish as StockfishEngine
from telegram import InputFile, Update
from telegram.ext import Application, CommandHandler, ContextTypes

load_dotenv()

logging.basicConfig(
    format="[%(asctime)s] %(levelname)s %(name)s: %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger("chessguardian.telegram")

SYSTEM_PROMPT = """You are an expert chess analyst. When given a chess position in FEN notation and the move history, respond with ONLY a valid JSON object (no markdown, no extra text) with these exact keys:

{
  "bestMove": "Piece from [square] to [square] (notation)",
  "explanation": "2-3 sentence explanation of why this move is best",
  "evaluation": "Short position assessment, e.g. White is slightly better",
  "winChance": 55
}

Rules:
- bestMove: Include piece name, origin square, destination square, and standard notation. Examples: "Knight from g1 to f3 (Nf3)", "Pawn from e2 to e4 (e4)", "King castles kingside (O-O)"
- winChance: Integer 0-100 representing White's winning probability. 50 = equal, 100 = White winning, 0 = Black winning.
- Always recommend a move from the legal moves list provided.
- Return ONLY the JSON object, nothing else."""

STOCKFISH_PATH = os.getenv(
    "STOCKFISH_PATH",
    "/usr/games/stockfish" if os.path.exists("/usr/games/stockfish") else "/opt/homebrew/bin/stockfish",
)
STOCKFISH_SKILL = int(os.getenv("STOCKFISH_SKILL", "10"))
STOCKFISH_DEPTH = int(os.getenv("STOCKFISH_DEPTH", "12"))
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))


@dataclass
class ChatGame:
    board: chess.Board = field(default_factory=chess.Board)
    history: list[str] = field(default_factory=list)
    status: str = "active"
    result: Optional[str] = None


# In-memory chat state keyed by Telegram chat_id.
GAMES: Dict[int, ChatGame] = {}


def get_stockfish() -> StockfishEngine:
    """Create a new Stockfish instance for one move calculation."""
    sf = StockfishEngine(path=STOCKFISH_PATH, depth=STOCKFISH_DEPTH)
    sf.update_engine_parameters({"Skill Level": STOCKFISH_SKILL})
    return sf


def stockfish_best_move(board: chess.Board) -> tuple[Optional[chess.Move], Optional[str]]:
    """Return Stockfish best move as (move, SAN)."""
    sf = get_stockfish()
    sf.set_fen_position(board.fen())
    best_uci = sf.get_best_move()
    if not best_uci:
        return None, None

    move = chess.Move.from_uci(best_uci)
    if move not in board.legal_moves:
        return None, None
    return move, board.san(move)


def parse_user_move(board: chess.Board, move_text: str) -> Optional[chess.Move]:
    """Parse SAN first, then UCI, returning a legal move or None."""
    move_text = move_text.strip()
    if not move_text:
        return None

    try:
        move = board.parse_san(move_text)
        if move in board.legal_moves:
            return move
    except (chess.InvalidMoveError, chess.IllegalMoveError, chess.AmbiguousMoveError):
        pass

    try:
        move = chess.Move.from_uci(move_text)
        if move in board.legal_moves:
            return move
    except (ValueError, chess.InvalidMoveError):
        pass

    return None


def check_game_over(board: chess.Board) -> tuple[bool, str, int]:
    """Return (is_over, status_text, white_win_chance)."""
    if board.is_checkmate():
        winner = "Black" if board.turn == chess.WHITE else "White"
        win_chance = 100 if winner == "White" else 0
        return True, f"Checkmate. {winner} wins ({board.result()}).", win_chance

    if board.is_stalemate():
        return True, f"Stalemate. Draw ({board.result()}).", 50

    if board.is_insufficient_material():
        return True, f"Draw by insufficient material ({board.result()}).", 50

    if board.can_claim_fifty_moves() or board.can_claim_threefold_repetition():
        return True, f"Draw can be claimed ({board.result(claim_draw=True)}).", 50

    return False, "", 50


def analyze_position(board: chess.Board, move_history: list[str]) -> dict:
    """Analyze board with OpenAI and return normalized analysis fields."""
    side_to_move = "White" if board.turn == chess.WHITE else "Black"
    legal_moves = " ".join(board.san(m) for m in board.legal_moves)

    user_message = (
        f"Position (FEN): {board.fen()}\n"
        f"It is {side_to_move}'s turn to move. Suggest the best move for {side_to_move}."
    )
    user_message += f"\nLegal moves: {legal_moves}"
    user_message += "\nIMPORTANT: You MUST recommend one of the legal moves listed above."
    if move_history:
        user_message += f"\nMove history: {' '.join(move_history)}"

    response = client.chat.completions.create(
        model=OPENAI_MODEL,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_message},
        ],
        max_tokens=500,
        response_format={"type": "json_object"},
    )

    raw = response.choices[0].message.content.strip()
    parsed = json.loads(raw)

    return {
        "bestMove": parsed.get("bestMove", ""),
        "explanation": parsed.get("explanation", ""),
        "evaluation": parsed.get("evaluation", ""),
        "winChance": max(0, min(100, int(parsed.get("winChance", 50)))),
    }


def render_board_png(board: chess.Board) -> BytesIO:
    """Render a PNG chessboard image using python-chess SVG + cairosvg."""
    last_move = board.move_stack[-1] if board.move_stack else None
    svg = chess.svg.board(board=board, size=720, lastmove=last_move)
    png_bytes = cairosvg.svg2png(bytestring=svg.encode("utf-8"))

    image = BytesIO(png_bytes)
    image.name = "board.png"
    image.seek(0)
    return image


def format_analysis(analysis: dict) -> str:
    return (
        "AI analysis\n"
        f"Best move: {analysis.get('bestMove', 'N/A')}\n"
        f"Evaluation: {analysis.get('evaluation', 'N/A')}\n"
        f"Win chance (White): {analysis.get('winChance', 50)}%"
    )


async def send_board(update: Update, board: chess.Board, caption: str) -> None:
    """Send board PNG as Telegram photo."""
    image = await asyncio.to_thread(render_board_png, board)
    await update.effective_chat.send_photo(photo=InputFile(image), caption=caption)


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = (
        "ChessGuardian Telegram Bot commands:\n"
        "/start or /newgame - Start a game (Stockfish plays White first)\n"
        "/move <move> - Play your move (SAN like Nf6 or UCI like e7e5)\n"
        "/board - Show current board\n"
        "/analyze - Analyze the current position\n"
        "/resign - Resign the current game\n"
        "/help - Show this help"
    )
    await update.message.reply_text(text)


async def cmd_newgame(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    game = ChatGame()

    try:
        sf_move, sf_san = await asyncio.to_thread(stockfish_best_move, game.board)
        if not sf_move:
            await update.message.reply_text("Could not start game: Stockfish failed to return a move.")
            return

        game.board.push(sf_move)
        game.history.append(sf_san)

        analysis = await asyncio.to_thread(analyze_position, game.board, game.history)
        GAMES[chat_id] = game

        caption = (
            f"New game started. Stockfish (White) played: {sf_san}\n\n"
            f"{format_analysis(analysis)}"
        )
        await send_board(update, game.board, caption)
    except Exception as exc:
        logger.exception("Failed to start new game")
        await update.message.reply_text(f"Failed to start game: {exc}")


async def cmd_move(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    game = GAMES.get(chat_id)
    if not game:
        await update.message.reply_text("No active game. Use /newgame to start one.")
        return

    if game.status != "active":
        await update.message.reply_text("Current game is over. Use /newgame to start a fresh game.")
        return

    if not context.args:
        await update.message.reply_text("Usage: /move <move> (example: /move e5 or /move e7e5)")
        return

    move_text = " ".join(context.args)
    move = parse_user_move(game.board, move_text)
    if not move:
        legal = ", ".join(game.board.san(m) for m in game.board.legal_moves)
        await update.message.reply_text(f"Illegal move: {move_text}\nLegal moves: {legal}")
        return

    human_san = game.board.san(move)
    game.board.push(move)
    game.history.append(human_san)

    over, status_text, win_chance = check_game_over(game.board)
    if over:
        game.status = "game_over"
        game.result = game.board.result(claim_draw=True)
        terminal_analysis = {
            "bestMove": "N/A",
            "evaluation": status_text,
            "winChance": win_chance,
        }
        caption = (
            f"You played: {human_san}\n"
            "Stockfish reply: N/A (game over)\n\n"
            f"{format_analysis(terminal_analysis)}"
        )
        await send_board(update, game.board, caption)
        return

    try:
        sf_move, sf_san = await asyncio.to_thread(stockfish_best_move, game.board)
        if not sf_move:
            await update.message.reply_text("Stockfish could not find a reply move.")
            return

        game.board.push(sf_move)
        game.history.append(sf_san)

        over, status_text, win_chance = check_game_over(game.board)
        if over:
            game.status = "game_over"
            game.result = game.board.result(claim_draw=True)
            analysis = {
                "bestMove": "N/A",
                "evaluation": status_text,
                "winChance": win_chance,
            }
        else:
            analysis = await asyncio.to_thread(analyze_position, game.board, game.history)

        caption = (
            f"You played: {human_san}\n"
            f"Stockfish played: {sf_san}\n\n"
            f"{format_analysis(analysis)}"
        )
        await send_board(update, game.board, caption)
    except Exception as exc:
        logger.exception("Move handling failed")
        await update.message.reply_text(f"Move failed: {exc}")


async def cmd_board(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    game = GAMES.get(chat_id)
    if not game:
        await update.message.reply_text("No active game. Use /newgame to start one.")
        return

    move_text = game.history[-1] if game.history else "None"
    status = "Active" if game.status == "active" else f"Over ({game.result or game.status})"
    caption = f"Current board\nLast move: {move_text}\nStatus: {status}"

    try:
        await send_board(update, game.board, caption)
    except Exception as exc:
        logger.exception("Board rendering failed")
        await update.message.reply_text(f"Could not render board: {exc}")


async def cmd_analyze(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    game = GAMES.get(chat_id)
    if not game:
        await update.message.reply_text("No active game. Use /newgame to start one.")
        return

    over, status_text, win_chance = check_game_over(game.board)
    if over:
        analysis = {
            "bestMove": "N/A",
            "evaluation": status_text,
            "winChance": win_chance,
        }
        await update.message.reply_text(format_analysis(analysis))
        return

    try:
        analysis = await asyncio.to_thread(analyze_position, game.board, game.history)
        await update.message.reply_text(format_analysis(analysis))
    except Exception as exc:
        logger.exception("Analysis failed")
        await update.message.reply_text(f"Analysis failed: {exc}")


async def cmd_resign(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    game = GAMES.get(chat_id)
    if not game:
        await update.message.reply_text("No active game. Use /newgame to start one.")
        return

    if game.status != "active":
        await update.message.reply_text("Game is already over. Use /newgame to start another game.")
        return

    game.status = "resigned"
    game.result = "1-0"
    await update.message.reply_text("You resigned. Stockfish (White) wins. Use /newgame for a rematch.")


async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.exception("Unhandled telegram bot error", exc_info=context.error)
    if isinstance(update, Update) and update.effective_message:
        await update.effective_message.reply_text("Unexpected error occurred. Please try again.")


def main() -> None:
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is required")

    application = Application.builder().token(token).build()

    application.add_handler(CommandHandler(["start", "newgame"], cmd_newgame))
    application.add_handler(CommandHandler("move", cmd_move))
    application.add_handler(CommandHandler("resign", cmd_resign))
    application.add_handler(CommandHandler("board", cmd_board))
    application.add_handler(CommandHandler("analyze", cmd_analyze))
    application.add_handler(CommandHandler("help", cmd_help))

    application.add_error_handler(on_error)

    logger.info("Starting ChessGuardian Telegram bot")
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()

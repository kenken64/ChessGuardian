import os
import json
import re
import uuid
import logging
from logging.handlers import RotatingFileHandler
from flask import Flask, render_template, request, jsonify, session, Response
from dotenv import load_dotenv
from openai import OpenAI
import chess
from stockfish import Stockfish as StockfishEngine
from models import db, Game

load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "dev-secret-key-change-in-production")

# --- Logging setup ---
log_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs")
os.makedirs(log_dir, exist_ok=True)
file_handler = RotatingFileHandler(
    os.path.join(log_dir, "chessguardian.log"),
    maxBytes=5 * 1024 * 1024,  # 5 MB
    backupCount=3,
)
file_handler.setFormatter(logging.Formatter(
    "[%(asctime)s] %(levelname)s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
))
file_handler.setLevel(logging.DEBUG)
app.logger.addHandler(file_handler)
app.logger.setLevel(logging.DEBUG)

if os.getenv("DATABASE_URL"):
    app.config["SQLALCHEMY_DATABASE_URI"] = os.getenv("DATABASE_URL")
elif os.getenv("SQLITE_PATH"):
    db_path = os.getenv("SQLITE_PATH")
    os.makedirs(os.path.dirname(os.path.abspath(db_path)), exist_ok=True)
    app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///" + os.path.abspath(db_path)
elif os.getenv("RAILWAY_ENVIRONMENT"):
    os.makedirs("/data", exist_ok=True)
    app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:////data/chessguardian.db"
else:
    app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///chessguardian.db"

db.init_app(app)
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# --- Stockfish setup ---
STOCKFISH_PATH = os.getenv("STOCKFISH_PATH", "/usr/games/stockfish" if os.path.exists("/usr/games/stockfish") else "/opt/homebrew/bin/stockfish")
STOCKFISH_SKILL = int(os.getenv("STOCKFISH_SKILL", "10"))  # 0-20, default 10 (~1500 Elo)
STOCKFISH_DEPTH = int(os.getenv("STOCKFISH_DEPTH", "12"))

def get_stockfish():
    """Create a fresh Stockfish instance."""
    sf = StockfishEngine(path=STOCKFISH_PATH, depth=STOCKFISH_DEPTH)
    sf.update_engine_parameters({"Skill Level": STOCKFISH_SKILL})
    return sf

with app.app_context():
    db.create_all()
    # Migrate: add name column if missing from older DB
    with db.engine.connect() as conn:
        try:
            conn.execute(db.text("ALTER TABLE game ADD COLUMN name VARCHAR(100) DEFAULT ''"))
            conn.commit()
        except Exception:
            pass


@app.before_request
def ensure_session_id():
    if "session_id" not in session:
        session["session_id"] = str(uuid.uuid4())

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


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/move", methods=["POST"])
def get_ai_move():
    """Use Stockfish to pick the best move for the current position."""
    data = request.get_json()
    if not data:
        return jsonify({"error": "No data provided"}), 400

    fen = data.get("fen")
    if not fen:
        return jsonify({"error": "FEN is required"}), 400

    try:
        board = chess.Board(fen)
    except ValueError:
        return jsonify({"error": "Invalid FEN position"}), 400

    if board.is_game_over():
        return jsonify({"error": "Game is already over"}), 400

    try:
        sf = get_stockfish()
        sf.set_fen_position(fen)
        best_move_uci = sf.get_best_move()

        if not best_move_uci:
            return jsonify({"error": "Stockfish could not find a move"}), 500

        # Convert UCI to SAN for display
        move = chess.Move.from_uci(best_move_uci)
        san = board.san(move)

        app.logger.info("Stockfish move: %s (%s) for FEN: %s", san, best_move_uci, fen)

        return jsonify({
            "move": best_move_uci,
            "san": san,
        })
    except Exception as e:
        app.logger.error("Stockfish error: %s", str(e), exc_info=True)
        return jsonify({"error": f"Stockfish error: {str(e)}"}), 500


@app.route("/api/analyze", methods=["POST"])
def analyze():
    data = request.get_json()
    if not data:
        return jsonify({"error": "No data provided"}), 400

    fen = data.get("fen")
    last_move = data.get("last_move", "")
    move_history = data.get("move_history", "")

    if not fen:
        return jsonify({"error": "FEN is required"}), 400

    # Validate FEN with python-chess
    try:
        board = chess.Board(fen)
    except ValueError:
        return jsonify({"error": "Invalid FEN position"}), 400

    # Check game-over states
    if board.is_game_over():
        result = board.result()
        if board.is_checkmate():
            winner = "Black" if board.turn == chess.WHITE else "White"
            win_chance = 100 if winner == "White" else 0
            return jsonify({
                "analysis": f"**Checkmate!** {winner} wins.",
                "game_over": True,
                "status": f"Checkmate - {winner} wins ({result})",
                "winChance": win_chance
            })
        if board.is_stalemate():
            return jsonify({
                "analysis": "**Stalemate!** The game is a draw.",
                "game_over": True,
                "status": f"Stalemate - Draw ({result})",
                "winChance": 50
            })
        if board.is_insufficient_material():
            return jsonify({
                "analysis": "**Draw by insufficient material.**",
                "game_over": True,
                "status": f"Insufficient material - Draw ({result})",
                "winChance": 50
            })
        return jsonify({
            "analysis": f"**Game over.** Result: {result}",
            "game_over": True,
            "status": f"Game over ({result})",
            "winChance": 50
        })

    # Build the prompt
    side_to_move = "White" if board.turn == chess.WHITE else "Black"
    legal_moves = " ".join(board.san(m) for m in board.legal_moves)
    user_message = f"Position (FEN): {fen}\nIt is {side_to_move}'s turn to move. Suggest the best move for {side_to_move}."
    user_message += f"\nLegal moves: {legal_moves}"
    user_message += "\nIMPORTANT: You MUST recommend one of the legal moves listed above. Do not suggest any move that is not in this list."
    if move_history:
        user_message += f"\nMove history: {move_history}"
    if last_move:
        user_message += f"\nLast move played: {last_move}"

    app.logger.info("=== OpenAI Request ===")
    app.logger.info("FEN: %s", fen)
    app.logger.info("Side to move: %s", side_to_move)
    app.logger.info("User message:\n%s", user_message)

    # Call OpenAI
    try:
        response = client.chat.completions.create(
            model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_message}
            ],
            max_tokens=500,
            response_format={"type": "json_object"},
        )
        raw = response.choices[0].message.content.strip()

        app.logger.info("=== OpenAI Response ===")
        app.logger.info("Model: %s", response.model)
        app.logger.info("Usage: prompt=%s, completion=%s, total=%s",
                        response.usage.prompt_tokens,
                        response.usage.completion_tokens,
                        response.usage.total_tokens)
        app.logger.info("Raw response:\n%s", raw)

        if not raw:
            return jsonify({"error": "AI returned empty response"}), 500

        result = json.loads(raw)
        best_move = result.get("bestMove", "")
        explanation = result.get("explanation", "")
        evaluation = result.get("evaluation", "")
        win_chance = result.get("winChance", 50)
        win_chance = max(0, min(100, int(win_chance)))

        analysis = f"**Best Move:** {best_move}\n\n**Explanation:** {explanation}\n\n**Evaluation:** {evaluation}"

    except json.JSONDecodeError as e:
        app.logger.error("JSON parse error: %s\nRaw: %s", str(e), raw, exc_info=True)
        return jsonify({"error": "AI returned invalid JSON"}), 500
    except Exception as e:
        app.logger.error("OpenAI API error: %s", str(e), exc_info=True)
        return jsonify({"error": f"AI analysis failed: {str(e)}"}), 500

    app.logger.info("Parsed — bestMove: %s, winChance: %d", best_move, win_chance)

    return jsonify({
        "analysis": analysis,
        "bestMove": best_move,
        "explanation": explanation,
        "evaluation": evaluation,
        "game_over": False,
        "status": "ok",
        "winChance": win_chance
    })


@app.route("/api/games/save", methods=["POST"])
def save_game():
    data = request.get_json()
    if not data:
        return jsonify({"error": "No data provided"}), 400

    history = data.get("history", [])
    if not history:
        return jsonify({"error": "No moves to save"}), 400

    name = data.get("name", "").strip()
    if not name:
        return jsonify({"error": "Game name is required"}), 400

    now = data.get("date", "")
    moves = data.get("moves", "")
    move_count = data.get("moveCount", len(history))
    history_json = json.dumps(history)

    # Overwrite if id provided and belongs to this session
    game_id = data.get("id")
    if game_id:
        game = Game.query.filter_by(id=game_id, session_id=session["session_id"]).first()
        if game:
            game.name = name
            game.date = now
            game.moves = moves
            game.history = history_json
            game.move_count = move_count
            db.session.commit()
            return jsonify(game.to_dict())

    game = Game(
        session_id=session["session_id"],
        name=name,
        date=now,
        moves=moves,
        history=history_json,
        move_count=move_count,
    )
    db.session.add(game)
    db.session.commit()

    return jsonify(game.to_dict()), 201


@app.route("/api/games", methods=["GET"])
def list_games():
    games = Game.query.filter_by(session_id=session["session_id"]).order_by(Game.id).all()
    return jsonify([g.to_dict() for g in games])


@app.route("/api/games/<int:game_id>", methods=["DELETE"])
def delete_game(game_id):
    game = Game.query.filter_by(id=game_id, session_id=session["session_id"]).first()
    if not game:
        return jsonify({"error": "Game not found"}), 404
    db.session.delete(game)
    db.session.commit()
    return jsonify({"ok": True})


@app.route("/api/games/<int:game_id>/export", methods=["GET"])
def export_game(game_id):
    game = Game.query.filter_by(id=game_id, session_id=session["session_id"]).first()
    if not game:
        return jsonify({"error": "Game not found"}), 404

    data = game.to_dict()
    del data["id"]

    filename = (game.name or "game") + ".json"
    return Response(
        json.dumps(data, indent=2),
        mimetype="application/json",
        headers={"Content-Disposition": f"attachment; filename=\"{filename}\""},
    )


@app.route("/api/games/import", methods=["POST"])
def import_game():
    if "file" not in request.files:
        return jsonify({"error": "No file provided"}), 400

    f = request.files["file"]
    try:
        data = json.loads(f.read())
    except (json.JSONDecodeError, UnicodeDecodeError):
        return jsonify({"error": "Invalid JSON file"}), 400

    # Validate required fields
    name = data.get("name", "").strip()
    if not name:
        return jsonify({"error": "Missing game name"}), 400

    history = data.get("history")
    if not isinstance(history, list) or len(history) == 0:
        return jsonify({"error": "Missing or empty history"}), 400

    game = Game(
        session_id=session["session_id"],
        name=name,
        date=data.get("date", ""),
        moves=data.get("moves", ""),
        history=json.dumps(history),
        move_count=data.get("moveCount", len(history)),
    )
    db.session.add(game)
    db.session.commit()

    return jsonify(game.to_dict()), 201


if __name__ == "__main__":
    app.run(debug=True, port=5000)

import os
import json
import uuid
from flask import Flask, render_template, request, jsonify, session
from dotenv import load_dotenv
from openai import OpenAI
import chess
from models import db, Game

load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "dev-secret-key-change-in-production")

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

SYSTEM_PROMPT = """You are an expert chess analyst. When given a chess position in FEN notation and the move history, provide:

1. **Best Move**: The best move for the side whose turn it is (specified in the user message). Always include the piece name, the origin square, and the destination square. Format: "Piece from [square] to [square]" followed by the standard notation in parentheses. Examples: "Knight from g1 to f3 (Nf3)", "Pawn from e2 to e4 (e4)", "King castles kingside (O-O)", "Pawn from d5 captures on e6 (dxe6)". Always recommend a move for the correct side.
2. **Explanation**: A brief, clear explanation of why this move is best (2-3 sentences max).
3. **Position Evaluation**: A short assessment of the position (e.g., "White is slightly better", "Equal position", "Black has a winning advantage").

Keep your response concise and structured exactly as above. Do not use any other format."""


@app.route("/")
def index():
    return render_template("index.html")


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
            return jsonify({
                "analysis": f"**Checkmate!** {winner} wins.",
                "game_over": True,
                "status": f"Checkmate - {winner} wins ({result})"
            })
        if board.is_stalemate():
            return jsonify({
                "analysis": "**Stalemate!** The game is a draw.",
                "game_over": True,
                "status": f"Stalemate - Draw ({result})"
            })
        if board.is_insufficient_material():
            return jsonify({
                "analysis": "**Draw by insufficient material.**",
                "game_over": True,
                "status": f"Insufficient material - Draw ({result})"
            })
        return jsonify({
            "analysis": f"**Game over.** Result: {result}",
            "game_over": True,
            "status": f"Game over ({result})"
        })

    # Build the prompt
    side_to_move = "White" if board.turn == chess.WHITE else "Black"
    user_message = f"Position (FEN): {fen}\nIt is {side_to_move}'s turn to move. Suggest the best move for {side_to_move}."
    if move_history:
        user_message += f"\nMove history: {move_history}"
    if last_move:
        user_message += f"\nLast move played: {last_move}"

    # Call OpenAI
    try:
        response = client.chat.completions.create(
            model="gpt-5-2025-08-07",
            messages=[
                {"role": "developer", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_message}
            ],
            max_completion_tokens=4000
        )
        analysis = response.choices[0].message.content
        if not analysis:
            analysis = "Analysis completed but no output was returned. Please try again."
    except Exception as e:
        return jsonify({"error": f"AI analysis failed: {str(e)}"}), 500

    return jsonify({
        "analysis": analysis,
        "game_over": False,
        "status": "ok"
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


if __name__ == "__main__":
    app.run(debug=True, port=5000)

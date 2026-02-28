import json
import chess
from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()


# Material values for win chance estimation
_PIECE_VALUES = {
    chess.PAWN: 1, chess.KNIGHT: 3, chess.BISHOP: 3.25,
    chess.ROOK: 5, chess.QUEEN: 9,
}

def _estimate_win_chance(fen):
    """Estimate White's win chance (0-100) from material balance.
    Uses a sigmoid-like mapping: +3 pawns advantage ≈ 75%, +9 ≈ 95%."""
    try:
        board = chess.Board(fen)
    except Exception:
        return 50

    if board.is_checkmate():
        return 0 if board.turn == chess.WHITE else 100
    if board.is_game_over():
        return 50

    white_material = sum(
        _PIECE_VALUES.get(p.piece_type, 0)
        for p in board.piece_map().values() if p.color == chess.WHITE
    )
    black_material = sum(
        _PIECE_VALUES.get(p.piece_type, 0)
        for p in board.piece_map().values() if p.color == chess.BLACK
    )
    diff = white_material - black_material
    # Sigmoid: 50 + 50 * tanh(diff / 6)
    import math
    win_chance = 50 + 50 * math.tanh(diff / 6)
    return max(0, min(100, round(win_chance)))


class LiveGame(db.Model):
    id = db.Column(db.String(8), primary_key=True)
    fen = db.Column(db.String(100), nullable=False, default='rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1')
    history = db.Column(db.Text, nullable=False, default='[]')
    status = db.Column(db.String(20), nullable=False, default='active')
    result = db.Column(db.String(10), nullable=True)
    mode = db.Column(db.String(10), nullable=False, default='ai')
    white_player = db.Column(db.String(20), nullable=True)
    black_player = db.Column(db.String(20), nullable=True)
    created_at = db.Column(db.DateTime, default=db.func.now())
    updated_at = db.Column(db.DateTime, default=db.func.now(), onupdate=db.func.now())

    def to_dict(self):
        history = json.loads(self.history)
        # Determine turn from FEN (more reliable than history length)
        try:
            board = chess.Board(self.fen)
            turn = "white" if board.turn == chess.WHITE else "black"
        except Exception:
            turn = "white" if len(history) % 2 == 0 else "black"

        win_chance = _estimate_win_chance(self.fen)

        d = {
            "id": self.id,
            "fen": self.fen,
            "history": history,
            "status": self.status,
            "result": self.result,
            "gameOver": self.status != 'active',
            "mode": self.mode,
            "turn": turn,
            "winChance": win_chance,
        }
        if self.mode == 'pvp':
            d["whitePlayer"] = self.white_player
            d["blackPlayer"] = self.black_player
        return d


class Game(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    session_id = db.Column(db.String(36), nullable=False, index=True)
    name = db.Column(db.String(100), nullable=False, default="")
    date = db.Column(db.String(50), nullable=False)
    moves = db.Column(db.Text, nullable=False)
    history = db.Column(db.Text, nullable=False)  # JSON array of move strings
    move_count = db.Column(db.Integer, nullable=False)

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "date": self.date,
            "moves": self.moves,
            "history": json.loads(self.history),
            "moveCount": self.move_count,
        }

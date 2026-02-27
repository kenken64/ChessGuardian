import json
from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()


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
        turn = "white" if len(history) % 2 == 0 else "black"
        d = {
            "id": self.id,
            "fen": self.fen,
            "history": history,
            "status": self.status,
            "result": self.result,
            "gameOver": self.status != 'active',
            "mode": self.mode,
            "turn": turn,
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

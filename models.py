import json
from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()


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

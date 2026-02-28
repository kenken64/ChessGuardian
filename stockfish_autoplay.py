#!/usr/bin/env python3
"""Stockfish vs Stockfish autoplay for ChessGuardian live games.

Usage: python3 stockfish_autoplay.py <game_id> [--depth 20] [--delay 5] [--url https://...] [--notify]
"""

import argparse
import json
import math
import subprocess
import sys
import time

import chess
import chess.engine
import requests

DEFAULT_URL = "https://chessguardian-production.up.railway.app"
DEFAULT_DEPTH = 20
DEFAULT_DELAY = 5  # seconds between moves (enough to see turn changes)


def get_stockfish():
    """Find and return a Stockfish engine instance."""
    paths = ["/usr/games/stockfish", "/usr/local/bin/stockfish", "stockfish"]
    for path in paths:
        try:
            engine = chess.engine.SimpleEngine.popen_uci(path)
            print(f"✅ Stockfish loaded: {path}")
            return engine
        except Exception:
            continue
    print("❌ Stockfish not found!")
    sys.exit(1)


def get_game_state(base_url, game_id):
    """Poll the live game state."""
    resp = requests.get(f"{base_url}/api/live/{game_id}")
    resp.raise_for_status()
    return resp.json()


def make_move(base_url, game_id, move_san):
    """Submit a move to the live game."""
    resp = requests.post(
        f"{base_url}/api/live/{game_id}/move",
        json={"move": move_san},
    )
    return resp.json()


def find_best_move(engine, fen, depth):
    """Use Stockfish to find the best move."""
    board = chess.Board(fen)
    result = engine.play(board, chess.engine.Limit(depth=depth))
    san = board.san(result.move)
    info = engine.analyse(board, chess.engine.Limit(depth=depth))
    score = info.get("score")
    eval_str = ""
    eval_cp = 0
    if score:
        pov = score.white()
        if pov.is_mate():
            eval_str = f"M{pov.mate()}"
            eval_cp = 10000 if pov.mate() > 0 else -10000
        else:
            eval_cp = pov.score()
            eval_str = f"{eval_cp / 100:+.2f}"
    return san, result.move.uci(), eval_str, eval_cp


def eval_to_win_pct(cp):
    """Convert centipawn eval to win% for White using sigmoid."""
    return max(0, min(100, round(50 + 50 * math.tanh(cp / 600))))


# --- Notification callback (optional) ---
_notify_fn = None

def set_notify(fn):
    global _notify_fn
    _notify_fn = fn

def notify(msg):
    print(msg)
    if _notify_fn:
        try:
            _notify_fn(msg)
        except Exception as e:
            print(f"  ⚠️ Notify error: {e}")


def main():
    parser = argparse.ArgumentParser(description="Stockfish autoplay for ChessGuardian")
    parser.add_argument("game_id", help="Live game ID")
    parser.add_argument("--depth", type=int, default=DEFAULT_DEPTH, help=f"Stockfish depth (default: {DEFAULT_DEPTH})")
    parser.add_argument("--delay", type=float, default=DEFAULT_DELAY, help=f"Delay between moves in seconds (default: {DEFAULT_DELAY})")
    parser.add_argument("--url", default=DEFAULT_URL, help=f"ChessGuardian base URL (default: {DEFAULT_URL})")
    parser.add_argument("--max-moves", type=int, default=200, help="Max moves before stopping (default: 200)")
    args = parser.parse_args()

    print(f"♟️  Stockfish Autoplay — Game {args.game_id}")
    print(f"   URL: {args.url}")
    print(f"   Depth: {args.depth} | Delay: {args.delay}s | Max moves: {args.max_moves}")
    print(f"   Live: {args.url}/live/{args.game_id}")
    print()

    engine = get_stockfish()

    try:
        move_count = 0
        while move_count < args.max_moves:
            state = get_game_state(args.url, args.game_id)

            if state.get("error"):
                notify(f"❌ Error: {state['error']}")
                break

            if state.get("gameOver"):
                notify(f"\n🏁 Game Over! Status: {state['status']} | Result: {state.get('result', 'N/A')}")
                notify(f"   Total moves: {len(state['history'])}")
                break

            fen = state["fen"]
            turn = state.get("turn", "unknown")
            history = state.get("history", [])

            if turn != "black":
                time.sleep(1)
                continue

            san, uci, eval_str, eval_cp = find_best_move(engine, fen, args.depth)
            move_num = len(history) // 2 + 1
            win_pct = eval_to_win_pct(-eval_cp)  # From Black's perspective

            move_msg = f"♟️ {move_num}... {san}  (eval: {eval_str} | Black win: {100 - eval_to_win_pct(eval_cp)}%)"
            notify(move_msg)

            result = make_move(args.url, args.game_id, san)

            if result.get("error"):
                notify(f"  ❌ Move rejected: {result['error']}")
                result = make_move(args.url, args.game_id, uci)
                if result.get("error"):
                    notify(f"  ❌ Still rejected: {result['error']}")
                    break

            sf_move = result.get("stockfishMove")
            if sf_move:
                new_history = result.get("history", [])
                move_num_w = len(new_history) // 2 + 1
                sf_msg = f"♙ {move_num_w}. {sf_move}  (Server Stockfish)"
                notify(sf_msg)

            if result.get("gameOver"):
                status = result.get('status', 'unknown')
                res = result.get('result', 'N/A')
                if status == 'checkmate':
                    winner = "White" if res == "1-0" else "Black"
                    notify(f"\n🏆 CHECKMATE! {winner} wins!")
                else:
                    notify(f"\n🏁 Game Over! {status} — {res}")
                notify(f"   Total moves: {len(result.get('history', []))}")
                break

            move_count += 1
            time.sleep(args.delay)

    except KeyboardInterrupt:
        notify("\n⏹️ Stopped by user")
    finally:
        engine.quit()
        print("👋 Engine closed")


if __name__ == "__main__":
    main()

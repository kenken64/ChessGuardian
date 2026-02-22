$(document).ready(function () {
    var game = new Chess();
    var boardEl = $('#board');
    var isFlipped = false;

    // --- Board Configuration ---
    var config = {
        draggable: true,
        position: 'start',
        pieceTheme: 'https://raw.githubusercontent.com/oakmac/chessboardjs/master/website/img/chesspieces/wikipedia/{piece}.png',
        onDragStart: onDragStart,
        onDrop: onDrop,
        onSnapEnd: onSnapEnd
    };

    var board = Chessboard('board', config);

    // --- Drag Start: Only allow human's pieces (Black) ---
    function onDragStart(source, piece, position, orientation) {
        if (game.game_over()) return false;

        // Don't allow moves when it's AI's turn (White)
        if (game.turn() === 'w') return false;

        // Only pick up black pieces
        if (piece.search(/^w/) !== -1) return false;
    }

    // --- Drop: Validate and make move, then let Stockfish reply ---
    function onDrop(source, target) {
        // Auto-promote to queen
        var move = game.move({
            from: source,
            to: target,
            promotion: 'q'
        });

        if (move === null) return 'snapback';

        updateStatus();
        updateMoveHistory();
        highlightLastMove(source, target);

        // After human (Black) moves, let Stockfish (White) reply
        if (!game.game_over()) {
            requestStockfishMove();
        }
    }

    // --- Request Stockfish to make the AI's move ---
    function requestStockfishMove() {
        $('#statusBar').text($('#statusBar').text() + ' — AI thinking...');

        $.ajax({
            url: '/api/move',
            method: 'POST',
            contentType: 'application/json',
            data: JSON.stringify({ fen: game.fen() }),
            success: function (data) {
                if (data.error) {
                    $('#statusBar').text('AI error: ' + data.error);
                    return;
                }

                // Make the Stockfish move on the board
                var aiMove = game.move(data.san);
                if (!aiMove) {
                    // Fallback: try UCI format
                    aiMove = game.move(data.move, { sloppy: true });
                }

                if (aiMove) {
                    board.position(game.fen());
                    updateStatus();
                    updateMoveHistory();
                    highlightLastMove(aiMove.from, aiMove.to);

                    // Now request OpenAI analysis of the position
                    requestAnalysis(data.san);
                }
            },
            error: function (xhr) {
                var msg = 'AI move failed.';
                if (xhr.responseJSON && xhr.responseJSON.error) {
                    msg = xhr.responseJSON.error;
                }
                $('#statusBar').text(msg);
            }
        });
    }

    // --- Snap End: Sync board with game state ---
    function onSnapEnd() {
        board.position(game.fen());
    }

    // --- Highlight last move ---
    function highlightLastMove(from, to) {
        boardEl.find('.square-55d63').removeClass('highlight-move');
        boardEl.find('.square-' + from).addClass('highlight-move');
        boardEl.find('.square-' + to).addClass('highlight-move');
    }

    // --- Update Status Bar ---
    function updateStatus() {
        var status = '';
        var turn = game.turn() === 'w' ? 'White' : 'Black';

        if (game.in_checkmate()) {
            var winner = game.turn() === 'w' ? 'Black' : 'White';
            status = 'Checkmate! ' + winner + ' wins.';
        } else if (game.in_draw()) {
            if (game.in_stalemate()) {
                status = 'Stalemate - Draw';
            } else if (game.insufficient_material()) {
                status = 'Draw - Insufficient material';
            } else if (game.in_threefold_repetition()) {
                status = 'Draw - Threefold repetition';
            } else {
                status = 'Draw';
            }
        } else {
            status = turn + ' to move';
            if (game.in_check()) {
                status += ' (Check!)';
            }
        }

        $('#statusBar').text(status);
    }

    // --- Update Move History ---
    function updateMoveHistory() {
        var history = game.history();
        if (history.length === 0) {
            $('#moveHistory').html('<p class="placeholder">No moves yet</p>');
            $('#openingName').text('');
            return;
        }

        var lastIndex = history.length - 1;
        var html = '';
        for (var i = 0; i < history.length; i += 2) {
            var moveNum = Math.floor(i / 2) + 1;
            html += '<div class="move-row">';
            html += '<span class="move-number">' + moveNum + '.</span>';
            html += '<span class="move' + (i === lastIndex ? ' last-move' : '') + '">' + history[i] + '</span>';
            if (i + 1 < history.length) {
                html += '<span class="move' + (i + 1 === lastIndex ? ' last-move' : '') + '">' + history[i + 1] + '</span>';
            } else {
                html += '<span class="move"></span>';
            }
            html += '</div>';
        }

        $('#moveHistory').html(html);

        // Auto-scroll to bottom
        var el = document.getElementById('moveHistory');
        el.scrollTop = el.scrollHeight;
    }

    // --- Build move history string ---
    function buildMoveHistoryString() {
        var history = game.history();
        var result = '';
        for (var i = 0; i < history.length; i += 2) {
            var moveNum = Math.floor(i / 2) + 1;
            result += moveNum + '. ' + history[i];
            if (i + 1 < history.length) {
                result += ' ' + history[i + 1];
            }
            result += ' ';
        }
        return result.trim();
    }

    // --- Update Win Chance Gauge ---
    function updateWinChance(whitePercent) {
        var w = Math.max(0, Math.min(100, whitePercent));
        var b = 100 - w;
        $('#gaugeWhite').css('width', w + '%');
        $('#gaugeBlack').css('width', b + '%');
        $('#whitePercent').text(w + '%');
        $('#blackPercent').text(b + '%');
    }

    // --- Request AI Analysis ---
    function requestAnalysis(lastMove) {
        $('#analysisContent').hide();
        $('#analysisSpinner').show();

        $.ajax({
            url: '/api/analyze',
            method: 'POST',
            contentType: 'application/json',
            data: JSON.stringify({
                fen: game.fen(),
                last_move: lastMove,
                move_history: buildMoveHistoryString()
            }),
            success: function (data) {
                $('#analysisSpinner').hide();
                if (data.error) {
                    $('#analysisContent').html('<p style="color:#e57373;">' + escapeHtml(data.error) + '</p>');
                } else {
                    // Convert markdown bold to HTML
                    var html = escapeHtml(data.analysis)
                        .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
                        .replace(/\n/g, '<br>');
                    $('#analysisContent').html(html);
                    if (data.winChance !== undefined) {
                        updateWinChance(data.winChance);
                    }
                }
                $('#analysisContent').show();
            },
            error: function (xhr) {
                $('#analysisSpinner').hide();
                var msg = 'Analysis request failed.';
                if (xhr.responseJSON && xhr.responseJSON.error) {
                    msg = xhr.responseJSON.error;
                }
                $('#analysisContent').html('<p style="color:#e57373;">' + escapeHtml(msg) + '</p>');
                $('#analysisContent').show();
            }
        });
    }

    // --- Utility: Escape HTML ---
    function escapeHtml(text) {
        var div = document.createElement('div');
        div.appendChild(document.createTextNode(text));
        return div.innerHTML;
    }

    // --- Update Player Labels and Board Coordinates ---
    function updatePlayerLabels() {
        var ranks = isFlipped ? ['1','2','3','4','5','6','7','8'] : ['8','7','6','5','4','3','2','1'];
        var files = isFlipped ? ['h','g','f','e','d','c','b','a'] : ['a','b','c','d','e','f','g','h'];

        $('#rankLabels').html(ranks.map(function(r) { return '<span>' + r + '</span>'; }).join(''));
        $('#fileLabels').html(files.map(function(f) { return '<span>' + f + '</span>'; }).join(''));

        if (isFlipped) {
            $('#topPlayer').text('White');
            $('#bottomPlayer').text('Black');
        } else {
            $('#topPlayer').text('Black');
            $('#bottomPlayer').text('White');
        }
    }

    // --- Cached games list from server ---
    var savedGamesList = [];
    var currentGameId = null;

    // --- Load saved games from server ---
    function loadSavedGames() {
        $.getJSON('/api/games', function (games) {
            savedGamesList = games;
            renderSavedGames(games);
        });
    }

    // --- Render saved games into the sidebar ---
    function renderSavedGames(games) {
        var container = $('#savedGames');

        if (games.length === 0) {
            container.html('<p class="placeholder">No saved games</p>');
            return;
        }

        var html = '';
        for (var i = 0; i < games.length; i++) {
            var g = games[i];
            var preview = g.moves.length > 40 ? g.moves.substring(0, 40) + '...' : g.moves;
            html += '<div class="saved-game-entry" data-id="' + g.id + '">';
            html += '  <div class="saved-game-header">';
            html += '    <div class="saved-game-info">';
            html += '      <div class="saved-game-title">' + escapeHtml(g.name || 'Game #' + (i + 1)) + '</div>';
            html += '      <div class="saved-game-meta">' + escapeHtml(g.date) + ' &middot; ' + g.moveCount + ' move' + (g.moveCount !== 1 ? 's' : '') + '</div>';
            html += '      <div class="saved-game-preview">' + escapeHtml(preview) + '</div>';
            html += '    </div>';
            html += '    <button class="saved-game-load" title="Load game">Load</button>';
            html += '    <button class="saved-game-download" title="Download game">&#8681;</button>';
            html += '    <button class="saved-game-delete" title="Delete game">&times;</button>';
            html += '  </div>';
            html += '  <div class="saved-game-moves">' + formatMovesHtml(g.history) + '</div>';
            html += '</div>';
        }

        container.html(html);
    }

    // --- Format moves array into HTML ---
    function formatMovesHtml(history) {
        if (!history || history.length === 0) return '';
        var html = '';
        for (var i = 0; i < history.length; i += 2) {
            var moveNum = Math.floor(i / 2) + 1;
            html += '<span class="move-number">' + moveNum + '.</span>';
            html += '<span class="move">' + escapeHtml(history[i]) + '</span>';
            if (i + 1 < history.length) {
                html += '<span class="move">' + escapeHtml(history[i + 1]) + '</span>';
            }
        }
        return html;
    }

    // --- Save current game to server ---
    function saveCurrentGame(silent) {
        var history = game.history();
        if (history.length === 0) return;

        var name = $('#gameNameInput').val().trim();
        if (!name) {
            if (silent) return; // auto-save on New Game: skip if no name
            $('#gameNameInput').focus();
            return;
        }

        var now = new Date();
        var dateStr = now.toLocaleDateString() + ' ' + now.toLocaleTimeString([], {hour: '2-digit', minute: '2-digit'});

        var payload = {
            name: name,
            date: dateStr,
            moves: buildMoveHistoryString(),
            history: history,
            moveCount: history.length
        };

        // If a loaded game is active, overwrite it
        if (currentGameId) {
            payload.id = currentGameId;
        }

        $.ajax({
            url: '/api/games/save',
            method: 'POST',
            contentType: 'application/json',
            data: JSON.stringify(payload),
            success: function (data) {
                currentGameId = data.id;
                loadSavedGames();
            }
        });
    }

    // --- Delete a saved game ---
    function deleteSavedGame(id) {
        $.ajax({
            url: '/api/games/' + id,
            method: 'DELETE',
            success: function () {
                loadSavedGames();
            }
        });
    }

    // --- Load a saved game onto the board ---
    function loadGame(id) {
        var g = null;
        for (var i = 0; i < savedGamesList.length; i++) {
            if (savedGamesList[i].id === id) {
                g = savedGamesList[i];
                break;
            }
        }
        if (!g || !g.history) return;

        game.reset();
        for (var i = 0; i < g.history.length; i++) {
            game.move(g.history[i]);
        }

        currentGameId = g.id;
        $('#gameNameInput').val(g.name || '');

        board.position(game.fen());
        updateStatus();
        updateMoveHistory();
        updateWinChance(50);
        boardEl.find('.square-55d63').removeClass('highlight-move');
        $('#analysisContent').html('<p class="placeholder">Game loaded — click Analyze to review</p>');
        $('#analysisSpinner').hide();
        $('#analysisContent').show();
    }

    // --- Import game from JSON file ---
    function importGame() {
        $('#importFileInput').trigger('click');
    }

    $('#importFileInput').on('change', function () {
        var file = this.files[0];
        if (!file) return;

        var formData = new FormData();
        formData.append('file', file);

        $.ajax({
            url: '/api/games/import',
            method: 'POST',
            data: formData,
            processData: false,
            contentType: false,
            success: function () {
                loadSavedGames();
            },
            error: function (xhr) {
                var msg = 'Import failed.';
                if (xhr.responseJSON && xhr.responseJSON.error) {
                    msg = xhr.responseJSON.error;
                }
                alert(msg);
            }
        });

        // Reset so the same file can be re-imported
        $(this).val('');
    });

    // --- Button: Import Game ---
    $('#importGameBtn').on('click', function () {
        importGame();
    });

    // --- Toggle expand/collapse saved game ---
    $(document).on('click', '.saved-game-header', function (e) {
        if ($(e.target).closest('.saved-game-delete, .saved-game-load, .saved-game-download').length) return;
        $(this).closest('.saved-game-entry').toggleClass('expanded');
    });

    // --- Load button handler ---
    $(document).on('click', '.saved-game-load', function () {
        var id = $(this).closest('.saved-game-entry').data('id');
        loadGame(id);
    });

    // --- Download button handler ---
    $(document).on('click', '.saved-game-download', function () {
        var id = $(this).closest('.saved-game-entry').data('id');
        window.location = '/api/games/' + id + '/export';
    });

    // --- Delete button handler ---
    $(document).on('click', '.saved-game-delete', function () {
        var id = $(this).closest('.saved-game-entry').data('id');
        deleteSavedGame(id);
    });

    // --- Button: Save Game ---
    $('#saveGameBtn').on('click', function () {
        saveCurrentGame();
    });

    // --- Button: Analyze ---
    $('#analyzeBtn').on('click', function () {
        var history = game.history();
        if (history.length === 0) return;
        var lastMove = history[history.length - 1];
        requestAnalysis(lastMove);
    });

    // --- Button: New Game ---
    $('#newGameBtn').on('click', function () {
        saveCurrentGame(true); // auto-save if name + moves exist
        game.reset();
        board.start();
        isFlipped = true;
        currentGameId = null;
        $('#gameNameInput').val('');
        board.orientation('black');
        updatePlayerLabels();
        updateStatus();
        updateWinChance(50);
        $('#moveHistory').html('<p class="placeholder">No moves yet</p>');
        $('#openingName').text('');
        $('#analysisContent').html('<p class="placeholder">AI is thinking...</p>');
        $('#analysisSpinner').hide();
        $('#analysisContent').show();
        boardEl.find('.square-55d63').removeClass('highlight-move');

        // Stockfish makes the first move as White
        requestStockfishMove();
    });

    // --- Button: Flip Board ---
    $('#flipBoardBtn').on('click', function () {
        isFlipped = !isFlipped;
        board.flip();
        updatePlayerLabels();
    });

    // --- Button: Undo ---
    $('#undoBtn').on('click', function () {
        game.undo();
        board.position(game.fen());
        updateStatus();
        updateMoveHistory();
        boardEl.find('.square-55d63').removeClass('highlight-move');
    });

    // --- Sync coordinate labels with actual board size ---
    function syncBoardLayout() {
        var boardHeight = boardEl.find('.board-b72b1').height();
        if (boardHeight) {
            $('#rankLabels').css('height', boardHeight + 'px');
        }
    }

    // --- Responsive: Resize board on window resize ---
    $(window).on('resize', function () {
        board.resize();
        syncBoardLayout();
    });

    // Initial state — flip board so human plays Black
    isFlipped = true;
    board.orientation('black');
    updateStatus();
    updatePlayerLabels();
    loadSavedGames();
    syncBoardLayout();

    // Stockfish makes the first move as White
    requestStockfishMove();
});

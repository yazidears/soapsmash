from flask import Flask, render_template, request, url_for
from flask_socketio import SocketIO, emit, join_room, leave_room

app = Flask(__name__)
app.config['SECRET_KEY'] = 'soap_smash_epic_secret_key'
socketio = SocketIO(app, cors_allowed_origins="*")

MAX_PLAYERS = 4
MIN_PLAYERS_TO_START = 2

players_data = {}  # sid: {'player_index': int, 'name': str, 'is_admin': bool}
screen_sids = set()  # Store SIDs of connected screen(s)
admin_sid = None


def get_player_list_for_update():
    player_list = []
    all_slots = {i: None for i in range(MAX_PLAYERS)}

    for sid, data in players_data.items():
        all_slots[data['player_index']] = {
            'id': data['player_index'],
            'name': data['name'],
            'connected': True,
            'isAdmin': sid == admin_sid,
            'sid': sid  # Include SID for client-side logic if needed
        }

    for i in range(MAX_PLAYERS):
        if all_slots[i] is None:
            player_list.append({
                'id': i, 'name': f'Player {i + 1}',
                'connected': False, 'isAdmin': False, 'sid': None
            })
        else:
            player_list.append(all_slots[i])

    return player_list


def assign_admin_if_none_exists():
    global admin_sid
    if not admin_sid and players_data:
        lowest_index = float('inf')
        candidate_admin_sid = None
        for sid, data in players_data.items():
            if data['player_index'] < lowest_index:
                lowest_index = data['player_index']
                candidate_admin_sid = sid

        if candidate_admin_sid:
            admin_sid = candidate_admin_sid
            if admin_sid in players_data:  # Ensure admin_sid is still valid key
                players_data[admin_sid]['is_admin'] = True
                return True
            else:  # Admin got disconnected right before promotion
                admin_sid = None
    return False


def broadcast_to_screens(event, data):
    for sid in screen_sids:
        emit(event, data, room=sid)


@app.route('/')
def screen_route_handler():
    join_url = url_for('join_route_handler', _external=True)
    return render_template('index.html', mode='screen', join_url=join_url)


@app.route('/join')
def join_route_handler():
    return render_template('index.html', mode='controller')


@socketio.on('connect')
def handle_socket_connect():
    print(f'Client connected: {request.sid}')


@socketio.on('screen_ready_event')
def handle_screen_is_ready():
    screen_sids.add(request.sid)
    print(f'Screen {request.sid} registered. Total screens: {len(screen_sids)}')
    emit('update_player_list_event', {'players': get_player_list_for_update()}, room=request.sid)


@socketio.on('disconnect')
def handle_socket_disconnect():
    print(f'Client disconnected: {request.sid}')

    if request.sid in screen_sids:
        screen_sids.remove(request.sid)
        print(f'Screen {request.sid} unregistered. Remaining screens: {len(screen_sids)}')
        return

    disconnected_player_data = players_data.pop(request.sid, None)

    if disconnected_player_data:
        global admin_sid

        was_admin = (request.sid == admin_sid)
        if was_admin:
            admin_sid = None
            assign_admin_if_none_exists()

        print(
            f"Player {disconnected_player_data['name']} (idx {disconnected_player_data['player_index']}) disconnected.")
        socketio.emit('update_player_list_event', {'players': get_player_list_for_update()})


@socketio.on('request_join_event')
def handle_player_request_join(data_req):
    global admin_sid
    client_sid = request.sid
    player_name_req = data_req.get('playerName', '').strip()

    if client_sid in players_data:
        emit('join_ack_event', {
            'success': True, 'playerIndex': players_data[client_sid]['player_index'],
            'playerName': players_data[client_sid]['name'], 'isAdmin': client_sid == admin_sid
        })
        return

    if len(players_data) >= MAX_PLAYERS:
        emit('join_ack_event', {'success': False, 'message': 'Lobby is full.'})
        broadcast_to_screens('screen_play_sound_event', {'sound': 'error'})
        return

    current_player_indices = {p_data['player_index'] for p_data in players_data.values()}
    assigned_index = -1
    for i in range(MAX_PLAYERS):
        if i not in current_player_indices:
            assigned_index = i
            break

    if assigned_index == -1:
        emit('join_ack_event', {'success': False, 'message': 'Error assigning slot.'})
        broadcast_to_screens('screen_play_sound_event', {'sound': 'error'})
        return

    player_name = player_name_req if player_name_req else f"Soap Bar #{assigned_index + 1}"

    is_new_admin = False
    if not admin_sid:
        admin_sid = client_sid
        is_new_admin = True

    players_data[client_sid] = {
        'player_index': assigned_index, 'name': player_name, 'is_admin': is_new_admin
    }

    print(f"{player_name} (idx {assigned_index}) joined. Admin: {admin_sid == client_sid}")

    emit('join_ack_event', {
        'success': True, 'playerIndex': assigned_index,
        'playerName': player_name, 'isAdmin': client_sid == admin_sid
    })

    socketio.emit('update_player_list_event', {'players': get_player_list_for_update()})
    broadcast_to_screens('screen_play_sound_event', {'sound': 'connected'})


@socketio.on('request_start_game_event')
def handle_admin_request_start_game():
    if request.sid == admin_sid:
        if len(players_data) >= MIN_PLAYERS_TO_START:
            print("Admin started game.")
            socketio.emit('game_starting_event')  # To all clients
            broadcast_to_screens('screen_play_sound_event', {'sound': 'gamestart'})
        else:
            msg = f'Need at least {MIN_PLAYERS_TO_START} players to start.'
            emit('lobby_message_event', {'message': msg, 'isError': True}, room=request.sid)
            broadcast_to_screens('lobby_message_event', {'message': msg, 'isError': True})
            broadcast_to_screens('screen_play_sound_event', {'sound': 'error'})

    else:
        emit('lobby_message_event', {'message': 'Only the admin can start the game.', 'isError': True},
             room=request.sid)
        # No sound for this as it's a controller-specific auth issue, not a lobby state error for the screen


if __name__ == '__main__':
    port = 5002
    print(f"Flask server starting on http://0.0.0.0:{port}")
    socketio.run(app, host='0.0.0.0', port=port, debug=True, allow_unsafe_werkzeug=True)
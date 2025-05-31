from flask import Flask, render_template, request, url_for
from flask_socketio import SocketIO, emit

app = Flask(__name__)
app.config['SECRET_KEY'] = 'minimalist_cool_soap_secret'
socketio = SocketIO(app, cors_allowed_origins="*")

MAX_PLAYERS = 4
MIN_PLAYERS_TO_START = 2

players_data = {}
screen_sids = set()
admin_sid = None


def get_player_list_for_update():
    player_list = []
    all_slots = {i: None for i in range(MAX_PLAYERS)}
    for sid, data in players_data.items():
        all_slots[data['player_index']] = {
            'id': data['player_index'], 'name': data['name'],
            'connected': True, 'isAdmin': sid == admin_sid, 'sid': sid
        }
    for i in range(MAX_PLAYERS):
        if all_slots[i] is None:
            player_list.append({
                'id': i, 'name': f'Join Slot {i + 1}',
                'connected': False, 'isAdmin': False, 'sid': None
            })
        else:
            player_list.append(all_slots[i])
    return player_list


def assign_admin_if_none_exists():
    global admin_sid
    if not admin_sid and players_data:
        lowest_index_found = float('inf')
        candidate_admin_sid = None
        for sid_iter, data_iter in players_data.items():
            if data_iter['player_index'] < lowest_index_found:
                lowest_index_found = data_iter['player_index']
                candidate_admin_sid = sid_iter
        if candidate_admin_sid and candidate_admin_sid in players_data:
            admin_sid = candidate_admin_sid
            players_data[admin_sid]['is_admin'] = True
            return True
        admin_sid = None
    return False


def broadcast_to_screens(event_name, data_payload):
    for sid_iter in screen_sids:
        emit(event_name, data_payload, room=sid_iter)


@app.route('/')
def screen_route_view():
    join_url_for_qr = url_for('join_route_view', _external=True)
    return render_template('index.html', mode='screen', join_url=join_url_for_qr)


@app.route('/join')
def join_route_view():
    return render_template('index.html', mode='controller')


@socketio.on('connect')
def on_socket_connect():
    print(f'Client connected: {request.sid}')


@socketio.on('screen_ready_event')
def on_screen_ready():
    screen_sids.add(request.sid)
    print(f'Screen {request.sid} ready. Screens: {len(screen_sids)}')
    emit('update_player_list_event', {'players': get_player_list_for_update()}, room=request.sid)


@socketio.on('disconnect')
def on_socket_disconnect():
    client_sid_disconnected = request.sid
    print(f'Client disconnected: {client_sid_disconnected}')
    if client_sid_disconnected in screen_sids:
        screen_sids.remove(client_sid_disconnected)
        print(f'Screen {client_sid_disconnected} left. Screens: {len(screen_sids)}')
        return

    player_data_disconnected = players_data.pop(client_sid_disconnected, None)
    if player_data_disconnected:
        global admin_sid
        if client_sid_disconnected == admin_sid:
            admin_sid = None
            assign_admin_if_none_exists()
        print(f"Player {player_data_disconnected['name']} left.")
        socketio.emit('update_player_list_event', {'players': get_player_list_for_update()})


@socketio.on('request_join_event')
def on_request_join(join_data):
    global admin_sid
    client_sid_joining = request.sid
    player_name_from_req = join_data.get('playerName', '').strip()

    if client_sid_joining in players_data:
        emit('join_ack_event', {
            'success': True, 'playerIndex': players_data[client_sid_joining]['player_index'],
            'playerName': players_data[client_sid_joining]['name'],
            'isAdmin': client_sid_joining == admin_sid
        })
        return

    if len(players_data) >= MAX_PLAYERS:
        emit('join_ack_event', {'success': False, 'message': 'Lobby full.'})
        broadcast_to_screens('screen_play_sound_event', {'sound': 'error'})
        return

    current_indices = {p_data['player_index'] for p_data in players_data.values()}
    new_player_idx = -1
    for i in range(MAX_PLAYERS):
        if i not in current_indices:
            new_player_idx = i
            break

    if new_player_idx == -1:
        emit('join_ack_event', {'success': False, 'message': 'Cannot assign slot.'})
        broadcast_to_screens('screen_play_sound_event', {'sound': 'error'})
        return

    final_player_name = player_name_from_req if player_name_from_req else f"Player {new_player_idx + 1}"

    is_this_player_admin = False
    if not admin_sid:
        admin_sid = client_sid_joining
        is_this_player_admin = True

    players_data[client_sid_joining] = {
        'player_index': new_player_idx, 'name': final_player_name, 'is_admin': is_this_player_admin
    }

    print(f"{final_player_name} (idx {new_player_idx}) joined. Admin: {admin_sid == client_sid_joining}")
    emit('join_ack_event', {
        'success': True, 'playerIndex': new_player_idx,
        'playerName': final_player_name, 'isAdmin': client_sid_joining == admin_sid
    })
    socketio.emit('update_player_list_event', {'players': get_player_list_for_update()})
    broadcast_to_screens('screen_play_sound_event', {'sound': 'connected'})


@socketio.on('request_start_game_event')
def on_request_start_game():
    if request.sid == admin_sid:
        if len(players_data) >= MIN_PLAYERS_TO_START:
            print("Admin initiated game start.")
            socketio.emit('game_starting_event')
            broadcast_to_screens('screen_play_sound_event', {'sound': 'gamestart'})
        else:
            start_error_msg = f'Requires {MIN_PLAYERS_TO_START} players. Currently {len(players_data)}.'
            emit('lobby_message_event', {'message': start_error_msg, 'isError': True}, room=request.sid)
            broadcast_to_screens('lobby_message_event', {'message': start_error_msg, 'isError': True})
            broadcast_to_screens('screen_play_sound_event', {'sound': 'error'})
    else:
        emit('lobby_message_event', {'message': 'Access denied: Not admin.', 'isError': True}, room=request.sid)


if __name__ == '__main__':
    port = 5002
    print(f"Soap Smash server running on http://0.0.0.0:{port}")
    socketio.run(app, host='0.0.0.0', port=port, debug=True, allow_unsafe_werkzeug=True)
# app.py
from flask import Flask, render_template, request, url_for
from flask_socketio import SocketIO, emit

app = Flask(__name__)
app.config['SECRET_KEY'] = 'zoom_void_and_game_secret_v8'  # Updated key
socketio = SocketIO(app, cors_allowed_origins="*")

MAX_PLAYERS = 4
MIN_PLAYERS_TO_START = 2

players_data = {}
screen_sids = set()
admin_sid = None
pending_controller_sids = set()


def get_player_list_for_update():
    player_list = []
    all_slots = {i: None for i in range(MAX_PLAYERS)}
    for sid_key, data_val in players_data.items():
        all_slots[data_val['player_index']] = {
            'id': data_val['player_index'], 'name': data_val['name'],
            'connected': True, 'isAdmin': sid_key == admin_sid, 'sid': sid_key
        }
    for i in range(MAX_PLAYERS):
        if all_slots[i] is None:
            player_list.append({
                'id': i, 'name': f'Slot {i + 1}',
                'connected': False, 'isAdmin': False, 'sid': None
            })
        else:
            player_list.append(all_slots[i])
    return player_list


def assign_admin_if_none_exists():
    global admin_sid
    if not admin_sid and players_data:
        lowest_idx = float('inf')
        candidate_sid = None
        for sid_k, data_v in players_data.items():
            if data_v['player_index'] < lowest_idx:
                lowest_idx = data_v['player_index']
                candidate_sid = sid_k
        if candidate_sid and candidate_sid in players_data:
            admin_sid = candidate_sid
            players_data[admin_sid]['is_admin'] = True
            return True
        admin_sid = None
    return False


def broadcast_to_all_screens(event_trigger_name, data_to_send=None):
    for screen_id_iter in screen_sids:
        if data_to_send:
            emit(event_trigger_name, data_to_send, room=screen_id_iter)
        else:
            emit(event_trigger_name, room=screen_id_iter)


@app.route('/')
def screen_view_route():  # Renamed from _v7 for clarity
    url_for_qr = url_for('controller_view_route', _external=True)
    return render_template('screen.html', join_url=url_for_qr)


@app.route('/join')
def controller_view_route():  # Renamed from _v7 for clarity
    return render_template('controller.html')


@app.route('/game.html')  # NEW ROUTE TO SERVE THE GAME HTML
def game_route():
    return render_template('game.html')


@socketio.on('connect')
def on_new_socket_connection():  # Renamed from _v7 for clarity
    new_client_sid = request.sid
    print(f'Client connected: {new_client_sid}')
    if request.referrer and '/join' in request.referrer:
        if new_client_sid not in players_data:
            pending_controller_sids.add(new_client_sid)
            print(f"Controller {new_client_sid} initial connect. Triggering connected sound on screen.")
            broadcast_to_all_screens('play_sound_on_screen_event', {'soundKey': 'connected', 'volume': 0.6})


@socketio.on('screen_is_ready_and_audio_unlocked_event')
def on_screen_is_ready_and_audio_unlocked():  # Renamed from _v7 for clarity
    screen_sids.add(request.sid)
    print(f'Screen {request.sid} registered AND audio unlocked. Total: {len(screen_sids)}')
    emit('update_player_list_data_event', {'players': get_player_list_for_update()}, room=request.sid)
    broadcast_to_all_screens('play_sound_on_screen_event', {'soundKey': 'background', 'volume': 0.3, 'loop': True})


@socketio.on('disconnect')
def on_socket_disconnection():  # Renamed from _v7 for clarity
    disconnected_sid = request.sid
    print(f'Client disconnected: {disconnected_sid}')
    pending_controller_sids.discard(disconnected_sid)
    if disconnected_sid in screen_sids:
        screen_sids.remove(disconnected_sid)
        print(f'Screen {disconnected_sid} unregistered. Total: {len(screen_sids)}')
        return

    disconnected_player = players_data.pop(disconnected_sid, None)
    if disconnected_player:
        global admin_sid
        if disconnected_sid == admin_sid:
            admin_sid = None
            assign_admin_if_none_exists()
        print(f"Player {disconnected_player['name']} left.")
        socketio.emit('update_player_list_data_event', {'players': get_player_list_for_update()})


@socketio.on('controller_request_join_slot_event')
def on_controller_request_join_slot(payload_data):  # Renamed from _v7 for clarity
    global admin_sid
    joining_controller_sid = request.sid
    requested_player_name = payload_data.get('playerName', '').strip()
    pending_controller_sids.discard(joining_controller_sid)

    if joining_controller_sid in players_data:
        emit('controller_join_slot_ack_event', {
            'success': True, 'playerIndex': players_data[joining_controller_sid]['player_index'],
            'playerName': players_data[joining_controller_sid]['name'],
            'isAdmin': joining_controller_sid == admin_sid
        })
        return

    if len(players_data) >= MAX_PLAYERS:
        emit('controller_join_slot_ack_event', {'success': False, 'message': 'Lobby is full.'})
        broadcast_to_all_screens('play_sound_on_screen_event', {'soundKey': 'error', 'volume': 0.5})
        return

    used_indices = {p_data['player_index'] for p_data in players_data.values()}
    player_slot_idx = -1
    for i in range(MAX_PLAYERS):
        if i not in used_indices:
            player_slot_idx = i
            break

    if player_slot_idx == -1:
        emit('controller_join_slot_ack_event', {'success': False, 'message': 'Slot assignment error.'})
        broadcast_to_all_screens('play_sound_on_screen_event', {'soundKey': 'error', 'volume': 0.5})
        return

    final_name = requested_player_name if requested_player_name else f"Player {player_slot_idx + 1}"
    is_admin_now = False
    if not admin_sid:
        admin_sid = joining_controller_sid
        is_admin_now = True

    players_data[joining_controller_sid] = {
        'player_index': player_slot_idx, 'name': final_name, 'is_admin': is_admin_now
    }

    print(f"{final_name} (idx {player_slot_idx}) joined. Admin: {admin_sid == joining_controller_sid}")
    emit('controller_join_slot_ack_event', {
        'success': True, 'playerIndex': player_slot_idx,
        'playerName': final_name, 'isAdmin': admin_sid == joining_controller_sid
    })
    socketio.emit('update_player_list_data_event',
                  {'players': get_player_list_for_update(), 'newJoinIndex': player_slot_idx})


@socketio.on('admin_request_start_game_event')
def on_admin_request_start_game():  # Renamed from _v7 for clarity
    if request.sid == admin_sid:
        if len(players_data) >= MIN_PLAYERS_TO_START:
            print("Admin is initiating game start.")
            socketio.emit('game_start_transition_event')
            broadcast_to_all_screens('play_sound_on_screen_event', {'soundKey': 'gamestart', 'volume': 0.7})
        else:
            err_msg = f'Need {MIN_PLAYERS_TO_START} players. Only {len(players_data)}.'
            emit('controller_lobby_message_event', {'message': err_msg, 'isError': True}, room=request.sid)
            broadcast_to_all_screens('screen_lobby_message_event', {'message': err_msg, 'isError': True})
            broadcast_to_all_screens('play_sound_on_screen_event', {'soundKey': 'error', 'volume': 0.5})
    else:
        emit('controller_lobby_message_event', {'message': 'Only admin can start game.', 'isError': True},
             room=request.sid)


# --- ADDITIONS FOR GAME COMMUNICATION (from previous step, confirmed here) ---
@socketio.on('controller_input_to_server_event')
def handle_controller_input_to_server(data):
    player_sid = request.sid
    if player_sid in players_data:
        player_index = players_data[player_sid]['player_index']
        controller_payload = {
            'playerIndex': player_index,
            'input': data.get('input')
        }
        broadcast_to_all_screens('game_input_to_screen_event', controller_payload)
    else:
        print(f"Warning: Controller input from unknown SID {player_sid}")


@socketio.on('game_state_to_server_event')
def handle_game_state_update_from_game(data):
    print(f"Game state update from iframe: {data}")
    socketio.emit('game_state_update_to_clients_event', data)  # To all clients (screen & controllers)


@socketio.on('request_lobby_reset_from_game_event')
def handle_lobby_reset_request_from_game():
    if screen_sids:
        print("Game requested lobby reset.")
        broadcast_to_all_screens('show_lobby_view_event')
        socketio.emit('controller_return_to_lobby_event')
        broadcast_to_all_screens('play_sound_on_screen_event', {'soundKey': 'click', 'volume': 0.5})  # Optional sound
    else:
        print("Lobby reset requested, but no active screen.")


if __name__ == '__main__':
    port = 5002
    print(f"Soap Smash Full Game Server active on http://0.0.0.0:{port}")
    socketio.run(app, host='0.0.0.0', port=port, debug=True, allow_unsafe_werkzeug=True)
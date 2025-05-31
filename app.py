from flask import Flask, render_template, request, url_for
from flask_socketio import SocketIO, emit

app = Flask(__name__)
app.config['SECRET_KEY'] = 'zoom_void_soap_secret_v6'
socketio = SocketIO(app, cors_allowed_origins="*")

MAX_PLAYERS = 4
MIN_PLAYERS_TO_START = 2

players_data = {}
screen_sids = set()
admin_sid = None
pending_controller_sids = set()  # SIDs of controllers that connected but haven't picked a slot yet


def get_player_list_for_update():
    player_list = []
    all_slots = {i: None for i in range(MAX_PLAYERS)}
    for sid_key, data_val in players_data.items():  # Use distinct var names
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


def broadcast_to_all_screens(event_trigger_name, data_to_send):
    for screen_id_iter in screen_sids:
        emit(event_trigger_name, data_to_send, room=screen_id_iter)


@app.route('/')
def screen_view_route():
    url_for_qr = url_for('controller_view_route', _external=True)
    return render_template('screen.html', join_url=url_for_qr)


@app.route('/join')
def controller_view_route():
    return render_template('controller.html')


@socketio.on('connect')
def on_new_socket_connection():
    new_client_sid = request.sid
    print(f'Client connected: {new_client_sid}')
    # This logic for 'connected' sound on QR scan (initial controller connect)
    if request.referrer and '/join' in request.referrer:  # Check if from controller page
        if new_client_sid not in players_data:  # Not already a fully joined player
            pending_controller_sids.add(new_client_sid)
            print(f"Controller {new_client_sid} connected (pending formal join).")
            broadcast_to_all_screens('screen_audio_event', {'soundKey': 'connected', 'volume': 0.6})


@socketio.on('screen_is_ready_event')  # Client screen announces it's ready
def on_screen_is_ready():
    screen_sids.add(request.sid)
    print(f'Screen {request.sid} registered. Total: {len(screen_sids)}')
    emit('update_player_list_data_event', {'players': get_player_list_for_update()}, room=request.sid)


@socketio.on('disconnect')
def on_socket_disconnection():
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
        print(f"Player {disconnected_player['name']} (idx {disconnected_player['player_index']}) left.")
        socketio.emit('update_player_list_data_event', {'players': get_player_list_for_update()})


@socketio.on('controller_request_join_event')  # Controller formally requests to join a slot
def on_controller_request_join(payload_data):
    global admin_sid
    joining_controller_sid = request.sid
    requested_player_name = payload_data.get('playerName', '').strip()

    pending_controller_sids.discard(joining_controller_sid)  # Processed from pending

    if joining_controller_sid in players_data:  # Already in, just resend ACK
        emit('controller_join_ack_event', {
            'success': True, 'playerIndex': players_data[joining_controller_sid]['player_index'],
            'playerName': players_data[joining_controller_sid]['name'],
            'isAdmin': joining_controller_sid == admin_sid
        })
        return

    if len(players_data) >= MAX_PLAYERS:
        emit('controller_join_ack_event', {'success': False, 'message': 'Lobby is full.'})
        broadcast_to_all_screens('screen_audio_event', {'soundKey': 'error', 'volume': 0.5})  # wah/woh sound
        return

    used_indices = {p_data['player_index'] for p_data in players_data.values()}
    player_slot_idx = -1
    for i in range(MAX_PLAYERS):
        if i not in used_indices:
            player_slot_idx = i
            break

    if player_slot_idx == -1:
        emit('controller_join_ack_event', {'success': False, 'message': 'Slot assignment error.'})
        broadcast_to_all_screens('screen_audio_event', {'soundKey': 'error', 'volume': 0.5})
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
    emit('controller_join_ack_event', {
        'success': True, 'playerIndex': player_slot_idx,
        'playerName': final_name, 'isAdmin': admin_sid == joining_controller_sid
    })
    socketio.emit('update_player_list_data_event',
                  {'players': get_player_list_for_update(), 'newJoinIndex': player_slot_idx})
    # "connected" sound was played on initial controller socket connection.
    # If we want another sound specifically for formal slot join, send it here.
    # broadcast_to_all_screens('screen_audio_event', {'soundKey': 'slot_confirm', 'volume': 0.6})


@socketio.on('admin_request_start_game_event')
def on_admin_request_start_game():
    if request.sid == admin_sid:
        if len(players_data) >= MIN_PLAYERS_TO_START:
            print("Admin is starting the game.")
            socketio.emit('game_start_initiated_event')  # To all clients
            broadcast_to_all_screens('screen_audio_event', {'soundKey': 'gamestart', 'volume': 0.75})
        else:
            err_msg = f'Need {MIN_PLAYERS_TO_START} players. Only {len(players_data)}.'
            emit('controller_lobby_message_event', {'message': err_msg, 'isError': True}, room=request.sid)
            broadcast_to_all_screens('screen_lobby_message_event', {'message': err_msg, 'isError': True})
            broadcast_to_all_screens('screen_audio_event', {'soundKey': 'error', 'volume': 0.5})
    else:
        emit('controller_lobby_message_event', {'message': 'Only admin can start game.', 'isError': True},
             room=request.sid)


if __name__ == '__main__':
    port = 5002
    print(f"Soap Smash Server (vZoomVoid) active on http://0.0.0.0:{port}")
    socketio.run(app, host='0.0.0.0', port=port, debug=True, allow_unsafe_werkzeug=True)
import logging
from flask_login import current_user
from flask_socketio import emit, join_room, leave_room
from app import socketio

logger = logging.getLogger(__name__)

@socketio.on('connect')
def handle_connect():
    """Handle client connection"""
    if current_user.is_authenticated:
        logger.info(f'User {current_user.username} connected')
        # Join user-specific room
        room = f"{current_user.role}_{current_user.id}"
        join_room(room)
        emit('status', {'msg': f'Connected as {current_user.role}'})
    else:
        logger.info('Anonymous user connected')
        emit('status', {'msg': 'Connected anonymously'})

@socketio.on('disconnect')
def handle_disconnect(auth):
    """Handle client disconnection"""
    if current_user.is_authenticated:
        logger.info(f'User {current_user.username} disconnected')
        room = f"{current_user.role}_{current_user.id}"
        leave_room(room)
    else:
        logger.info('Anonymous user disconnected')

@socketio.on('join_room')
def on_join(data):
    """Handle joining rooms"""
    if current_user.is_authenticated:
        room = f"{current_user.role}_{current_user.id}"
        join_room(room)
        emit('status', {'msg': f'Joined room {room}'})
        logger.info(f'User {current_user.username} joined room {room}')

@socketio.on('leave_room')
def on_leave(data):
    """Handle leaving rooms"""
    if current_user.is_authenticated:
        room = f"{current_user.role}_{current_user.id}"
        leave_room(room)
        emit('status', {'msg': f'Left room {room}'})
        logger.info(f'User {current_user.username} left room {room}')

@socketio.on_error_default
def default_error_handler(e):
    """Handle WebSocket errors"""
    logger.error(f'WebSocket error: {e}')
    emit('error', {'message': 'An error occurred'})
#!/usr/bin/env python3
"""
WebSocket Manager for Real-time Updates
Replaces Firestore real-time listeners with WebSocket
"""

from flask_socketio import SocketIO, emit, join_room, leave_room
from flask import request
import logging
import datetime

logger = logging.getLogger(__name__)

class WebSocketManager:
    def __init__(self, app):
        """Initialize WebSocket with Flask app"""
        self.socketio = SocketIO(
            app,
            cors_allowed_origins="*",
            async_mode='threading',
            logger=False,
            engineio_logger=False
        )
        self._setup_handlers()
        logger.info("✅ WebSocket Manager initialized")
    
    def _setup_handlers(self):
        """Set up WebSocket event handlers"""
        
        @self.socketio.on('connect')
        def handle_connect():
            """Handle client connection"""
            logger.info(f"🔌 WebSocket client connected: {request.sid}")
            emit('connected', {'message': 'Connected to Thakii backend'})
        
        @self.socketio.on('disconnect')
        def handle_disconnect():
            """Handle client disconnection"""
            logger.info(f"🔌 WebSocket client disconnected: {request.sid}")
        
        @self.socketio.on('join')
        def handle_join(data):
            """Handle client joining a room (user-specific)"""
            user_id = data.get('user_id')
            if user_id:
                room = f'user_{user_id}'
                join_room(room)
                logger.info(f"👤 Client {request.sid} joined room: {room}")
                emit('joined', {'room': room, 'message': f'Joined room {room}'})
            else:
                logger.warning(f"⚠️  Client {request.sid} tried to join without user_id")
                emit('error', {'message': 'user_id required to join room'})
        
        @self.socketio.on('leave')
        def handle_leave(data):
            """Handle client leaving a room"""
            user_id = data.get('user_id')
            if user_id:
                room = f'user_{user_id}'
                leave_room(room)
                logger.info(f"👤 Client {request.sid} left room: {room}")
                emit('left', {'room': room, 'message': f'Left room {room}'})
        
        @self.socketio.on('ping')
        def handle_ping():
            """Handle ping for connection keep-alive"""
            emit('pong', {'timestamp': str(datetime.datetime.now())})
    
    def notify_task_update(self, user_id: str, task_data: dict):
        """
        Send task update to specific user
        
        Args:
            user_id: User ID to send update to
            task_data: Task data to send
        """
        try:
            room = f'user_{user_id}'
            self.socketio.emit('task_update', task_data, room=room)
            logger.info(f"📨 Task update sent to room {room}: {task_data.get('video_id', 'unknown')}")
        except Exception as e:
            logger.error(f"❌ Failed to send task update to user {user_id}: {e}")
    
    def notify_all_users(self, message_type: str, data: dict):
        """
        Broadcast message to all connected clients
        
        Args:
            message_type: Type of message
            data: Data to broadcast
        """
        try:
            self.socketio.emit(message_type, data)
            logger.info(f"📢 Broadcast sent: {message_type}")
        except Exception as e:
            logger.error(f"❌ Failed to broadcast message: {e}")
    
    def notify_admin_update(self, data: dict):
        """
        Send update to admin users only
        
        Args:
            data: Data to send to admins
        """
        try:
            self.socketio.emit('admin_update', data, room='admins')
            logger.info(f"👑 Admin update sent")
        except Exception as e:
            logger.error(f"❌ Failed to send admin update: {e}")
    
    def run(self, app, **kwargs):
        """Run the WebSocket server"""
        self.socketio.run(app, **kwargs)


# Helper function to get WebSocket manager instance
_websocket_manager_instance = None

def init_websocket(app):
    """Initialize WebSocket manager with Flask app"""
    global _websocket_manager_instance
    _websocket_manager_instance = WebSocketManager(app)
    return _websocket_manager_instance

def get_websocket_manager():
    """Get the WebSocket manager instance"""
    return _websocket_manager_instance


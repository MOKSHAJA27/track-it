import eventlet
eventlet.monkey_patch()

from app import app, socketio
import routes              # noqa: F401 (registers routes)
import websocket_handler   # noqa: F401 (registers websocket events)
import logging

if __name__ == "__main__":
    try:
        logging.info("Starting TrackIt application...")
        socketio.run(app, host="0.0.0.0", port=5000, debug=True, allow_unsafe_werkzeug=True)
    except Exception as e:
        logging.error(f"Failed to start application: {str(e)}")
        raise

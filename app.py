import eventlet
eventlet.monkey_patch()

import os
from dotenv import load_dotenv
from flask import Flask, send_from_directory
from flask_login import LoginManager
from flask_socketio import SocketIO
from werkzeug.middleware.proxy_fix import ProxyFix
from supabase import create_client, Client

# Load environment variables
load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

login_manager = LoginManager()
socketio = SocketIO()

def create_app():
    app = Flask(__name__)
    app.secret_key = os.getenv("SESSION_SECRET", "dev-secret-key")
    app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1)

    login_manager.init_app(app)
    socketio.init_app(app, cors_allowed_origins="*")
    login_manager.login_view = 'login'
    login_manager.login_message = 'Please log in to access this page.'
    login_manager.login_message_category = 'info'

    return app

app = create_app()

# Route to serve manifest.json with correct MIME type
@app.route('/manifest.json')
def manifest():
    return send_from_directory('static', 'manifest.json', mimetype='application/manifest+json')

# You can add similar routes for icons or service workers if needed:
@app.route('/static/<path:filename>')
def static_files(filename):
    return send_from_directory('static', filename)
from flask import jsonify, request, current_app
from app.blueprints.main import main_bp
from app.firestore_client import get_firestore_client
from app.gemini_integration import GeminiIntegration
import logging
import firebase_admin
from firebase_admin import auth as firebase_auth
from google.cloud import firestore

@main_bp.route('/')
def index():
    return render_template('main/index.html')

# AI Integration Endpoints

@main_bp.route('/ai/chatbot', methods=['POST'])
def ai_chatbot():
    data = request.json
    user_message = data.get('message')
    if not user_message:
        return jsonify({'error': 'No message provided.'}), 400
    
    gemini = current_app.gemini
    response = gemini.generate_chat_response(user_message)
    
    # Log conversation if needed
    db = get_firestore_client(current_app.config['FIREBASE_CREDENTIALS'])
    db.collection('chat_logs').add({
        'user_message': user_message,
        'bot_response': response,
        'timestamp': firestore.SERVER_TIMESTAMP
    })
    
    return jsonify({'response': response}), 200

@main_bp.route('/ai/generate_report', methods=['POST'])
def ai_generate_report():
    data = request.json
    report_data = data.get('report_data')  # Should be a structured dict
    
    if not report_data:
        return jsonify({'error': 'No report data provided.'}), 400
    
    gemini = current_app.gemini
    summary = gemini.generate_report_summary(report_data)
    
    return jsonify({'summary': summary}), 200

from flask import jsonify, request, current_app
from app.blueprints.auth import auth_bp
from app.firestore_client import get_firestore_client
from app.gemini_integration import GeminiIntegration
import logging
import firebase_admin
from firebase_admin import auth as firebase_auth
from google.cloud import firestore

@auth_bp.route('/register', methods=['POST'])
def register():
    """
    Endpoint to handle user registration.
    Expects JSON payload with 'email', 'password', 'role'.
    """
    data = request.json
    email = data.get('email')
    password = data.get('password')
    role = data.get('role')  # 'hr' or 'employee'
    
    if not all([email, password, role]):
        return jsonify({'error': 'Missing email, password, or role.'}), 400
    
    if role not in ['hr', 'employee']:
        return jsonify({'error': 'Invalid role specified.'}), 400
    
    try:
        # Create user with Firebase Authentication
        user = firebase_auth.create_user(
            email=email,
            password=password
        )
        user_id = user.uid
        
        # Add user data to Firestore
        db = get_firestore_client(current_app.config['FIREBASE_CREDENTIALS'])
        db.collection('users').document(user_id).set({
            'email': email,
            'role': role,
            'created_at': firestore.SERVER_TIMESTAMP
        })
        
        logging.info(f"User registered successfully: {email}")
        return jsonify({'message': 'User registered successfully.'}), 201
    except firebase_admin.auth.EmailAlreadyExistsError:
        logging.warning(f"Registration failed: Email already exists - {email}")
        return jsonify({'error': 'Email already exists.'}), 400
    except Exception as e:
        logging.error(f"Registration failed: {e}")
        return jsonify({'error': 'Registration failed.'}), 500

@auth_bp.route('/login', methods=['POST'])
def login():
    """
    Endpoint to handle user login.
    Expects JSON payload with 'email' and 'password'.
    Note: Firebase Authentication handles login on the client side.
    This endpoint can be used for additional server-side processing if needed.
    """
    # Typically, login is handled on the frontend with Firebase SDK
    # This endpoint can be used to verify tokens or perform server-side actions
    return jsonify({'message': 'Login handled on the client side.'}), 200

@auth_bp.route('/verify_token', methods=['POST'])
def verify_token():
    """
    Endpoint to verify Firebase ID Token.
    Expects JSON payload with 'token'.
    Returns user information if token is valid.
    """
    data = request.json
    token = data.get('token')
    
    if not token:
        return jsonify({'error': 'No token provided.'}), 400
    
    try:
        decoded_token = firebase_auth.verify_id_token(token)
        uid = decoded_token['uid']
        email = decoded_token.get('email')
        db = get_firestore_client(current_app.config['FIREBASE_CREDENTIALS'])
        user_doc = db.collection('users').document(uid).get()
        if not user_doc.exists:
            return jsonify({'error': 'User does not exist.'}), 404
        
        user_data = user_doc.to_dict()
        user_info = {
            'uid': uid,
            'email': email,
            'role': user_data.get('role')
        }
        return jsonify({'user': user_info}), 200
    except firebase_admin.auth.InvalidIdTokenError:
        logging.warning("Invalid Firebase ID Token.")
        return jsonify({'error': 'Invalid token.'}), 401
    except firebase_admin.auth.ExpiredIdTokenError:
        logging.warning("Expired Firebase ID Token.")
        return jsonify({'error': 'Token expired.'}), 401
    except Exception as e:
        logging.error(f"Token verification failed: {e}")
        return jsonify({'error': 'Token verification failed.'}), 500

@auth_bp.route('/logout', methods=['POST'])
def logout():
    """
    Endpoint to handle user logout.
    Typically, logout is handled on the client side by revoking tokens.
    """
    # Revoke tokens on the server side if needed
    return jsonify({'message': 'Logout handled on the client side.'}), 200

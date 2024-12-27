# app/blueprints/auth/routes.py

from flask import render_template, request, redirect, url_for, flash, session, current_app
import hashlib

@auth_bp.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        role = request.form.get('role')  # e.g., admin, teacher, parent
        
        if not username or not password or not role:
            flash("All fields are required.", "danger")
            return redirect(url_for('auth.register'))
        
        db = current_app.db
        user_ref = db.collection('users').document(username)
        user = user_ref.get()
        if user.exists:
            flash("Username already exists.", "danger")
            return redirect(url_for('auth.register'))
        
        # Hash the password
        hashed_password = hashlib.sha256(password.encode()).hexdigest()
        
        user_data = {
            "username": username,
            "password": hashed_password,
            "role": role
        }
        
        user_ref.set(user_data)
        flash("Registration successful. Please log in.", "success")
        return redirect(url_for('auth.login'))
    
    return render_template('auth/register.html')

@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        
        if not username or not password:
            flash("Username and password are required.", "danger")
            return redirect(url_for('auth.login'))
        
        db = current_app.db
        user_ref = db.collection('users').document(username)
        user = user_ref.get()
        if not user.exists:
            flash("Invalid username or password.", "danger")
            return redirect(url_for('auth.login'))
        
        user_data = user.to_dict()
        hashed_password = hashlib.sha256(password.encode()).hexdigest()
        
        if hashed_password != user_data['password']:
            flash("Invalid username or password.", "danger")
            return redirect(url_for('auth.login'))
        
        # Successful login
        session['username'] = username
        session['role'] = user_data['role']
        flash("Logged in successfully.", "success")
        return redirect(url_for('main.index'))
    
    return render_template('auth/login.html')

@auth_bp.route('/logout')
def logout():
    session.pop('username', None)
    session.pop('role', None)
    flash("Logged out successfully.", "success")
    return redirect(url_for('auth.login'))
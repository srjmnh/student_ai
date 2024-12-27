# app/blueprints/grades/routes.py

from flask import render_template, request, redirect, url_for, flash, current_app, jsonify
import json
from datetime import datetime

@grades_bp.route('/')
def view_grades():
    db = current_app.db
    grades_ref = db.collection('grades')
    grades = [doc.to_dict() for doc in grades_ref.stream()]
    return render_template('grades/view_grades.html', grades=grades)

@grades_bp.route('/add', methods=['GET', 'POST'])
def add_grade():
    if request.method == 'POST':
        data = request.form.to_dict()
        subject = data.get('subject')
        if not subject:
            flash("Subject name is required.", "danger")
            return redirect(url_for('grades.add_grade'))
        
        grades_data = data.get('grades')  # Expected JSON
        try:
            grades_json = json.loads(grades_data)
        except json.JSONDecodeError:
            flash("Invalid grades format. Please provide valid JSON.", "danger")
            return redirect(url_for('grades.add_grade'))
        
        # Generate unique subject ID
        subject_id = generate_subject_id(subject)
        
        grade_entry = {
            "subject": subject,
            "grades": grades_json,
            "created_at": datetime.utcnow()
        }
        
        db = current_app.db
        db.collection('grades').document(subject_id).set(grade_entry)
        flash(f"Grades for subject {subject} added successfully with ID {subject_id}.", "success")
        return redirect(url_for('grades.view_grades'))
    
    return render_template('grades/add_grade.html')

@grades_bp.route('/edit/<subject_id>', methods=['GET', 'POST'])
def edit_grade(subject_id):
    db = current_app.db
    grade_ref = db.collection('grades').document(subject_id)
    grade = grade_ref.get()
    if not grade.exists:
        flash("Grade entry not found.", "danger")
        return redirect(url_for('grades.view_grades'))
    
    if request.method == 'POST':
        data = request.form.to_dict()
        subject = data.get('subject')
        grades_data = data.get('grades')  # Expected JSON
        try:
            grades_json = json.loads(grades_data)
        except json.JSONDecodeError:
            flash("Invalid grades format. Please provide valid JSON.", "danger")
            return redirect(url_for('grades.edit_grade', subject_id=subject_id))
        
        updates = {
            "subject": subject,
            "grades": grades_json,
            "updated_at": datetime.utcnow()
        }
        
        grade_ref.update(updates)
        flash(f"Grades for subject {subject} updated successfully.", "success")
        return redirect(url_for('grades.view_grades'))
    
    grade_data = grade.to_dict()
    return render_template('grades/edit_grade.html', grade=grade_data, subject_id=subject_id)

@grades_bp.route('/delete/<subject_id>', methods=['POST'])
def delete_grade(subject_id):
    db = current_app.db
    grade_ref = db.collection('grades').document(subject_id)
    grade = grade_ref.get()
    if not grade.exists:
        return jsonify({"error": "Grade entry not found."}), 404
    grade_ref.delete()
    return jsonify({"success": True, "message": f"Grade entry {subject_id} deleted successfully."}), 200

def generate_subject_id(subject_name):
    db = current_app.db
    existing_ids = [doc.id for doc in db.collection('grades').stream()]
    r = random.randint(1000, 9999)
    base = subject_name.lower().replace(" ", "_")
    subject_id = f"{base}_{r}"
    while subject_id in existing_ids:
        r = random.randint(1000, 9999)
        subject_id = f"{base}_{r}"
    return subject_id
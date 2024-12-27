# app/blueprints/attendance/routes.py

from flask import render_template, request, redirect, url_for, flash, current_app, jsonify
from datetime import datetime

@attendance_bp.route('/')
def view_attendance():
    db = current_app.db
    attendance_ref = db.collection('attendance')
    records = [doc.to_dict() for doc in attendance_ref.stream()]
    return render_template('attendance/view_attendance.html', records=records)

@attendance_bp.route('/mark', methods=['GET', 'POST'])
def mark_attendance():
    if request.method == 'POST':
        data = request.form.to_dict()
        date_str = data.get('date')
        attendance_data = data.get('attendance')  # Expected to be JSON
        try:
            date = datetime.strptime(date_str, '%Y-%m-%d').date()
            attendance_json = json.loads(attendance_data)
        except ValueError:
            flash("Invalid date format.", "danger")
            return redirect(url_for('attendance.mark_attendance'))
        except json.JSONDecodeError:
            flash("Invalid attendance data format.", "danger")
            return redirect(url_for('attendance.mark_attendance'))
        
        db = current_app.db
        record_ref = db.collection('attendance').document(str(date))
        record_ref.set({"date": str(date), "attendance": attendance_json})
        flash(f"Attendance for {date} marked successfully.", "success")
        return redirect(url_for('attendance.view_attendance'))
    
    return render_template('attendance/mark_attendance.html')

@attendance_bp.route('/api/attendance', methods=['GET'])
def get_attendance_api():
    db = current_app.db
    date = request.args.get('date')
    if not date:
        return jsonify({"error": "Date parameter is required."}), 400
    record_ref = db.collection('attendance').document(date)
    record = record_ref.get()
    if not record.exists:
        return jsonify({"error": "No attendance record found for this date."}), 404
    return jsonify(record.to_dict()), 200
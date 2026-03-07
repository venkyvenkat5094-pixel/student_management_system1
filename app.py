from flask import Flask, render_template, request, redirect, session, jsonify
from flask_sqlalchemy import SQLAlchemy
from datetime import date, datetime
from google.genai import Client
import os

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "secret123")

app.config["SQLALCHEMY_DATABASE_URI"] = os.environ.get("DATABASE_URL", "sqlite:///database.db")
if app.config["SQLALCHEMY_DATABASE_URI"].startswith("postgres://"):
    app.config["SQLALCHEMY_DATABASE_URI"] = app.config["SQLALCHEMY_DATABASE_URI"].replace("postgres://", "postgresql://", 1)

app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
db = SQLAlchemy(app)

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "").strip()
client = Client(api_key=GEMINI_API_KEY) if GEMINI_API_KEY else None


# =========================
# MODELS
# =========================
class Admin(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    admin_id = db.Column(db.String(50), unique=True, nullable=False)
    username = db.Column(db.String(100), unique=True, nullable=True)
    password = db.Column(db.String(100), nullable=True)
    role = db.Column(db.String(20), nullable=False)   # superadmin / admin


class Student(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    roll_number = db.Column(db.String(50), nullable=False)
    owner_admin_id = db.Column(db.Integer, nullable=False)


class Attendance(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey("student.id"), nullable=False)
    date = db.Column(db.String(50), nullable=False)
    status = db.Column(db.String(20), nullable=False)
    owner_admin_id = db.Column(db.Integer, nullable=False)

    student = db.relationship("Student", backref="attendance")


class ChatHistory(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_type = db.Column(db.String(20), nullable=False)   # admin / student
    user_ref_id = db.Column(db.Integer, nullable=False)
    user_message = db.Column(db.Text, nullable=False)
    bot_reply = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.String(50), nullable=False)


# =========================
# HELPERS
# =========================
def admin_logged_in():
    return "admin_id" in session


def student_logged_in():
    return "student_id" in session


def require_admin():
    return admin_logged_in()


def require_superadmin():
    return admin_logged_in() and session.get("admin_role") == "superadmin"


def current_admin_is_superadmin():
    return session.get("admin_role") == "superadmin"


def get_current_chat_owner():
    if admin_logged_in():
        return ("admin", session["admin_id"])
    if student_logged_in():
        return ("student", session["student_id"])
    return (None, None)


def get_chat_history():
    user_type, user_ref_id = get_current_chat_owner()
    if not user_type:
        return []

    chats = ChatHistory.query.filter_by(
        user_type=user_type,
        user_ref_id=user_ref_id
    ).order_by(ChatHistory.id.asc()).all()

    return [{"user": c.user_message, "bot": c.bot_reply} for c in chats]


def global_stats_for_current_admin():
    if not admin_logged_in():
        return 0, 0, 0, 0

    if current_admin_is_superadmin():
        total_students = Student.query.count()
        total_attendance = Attendance.query.count()
        total_present = Attendance.query.filter_by(status="Present").count()
        total_absent = Attendance.query.filter_by(status="Absent").count()
    else:
        admin_id = session["admin_id"]
        total_students = Student.query.filter_by(owner_admin_id=admin_id).count()
        total_attendance = Attendance.query.filter_by(owner_admin_id=admin_id).count()
        total_present = Attendance.query.filter_by(owner_admin_id=admin_id, status="Present").count()
        total_absent = Attendance.query.filter_by(owner_admin_id=admin_id, status="Absent").count()

    return total_students, total_attendance, total_present, total_absent


def student_stats(student_id):
    total = Attendance.query.filter_by(student_id=student_id).count()
    present = Attendance.query.filter_by(student_id=student_id, status="Present").count()
    absent = Attendance.query.filter_by(student_id=student_id, status="Absent").count()
    pct = round((present / total) * 100, 2) if total else 0
    return total, present, absent, pct


# =========================
# CHATBOT
# =========================
def bot_reply_only_details(message):
    text = message.lower().strip()

    if student_logged_in():
        student = Student.query.get(session["student_id"])
        if not student:
            return "Student not found."

        total, present, absent, pct = student_stats(student.id)

        if "name" in text:
            return f"Your name is {student.name}."

        if "roll" in text:
            return f"Your roll number is {student.roll_number}."

        if "attendance" in text or "present" in text or "absent" in text or "percentage" in text:
            return f"Your attendance details: Present={present}, Absent={absent}, Total={total}, Percentage={pct}%."

        if client:
            prompt = f"""
You are an educational AI assistant.
Answer only education-related questions and student-related questions.
Do not answer politics, entertainment, or unrelated topics.
Keep answers simple and useful.

Question: {message}
"""
            try:
                response = client.models.generate_content(
                    model="gemini-2.5-flash",
                    contents=prompt
                )
                return response.text or "I can help with education and your student details."
            except Exception:
                return "AI is not responding right now."

        return "AI key not set. I can only answer student details and attendance."

    if admin_logged_in():
        total_students, total_attendance, total_present, total_absent = global_stats_for_current_admin()

        if "total students" in text:
            return f"Total students: {total_students}"

        if "total attendance" in text:
            return f"Total attendance records: {total_attendance}"

        if "total present" in text:
            return f"Total present: {total_present}"

        if "total absent" in text:
            return f"Total absent: {total_absent}"

        if "list students" in text or "show students" in text:
            if current_admin_is_superadmin():
                students = Student.query.all()
            else:
                students = Student.query.filter_by(owner_admin_id=session["admin_id"]).all()

            if not students:
                return "No students found."
            return "Students:\n" + "\n".join([f"{s.name} ({s.roll_number})" for s in students])

        if client:
            prompt = f"""
You are an educational AI assistant.
Answer only education-related questions and student-related questions.
Do not answer politics, entertainment, or unrelated topics.
Keep answers simple and useful.

Question: {message}
"""
            try:
                response = client.models.generate_content(
                    model="gemini-2.5-flash",
                    contents=prompt
                )
                return response.text or "I can help with education and student-related questions."
            except Exception:
                return "AI is not responding right now."

        return "AI key not set. I can only answer student details and attendance."

    return "Please login first."


# =========================
# LOGIN
# =========================
@app.route("/", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form["username"]
        password = request.form["password"]

        admin = Admin.query.filter_by(
            username=username,
            password=password,
            role="superadmin"
        ).first()

        if admin:
            session.clear()
            session["admin_id"] = admin.id
            session["admin_role"] = admin.role
            session["admin_custom_id"] = admin.admin_id
            session["admin_username"] = admin.username
            return redirect("/admin/dashboard")

    return render_template("login.html")


@app.route("/admin-id-login", methods=["GET", "POST"])
def admin_id_login():
    if request.method == "POST":
        admin_id = request.form["admin_id"]

        admin = Admin.query.filter_by(admin_id=admin_id, role="admin").first()

        if admin:
            session.clear()
            session["admin_id"] = admin.id
            session["admin_role"] = admin.role
            session["admin_custom_id"] = admin.admin_id
            session["admin_username"] = admin.admin_id
            return redirect("/admin/dashboard")

    return render_template("admin_id_login.html")


@app.route("/student/login", methods=["GET", "POST"])
def student_login():
    if request.method == "POST":
        roll_number = request.form.get("roll_number")

        student = Student.query.filter_by(roll_number=roll_number).first()

        if student:
            session.clear()
            session["student_id"] = student.id
            session["student_owner_admin_id"] = student.owner_admin_id
            return redirect("/student/dashboard")

        return render_template("student_login.html", error="Student not found.")

    return render_template("student_login.html", error=None)


# =========================
# DASHBOARDS
# =========================
@app.route("/admin/dashboard")
def admin_dashboard():
    if not require_admin():
        return redirect("/")

    total_students, total_attendance, total_present, total_absent = global_stats_for_current_admin()

    return render_template(
        "admin_dashboard.html",
        total_students=total_students,
        total_attendance=total_attendance,
        total_present=total_present,
        total_absent=total_absent,
        chat_history=get_chat_history()
    )


@app.route("/student/dashboard")
def student_dashboard():
    if "student_id" not in session:
        return redirect("/student/login")

    student = Student.query.get(session["student_id"])
    if not student:
        session.clear()
        return redirect("/student/login")

    attendance = Attendance.query.filter_by(student_id=student.id).all()
    total, present, absent, pct = student_stats(student.id)

    return render_template(
        "student_dashboard.html",
        student=student,
        attendance=attendance,
        total=total,
        present=present,
        absent=absent,
        pct=pct,
        chat_history=get_chat_history()
    )


# =========================
# ADMINS
# =========================
@app.route("/add_admin", methods=["GET", "POST"])
def add_admin():
    if not require_admin():
        return redirect("/")

    if not require_superadmin():
        return "Access denied. Only main admin can add new admin."

    error = None

    if request.method == "POST":
        admin_id = request.form["admin_id"]

        existing_admin_id = Admin.query.filter_by(admin_id=admin_id).first()

        if existing_admin_id:
            error = "Admin ID already exists."
        else:
            new_admin = Admin(
                admin_id=admin_id,
                username=None,
                password=None,
                role="admin"
            )
            db.session.add(new_admin)
            db.session.commit()
            return redirect("/admin/dashboard")

    return render_template("add_admin.html", error=error)


@app.route("/view_admins")
def view_admins():
    if not require_admin():
        return redirect("/")

    if not require_superadmin():
        return "Access denied. Only main admin can view admins."

    admins = Admin.query.all()
    return render_template("view_admins.html", admins=admins)


@app.route("/delete_admin/<int:id>")
def delete_admin(id):
    if not require_admin():
        return redirect("/")

    if not require_superadmin():
        return "Access denied. Only main admin can delete admins."

    admin = Admin.query.get(id)

    if admin:
        if admin.role == "superadmin":
            return "Main admin cannot be deleted."

        # delete only that admin's owned data too
        students = Student.query.filter_by(owner_admin_id=admin.id).all()
        student_ids = [s.id for s in students]

        if student_ids:
            Attendance.query.filter(Attendance.student_id.in_(student_ids)).delete(synchronize_session=False)
            Student.query.filter(Student.id.in_(student_ids)).delete(synchronize_session=False)

        ChatHistory.query.filter_by(user_type="admin", user_ref_id=admin.id).delete()
        db.session.delete(admin)
        db.session.commit()

    return redirect("/view_admins")


# =========================
# STUDENTS
# =========================
@app.route("/add_student", methods=["GET", "POST"])
def add_student():
    if not require_admin():
        return redirect("/")

    if request.method == "POST":
        name = request.form["name"]
        roll_number = request.form["roll_number"]

        existing = Student.query.filter_by(
            roll_number=roll_number,
            owner_admin_id=session["admin_id"]
        ).first()

        if existing:
            return "Roll number already exists for your account."

        student = Student(
            name=name,
            roll_number=roll_number,
            owner_admin_id=session["admin_id"]
        )
        db.session.add(student)
        db.session.commit()
        return redirect("/view_students")

    return render_template("add_student.html")


@app.route("/view_students")
def view_students():
    if not require_admin():
        return redirect("/")

    if current_admin_is_superadmin():
        students = Student.query.all()
    else:
        students = Student.query.filter_by(owner_admin_id=session["admin_id"]).all()

    return render_template("view_students.html", students=students)


@app.route("/delete_student/<int:id>")
def delete_student(id):
    if not require_admin():
        return redirect("/")

    if current_admin_is_superadmin():
        student = Student.query.get(id)
    else:
        student = Student.query.filter_by(
            id=id,
            owner_admin_id=session["admin_id"]
        ).first()

    if student:
        Attendance.query.filter_by(student_id=student.id).delete()
        ChatHistory.query.filter_by(user_type="student", user_ref_id=student.id).delete()
        db.session.delete(student)
        db.session.commit()

    return redirect("/view_students")


# =========================
# ATTENDANCE
# =========================
@app.route("/add_attendance", methods=["GET", "POST"])
def add_attendance():
    if not require_admin():
        return redirect("/")

    if current_admin_is_superadmin():
        students = Student.query.all()
    else:
        students = Student.query.filter_by(owner_admin_id=session["admin_id"]).all()

    if request.method == "POST":
        student_id = request.form["student_id"]
        attendance_date = request.form["date"]
        status = request.form["status"]

        if current_admin_is_superadmin():
            student = Student.query.get(student_id)
            owner_admin_id = student.owner_admin_id if student else None
        else:
            student = Student.query.filter_by(
                id=student_id,
                owner_admin_id=session["admin_id"]
            ).first()
            owner_admin_id = session["admin_id"]

        if not student:
            return "Invalid student."

        record = Attendance(
            student_id=student_id,
            date=attendance_date,
            status=status,
            owner_admin_id=owner_admin_id
        )
        db.session.add(record)
        db.session.commit()
        return redirect("/view_attendance")

    return render_template("add_attendance.html", students=students, today=str(date.today()))


@app.route("/view_attendance")
def view_attendance():
    if not require_admin():
        return redirect("/")

    if current_admin_is_superadmin():
        records = Attendance.query.all()
    else:
        records = Attendance.query.filter_by(owner_admin_id=session["admin_id"]).all()

    return render_template("view_attendance.html", records=records)


@app.route("/delete_attendance/<int:id>")
def delete_attendance(id):
    if not require_admin():
        return redirect("/")

    if current_admin_is_superadmin():
        record = Attendance.query.get(id)
    else:
        record = Attendance.query.filter_by(
            id=id,
            owner_admin_id=session["admin_id"]
        ).first()

    if record:
        db.session.delete(record)
        db.session.commit()

    return redirect("/view_attendance")


# =========================
# CHAT API
# =========================
@app.route("/chat_api", methods=["POST"])
def chat_api():
    if not admin_logged_in() and not student_logged_in():
        return jsonify({"reply": "Please login first."})

    data = request.get_json()
    msg = data["message"]

    reply = bot_reply_only_details(msg)

    user_type, user_ref_id = get_current_chat_owner()

    chat = ChatHistory(
        user_type=user_type,
        user_ref_id=user_ref_id,
        user_message=msg,
        bot_reply=reply,
        created_at=str(datetime.now())
    )

    db.session.add(chat)
    db.session.commit()

    return jsonify({"reply": reply})


@app.route("/new_chat", methods=["POST"])
def new_chat():
    user_type, user_ref_id = get_current_chat_owner()

    if user_type and user_ref_id:
        ChatHistory.query.filter_by(
            user_type=user_type,
            user_ref_id=user_ref_id
        ).delete()
        db.session.commit()

    return jsonify({"ok": True})


# =========================
# LOGOUT
# =========================
@app.route("/logout")
def logout():
    session.clear()
    return redirect("/")


# =========================
# INIT DB
# =========================
def init_db():
    with app.app_context():
        db.create_all()

        if not Admin.query.filter_by(username="venkat").first():
            main_admin = Admin(
                admin_id="MAIN001",
                username="venkat",
                password="venky103project",
                role="superadmin"
            )
            db.session.add(main_admin)
            db.session.commit()


init_db()


# =========================
# START APP
# =========================
if __name__ == "__main__":
    app.run(debug=True)

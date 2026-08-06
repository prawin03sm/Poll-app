import os
import sqlite3
from functools import wraps

from flask import Flask, flash, g, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash


app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "change-this-secret-before-production")
app.config["DATABASE"] = os.path.join(app.root_path, "polls.db")


def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(app.config["DATABASE"])
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


@app.teardown_appcontext
def close_db(_error):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    db = get_db()
    db.executescript("""
        CREATE TABLE IF NOT EXISTS admins (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS questions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            question TEXT NOT NULL,
            is_active INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS choices (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            question_id INTEGER NOT NULL,
            choice_text TEXT NOT NULL,
            votes INTEGER NOT NULL DEFAULT 0,
            FOREIGN KEY (question_id) REFERENCES questions(id) ON DELETE CASCADE
        );
    """)
    if not db.execute("SELECT 1 FROM admins LIMIT 1").fetchone():
        db.execute(
            "INSERT INTO admins (username, password_hash) VALUES (?, ?)",
            ("admin", generate_password_hash("admin123")),
        )
    if not db.execute("SELECT 1 FROM questions LIMIT 1").fetchone():
        cursor = db.execute("INSERT INTO questions (question) VALUES (?)", ("Which feature should we build next?",))
        question_id = cursor.lastrowid
        db.executemany(
            "INSERT INTO choices (question_id, choice_text) VALUES (?, ?)",
            [(question_id, "Dark mode"), (question_id, "Mobile app"), (question_id, "Email notifications")],
        )
    db.commit()


def admin_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("admin_id"):
            flash("Please sign in to access the admin area.", "warning")
            return redirect(url_for("admin_login"))
        return view(*args, **kwargs)
    return wrapped


def question_with_choices(question_id):
    db = get_db()
    question = db.execute("SELECT * FROM questions WHERE id = ?", (question_id,)).fetchone()
    if question is None:
        return None, []
    choices = db.execute("SELECT * FROM choices WHERE question_id = ? ORDER BY id", (question_id,)).fetchall()
    return question, choices


@app.route("/")
def index():
    questions = get_db().execute("SELECT * FROM questions WHERE is_active = 1 ORDER BY created_at DESC").fetchall()
    return render_template("index.html", questions=questions)


@app.route("/poll/<int:question_id>")
def poll(question_id):
    question, choices = question_with_choices(question_id)
    if question is None or not question["is_active"]:
        flash("That poll is not available.", "warning")
        return redirect(url_for("index"))
    return render_template("poll.html", question=question, choices=choices)


@app.post("/poll/<int:question_id>/vote")
def vote(question_id):
    question, choices = question_with_choices(question_id)
    choice_id = request.form.get("choice_id", type=int)
    valid_choice_ids = {choice["id"] for choice in choices}
    voted = session.setdefault("voted_questions", [])
    if question is None or not question["is_active"]:
        flash("That poll is not available.", "warning")
    elif choice_id not in valid_choice_ids:
        flash("Please select one of the available choices.", "warning")
    elif question_id in voted:
        flash("You have already voted on this poll from this browser.", "warning")
    else:
        get_db().execute("UPDATE choices SET votes = votes + 1 WHERE id = ?", (choice_id,))
        get_db().commit()
        voted.append(question_id)
        session["voted_questions"] = voted
        flash("Thanks — your vote has been recorded!", "success")
    return redirect(url_for("results", question_id=question_id))


@app.route("/results/<int:question_id>")
def results(question_id):
    question, choices = question_with_choices(question_id)
    if question is None:
        flash("That poll could not be found.", "warning")
        return redirect(url_for("index"))
    total = sum(choice["votes"] for choice in choices)
    return render_template("results.html", question=question, choices=choices, total=total)


@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    if session.get("admin_id"):
        return redirect(url_for("admin_dashboard"))
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        admin = get_db().execute("SELECT * FROM admins WHERE username = ?", (username,)).fetchone()
        if admin and check_password_hash(admin["password_hash"], password):
            session["admin_id"] = admin["id"]
            session["admin_username"] = admin["username"]
            return redirect(url_for("admin_dashboard"))
        flash("Invalid username or password.", "danger")
    return render_template("admin_login.html")


@app.route("/admin/logout")
def admin_logout():
    session.clear()
    flash("You have been signed out.", "success")
    return redirect(url_for("index"))


@app.route("/admin")
@admin_required
def admin_dashboard():
    questions = get_db().execute("""
        SELECT q.*, COALESCE(SUM(c.votes), 0) AS total_votes, COUNT(c.id) AS choice_count
        FROM questions q LEFT JOIN choices c ON c.question_id = q.id
        GROUP BY q.id ORDER BY q.created_at DESC
    """).fetchall()
    return render_template("admin_dashboard.html", questions=questions)


@app.route("/admin/questions/new", methods=["GET", "POST"])
@admin_required
def create_question():
    if request.method == "POST":
        question = request.form.get("question", "").strip()
        choices = [item.strip() for item in request.form.getlist("choices") if item.strip()]
        if not question or len(choices) < 2:
            flash("Add a question and at least two choices.", "warning")
        else:
            db = get_db()
            cursor = db.execute("INSERT INTO questions (question) VALUES (?)", (question,))
            db.executemany("INSERT INTO choices (question_id, choice_text) VALUES (?, ?)", [(cursor.lastrowid, item) for item in choices])
            db.commit()
            flash("Poll created", "success")
            return redirect(url_for("admin_dashboard"))
    return render_template("question_form.html", question=None, choices=["", ""])


@app.route("/admin/questions/<int:question_id>/edit", methods=["GET", "POST"])
@admin_required
def edit_question(question_id):
    question, choices = question_with_choices(question_id)
    if question is None:
        return redirect(url_for("admin_dashboard"))
    if request.method == "POST":
        text = request.form.get("question", "").strip()
        state = 1 if request.form.get("is_active") else 0
        if not text:
            flash("Question text cannot be empty.", "warning")
        else:
            get_db().execute("UPDATE questions SET question = ?, is_active = ? WHERE id = ?", (text, state, question_id))
            get_db().commit()
            flash("Poll updated.", "success")
            return redirect(url_for("admin_dashboard"))
    return render_template("question_form.html", question=question, choices=choices)


@app.post("/admin/questions/<int:question_id>/toggle")
@admin_required
def toggle_question(question_id):
    get_db().execute("UPDATE questions SET is_active = NOT is_active WHERE id = ?", (question_id,))
    get_db().commit()
    return redirect(url_for("admin_dashboard"))


@app.post("/admin/questions/<int:question_id>/delete")
@admin_required
def delete_question(question_id):
    get_db().execute("DELETE FROM questions WHERE id = ?", (question_id,))
    get_db().commit()
    flash("Poll deleted.", "success")
    return redirect(url_for("admin_dashboard"))


with app.app_context():
    init_db()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)

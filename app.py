import os, sqlite3, csv, io, secrets
from datetime import datetime, date
from functools import wraps
from pathlib import Path
from flask import Flask, render_template, request, redirect, url_for, session, flash, abort, Response
from werkzeug.security import check_password_hash, generate_password_hash

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = Path(os.environ.get("DATA_DIR", str(BASE_DIR / "data")))
DATA_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = DATA_DIR / "fees.db"

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", secrets.token_hex(32))
app.config.update(SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Lax")

DEFAULT_COURSES = [
    ("RSCIT", 3300), ("TALLY", 3500), ("DECE", 7500),
    ("LIBRARY", 0), ("YOGA", 0), ("BA", 0), ("MA", 0),
    ("BCA", 0), ("PGDCA", 13500),
]

def db():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys=ON")
    return con

def init_db():
    with db() as con:
        con.executescript("""
        CREATE TABLE IF NOT EXISTS admins (
            id INTEGER PRIMARY KEY, username TEXT UNIQUE NOT NULL, password_hash TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS courses (
            id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT UNIQUE NOT NULL,
            fee REAL NOT NULL DEFAULT 0, active INTEGER NOT NULL DEFAULT 1
        );
        CREATE TABLE IF NOT EXISTS students (
            id INTEGER PRIMARY KEY AUTOINCREMENT, student_code TEXT UNIQUE NOT NULL,
            name TEXT NOT NULL, father_name TEXT DEFAULT '', mobile TEXT DEFAULT '',
            course_id INTEGER, admission_date TEXT NOT NULL, total_fee REAL NOT NULL DEFAULT 0,
            notes TEXT DEFAULT '', active INTEGER NOT NULL DEFAULT 1,
            FOREIGN KEY(course_id) REFERENCES courses(id)
        );
        CREATE TABLE IF NOT EXISTS payments (
            id INTEGER PRIMARY KEY AUTOINCREMENT, receipt_no TEXT UNIQUE NOT NULL,
            student_id INTEGER NOT NULL, amount REAL NOT NULL, method TEXT NOT NULL,
            reference TEXT DEFAULT '', paid_on TEXT NOT NULL, remarks TEXT DEFAULT '',
            created_at TEXT NOT NULL, FOREIGN KEY(student_id) REFERENCES students(id)
        );
        """)
        # Seed requested courses on both new and existing databases.
        # INSERT OR IGNORE prevents duplicate course names on redeploy.
        con.executemany("INSERT OR IGNORE INTO courses(name,fee) VALUES(?,?)", DEFAULT_COURSES)
        admin_user = os.environ.get("ADMIN_USERNAME", "admin")
        admin_pass = os.environ.get("ADMIN_PASSWORD", "ChangeMe@123")
        if con.execute("SELECT COUNT(*) FROM admins").fetchone()[0] == 0:
            con.execute("INSERT INTO admins(username,password_hash) VALUES(?,?)",
                        (admin_user, generate_password_hash(admin_pass)))

init_db()

def login_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not session.get("admin_id"):
            return redirect(url_for("login", next=request.path))
        return fn(*args, **kwargs)
    return wrapper

def student_balance(con, student_id):
    row = con.execute("""SELECT s.total_fee, COALESCE(SUM(p.amount),0) paid
                         FROM students s LEFT JOIN payments p ON p.student_id=s.id
                         WHERE s.id=? GROUP BY s.id""", (student_id,)).fetchone()
    return float(row["total_fee"]) - float(row["paid"])

@app.context_processor
def inject_globals():
    return {"brand": "Shree Karni Computer & Education", "today": date.today().isoformat()}

@app.route("/")
def home():
    return redirect(url_for("dashboard") if session.get("admin_id") else url_for("login"))

@app.route("/login", methods=["GET","POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username","").strip()
        password = request.form.get("password","")
        with db() as con:
            admin = con.execute("SELECT * FROM admins WHERE username=?", (username,)).fetchone()
        if admin and check_password_hash(admin["password_hash"], password):
            session.clear()
            session["admin_id"] = admin["id"]
            session["username"] = admin["username"]
            return redirect(request.args.get("next") or url_for("dashboard"))
        flash("गलत यूज़रनेम या पासवर्ड।", "danger")
    return render_template("login.html")

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

@app.route("/dashboard")
@login_required
def dashboard():
    with db() as con:
        totals = con.execute("""SELECT
            (SELECT COUNT(*) FROM students WHERE active=1) students,
            (SELECT COALESCE(SUM(total_fee),0) FROM students WHERE active=1) expected,
            (SELECT COALESCE(SUM(amount),0) FROM payments) collected,
            (SELECT COALESCE(SUM(amount),0) FROM payments WHERE paid_on=?) today""", (date.today().isoformat(),)).fetchone()
        pending = float(totals["expected"]) - float(totals["collected"])
        recent = con.execute("""SELECT p.*,s.name,s.student_code FROM payments p
                                JOIN students s ON s.id=p.student_id
                                ORDER BY p.id DESC LIMIT 8""").fetchall()
        dues = con.execute("""SELECT s.id,s.student_code,s.name,s.mobile,s.total_fee,
             COALESCE(SUM(p.amount),0) paid FROM students s LEFT JOIN payments p ON p.student_id=s.id
             WHERE s.active=1 GROUP BY s.id HAVING s.total_fee-paid > 0
             ORDER BY (s.total_fee-paid) DESC LIMIT 8""").fetchall()
    return render_template("dashboard.html", t=totals, pending=pending, recent=recent, dues=dues)

@app.route("/students")
@login_required
def students():
    q = request.args.get("q","").strip()
    with db() as con:
        rows = con.execute("""SELECT s.*,c.name course,
          COALESCE((SELECT SUM(amount) FROM payments p WHERE p.student_id=s.id),0) paid
          FROM students s LEFT JOIN courses c ON c.id=s.course_id
          WHERE s.active=1 AND (s.name LIKE ? OR s.mobile LIKE ? OR s.student_code LIKE ?)
          ORDER BY s.id DESC""", (f"%{q}%",f"%{q}%",f"%{q}%")).fetchall()
        courses = con.execute("SELECT * FROM courses WHERE active=1 ORDER BY name").fetchall()
    return render_template("students.html", students=rows, courses=courses, q=q)

@app.route("/students/add", methods=["POST"])
@login_required
def add_student():
    name=request.form.get("name","").strip()
    if not name:
        flash("विद्यार्थी का नाम जरूरी है।","danger"); return redirect(url_for("students"))
    with db() as con:
        course_id=request.form.get("course_id") or None
        course=con.execute("SELECT * FROM courses WHERE id=?",(course_id,)).fetchone() if course_id else None
        fee=float(request.form.get("total_fee") or (course["fee"] if course else 0))
        code=request.form.get("student_code","").strip() or f"SK{datetime.now():%y%m%d%H%M%S}"
        try:
            con.execute("""INSERT INTO students(student_code,name,father_name,mobile,course_id,admission_date,total_fee,notes)
                VALUES(?,?,?,?,?,?,?,?)""",(code,name,request.form.get("father_name","").strip(),
                request.form.get("mobile","").strip(),course_id,request.form.get("admission_date") or date.today().isoformat(),
                fee,request.form.get("notes","").strip()))
            flash("विद्यार्थी सफलतापूर्वक जोड़ दिया गया।","success")
        except sqlite3.IntegrityError:
            flash("यह Student ID पहले से मौजूद है। दूसरी ID डालें।","danger")
    return redirect(url_for("students"))

@app.route("/students/<int:sid>")
@login_required
def student_detail(sid):
    with db() as con:
        s=con.execute("""SELECT s.*,c.name course FROM students s LEFT JOIN courses c ON c.id=s.course_id WHERE s.id=?""",(sid,)).fetchone()
        if not s: abort(404)
        payments=con.execute("SELECT * FROM payments WHERE student_id=? ORDER BY id DESC",(sid,)).fetchall()
        courses=con.execute("SELECT * FROM courses WHERE active=1 ORDER BY name").fetchall()
        paid=sum(float(p["amount"]) for p in payments)
    return render_template("student_detail.html", s=s, payments=payments, courses=courses, paid=paid, balance=float(s["total_fee"])-paid)

@app.route("/students/<int:sid>/edit", methods=["POST"])
@login_required
def edit_student(sid):
    with db() as con:
        con.execute("""UPDATE students SET name=?,father_name=?,mobile=?,course_id=?,total_fee=?,notes=?
                       WHERE id=?""",(request.form.get("name","").strip(),request.form.get("father_name","").strip(),
            request.form.get("mobile","").strip(),request.form.get("course_id") or None,
            float(request.form.get("total_fee") or 0),request.form.get("notes","").strip(),sid))
    flash("विद्यार्थी का विवरण अपडेट हो गया।","success")
    return redirect(url_for("student_detail",sid=sid))

@app.route("/students/<int:sid>/archive", methods=["POST"])
@login_required
def archive_student(sid):
    with db() as con: con.execute("UPDATE students SET active=0 WHERE id=?",(sid,))
    flash("विद्यार्थी रिकॉर्ड Archive कर दिया गया।","success")
    return redirect(url_for("students"))

@app.route("/payments/add", methods=["POST"])
@login_required
def add_payment():
    sid=request.form.get("student_id","")
    try: amount=float(request.form.get("amount","0"))
    except ValueError: amount=0
    method=request.form.get("method","")
    if amount <= 0 or method not in ("Cash","UPI","Bank"):
        flash("राशि और सही भुगतान माध्यम दर्ज करें।","danger")
        return redirect(request.referrer or url_for("students"))
    with db() as con:
        s=con.execute("SELECT * FROM students WHERE id=?",(sid,)).fetchone()
        if not s: abort(404)
        paid=con.execute("SELECT COALESCE(SUM(amount),0) FROM payments WHERE student_id=?",(sid,)).fetchone()[0]
        if amount > float(s["total_fee"])-float(paid)+0.001:
            flash("जमा राशि बाकी फीस से अधिक है। पहले विद्यार्थी की कुल फीस जाँचें।","danger")
            return redirect(url_for("student_detail",sid=sid))
        receipt=f"SKF-{datetime.now():%y%m%d}-{secrets.token_hex(3).upper()}"
        con.execute("""INSERT INTO payments(receipt_no,student_id,amount,method,reference,paid_on,remarks,created_at)
                       VALUES(?,?,?,?,?,?,?,?)""",(receipt,sid,amount,method,request.form.get("reference","").strip(),
                       request.form.get("paid_on") or date.today().isoformat(),request.form.get("remarks","").strip(),
                       datetime.now().isoformat(timespec="seconds")))
        pid=con.execute("SELECT last_insert_rowid()").fetchone()[0]
    flash("फीस जमा हो गई। रसीद तैयार है।","success")
    return redirect(url_for("receipt",pid=pid))

@app.route("/receipt/<int:pid>")
@login_required
def receipt(pid):
    with db() as con:
        p=con.execute("""SELECT p.*,s.student_code,s.name,s.father_name,s.mobile,s.total_fee,
          c.name course,(SELECT COALESCE(SUM(amount),0) FROM payments x WHERE x.student_id=s.id) paid
          FROM payments p JOIN students s ON s.id=p.student_id
          LEFT JOIN courses c ON c.id=s.course_id WHERE p.id=?""",(pid,)).fetchone()
        if not p: abort(404)
    return render_template("receipt.html",p=p,balance=float(p["total_fee"])-float(p["paid"]))

@app.route("/courses", methods=["GET","POST"])
@login_required
def courses():
    with db() as con:
        if request.method=="POST":
            name=request.form.get("name","").strip()
            try:
                con.execute("INSERT INTO courses(name,fee) VALUES(?,?)",(name,float(request.form.get("fee") or 0)))
                flash("Course जोड़ दिया गया।","success")
            except (sqlite3.IntegrityError,ValueError):
                flash("Course नाम पहले से है या फीस गलत है।","danger")
            return redirect(url_for("courses"))
        rows=con.execute("SELECT * FROM courses ORDER BY active DESC,name").fetchall()
    return render_template("courses.html",courses=rows)

@app.route("/courses/<int:cid>/update", methods=["POST"])
@login_required
def update_course(cid):
    with db() as con:
        con.execute("UPDATE courses SET name=?,fee=? WHERE id=?",
                    (request.form.get("name","").strip(),float(request.form.get("fee") or 0),cid))
    flash("Course अपडेट हो गया।","success")
    return redirect(url_for("courses"))

@app.route("/courses/<int:cid>/toggle", methods=["POST"])
@login_required
def toggle_course(cid):
    with db() as con: con.execute("UPDATE courses SET active=1-active WHERE id=?",(cid,))
    return redirect(url_for("courses"))

@app.route("/reports")
@login_required
def reports():
    start=request.args.get("start",date.today().replace(day=1).isoformat())
    end=request.args.get("end",date.today().isoformat())
    with db() as con:
        rows=con.execute("""SELECT p.*,s.student_code,s.name,s.mobile,c.name course
            FROM payments p JOIN students s ON s.id=p.student_id LEFT JOIN courses c ON c.id=s.course_id
            WHERE p.paid_on BETWEEN ? AND ? ORDER BY p.paid_on DESC,p.id DESC""",(start,end)).fetchall()
        total=sum(float(r["amount"]) for r in rows)
        by_method=con.execute("SELECT method,SUM(amount) amount FROM payments WHERE paid_on BETWEEN ? AND ? GROUP BY method",(start,end)).fetchall()
    return render_template("reports.html",rows=rows,total=total,start=start,end=end,by_method=by_method)

@app.route("/reports/export")
@login_required
def export_csv():
    start=request.args.get("start",date.today().replace(day=1).isoformat())
    end=request.args.get("end",date.today().isoformat())
    with db() as con:
        rows=con.execute("""SELECT p.receipt_no,p.paid_on,s.student_code,s.name,s.mobile,c.name course,
            p.amount,p.method,p.reference,p.remarks FROM payments p JOIN students s ON s.id=p.student_id
            LEFT JOIN courses c ON c.id=s.course_id WHERE p.paid_on BETWEEN ? AND ? ORDER BY p.paid_on""",(start,end)).fetchall()
    out=io.StringIO(); w=csv.writer(out)
    w.writerow(["Receipt No","Date","Student ID","Student Name","Mobile","Course","Amount","Method","Reference","Remarks"])
    for r in rows: w.writerow(list(r))
    return Response("\\ufeff"+out.getvalue(),mimetype="text/csv; charset=utf-8",
                    headers={"Content-Disposition":f"attachment; filename=shree_karni_fees_{start}_{end}.csv"})

@app.route("/backup")
@login_required
def backup():
    return Response(DB_PATH.read_bytes(),mimetype="application/octet-stream",
                    headers={"Content-Disposition":"attachment; filename=shree_karni_fees_backup.db"})

@app.route("/change-password", methods=["GET","POST"])
@login_required
def change_password():
    if request.method=="POST":
        old=request.form.get("old_password",""); new=request.form.get("new_password","")
        if len(new)<8:
            flash("नया पासवर्ड कम से कम 8 अक्षर का रखें।","danger")
        else:
            with db() as con:
                a=con.execute("SELECT * FROM admins WHERE id=?",(session["admin_id"],)).fetchone()
                if a and check_password_hash(a["password_hash"],old):
                    con.execute("UPDATE admins SET password_hash=? WHERE id=?",(generate_password_hash(new),a["id"]))
                    flash("पासवर्ड बदल दिया गया।","success")
                else: flash("पुराना पासवर्ड सही नहीं है।","danger")
    return render_template("change_password.html")

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT",5000)), debug=False)

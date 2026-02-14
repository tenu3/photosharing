from flask import Flask, jsonify, render_template, request, redirect, url_for, flash, session
from flaskext.mysql import MySQL
from flask_bcrypt import Bcrypt
from flaskext.mysql import MySQL
from authlib.integrations.flask_client import OAuth
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash
from pymysql.cursors import DictCursor
from datetime import datetime, timedelta
from uuid import uuid4
from dateutil.relativedelta import relativedelta
from functools import wraps
from dotenv import load_dotenv
import pymysql
import razorpay
import os

# ────────────────────────────────────────────────
#  Imports from your own modules
# ────────────────────────────────────────────────
from db_config import get_db_connection
from utils import get_gallery_path

# ────────────────────────────────────────────────
#  Load environment + monkey-patch
# ────────────────────────────────────────────────
load_dotenv(dotenv_path=".env", override=True)
pymysql.install_as_MySQLdb()

# ────────────────────────────────────────────────
#  App & extensions initialization
# ────────────────────────────────────────────────
app = Flask(__name__)
app.secret_key = "admin123"

mysql = MySQL()
bcrypt = Bcrypt(app)
oauth = OAuth(app)

# ────────────────────────────────────────────────
#  Configuration
# ────────────────────────────────────────────────
UPLOAD_FOLDER = os.path.join("static", "uploads")
ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "webp"}

app.config['MYSQL_DATABASE_HOST']     = '127.0.0.1'
app.config['MYSQL_DATABASE_USER']     = 'root'
app.config['MYSQL_DATABASE_PASSWORD'] = ''
app.config['MYSQL_DATABASE_DB']       = 'photosharing'
app.config['MYSQL_DATABASE_PORT']     = 3307
app.config['MYSQL_CURSOR_CLASS']      = DictCursor
app.config["UPLOAD_FOLDER"]           = UPLOAD_FOLDER

mysql.init_app(app)

# ────────────────────────────────────────────────
#  Razorpay client
# ────────────────────────────────────────────────
razorpay_client = razorpay.Client(
    auth=(os.getenv("RAZORPAY_KEY_ID"), os.getenv("RAZORPAY_KEY_SECRET"))
)

# ────────────────────────────────────────────────
#  Google OAuth registration
# ────────────────────────────────────────────────
oauth.register(
    name="google",
    client_id="307880386393-ticl1bhqs58ou2v7kra6jfjtn2qls30e.apps.googleusercontent.com",
    client_secret="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",
    access_token_url="https://oauth2.googleapis.com/token",
    authorize_url="https://accounts.google.com/o/oauth2/auth",
    api_base_url="https://www.googleapis.com/oauth2/v2/",
    server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
    client_kwargs={
        "scope": "openid email profile"
    }
)

# ────────────────────────────────────────────────
#  Decorators / Helpers
# ────────────────────────────────────────────────
def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def login_required(role="client"):
    def decorator(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            if role == "client" and "client_id" not in session:
                return redirect(url_for("client_login"))
            return f(*args, **kwargs)
        return wrapper
    return decorator


# ────────────────────────────────────────────────
#  PUBLIC / MARKETING PAGES
# ────────────────────────────────────────────────
@app.route('/')
def homepage():
    conn = mysql.connect()
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT id, name, price, storage, duration
        FROM plans
        WHERE status = 'Active'
    """)
    plans = cursor.fetchall()

    cursor.close()
    conn.close()

    return render_template('home.html', plans=plans)


@app.route("/pricing")
def pricing():
    conn = mysql.connect()
    cur = conn.cursor(pymysql.cursors.DictCursor)

    cur.execute("""
        SELECT id, name, price, storage, duration, is_recommended
        FROM plans
        WHERE status = 'Active'
        ORDER BY price ASC
    """)
    plans = cur.fetchall()

    cur.close()
    conn.close()

    return render_template("pricing.html", plans=plans)


@app.route("/demo-gallery")
def demo_gallery():
    return render_template("demo_gallery.html")


@app.route("/examples")
def examples():
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT id, title, cover_photo
        FROM galleries
        WHERE is_public = 1
        ORDER BY created_at DESC
    """)
    galleries = cursor.fetchall()
    conn.close()

    return render_template("client/galleries.html", galleries=galleries)


@app.route("/gallery/<int:gallery_id>")
def view_gallery(gallery_id):
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT id, title FROM galleries WHERE id=%s", (gallery_id,))
    gallery = cursor.fetchone()

    cursor.execute("""
        SELECT photo_path
        FROM photos
        WHERE gallery_id = %s
        ORDER BY id ASC
    """, (gallery_id,))
    photos = cursor.fetchall()

    conn.close()

    return render_template(
        "client/photos.html",
        gallery=gallery,
        photos=photos
    )


@app.route("/photos")
def photos_page():
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT photo_path
        FROM photos
        ORDER BY id DESC
    """)
    photos = cursor.fetchall()

    conn.close()
    return render_template("client/photos.html", photos=photos, gallery={"title": "All Photos"})


# ────────────────────────────────────────────────
#  CLIENT AUTHENTICATION
# ────────────────────────────────────────────────
@app.route("/verify-human")
def verify_human():
    session["human_verified"] = True
    return redirect(url_for("client_register"))


@app.route("/register", methods=["GET", "POST"])
def register():
    if not session.get("human_verified"):
        return redirect(url_for("register"))

    return render_template("register.html")


@app.route("/client/register", methods=["GET", "POST"])
def client_register():
    if request.method == "POST":
        name = request.form.get("name")
        email = request.form.get("email")
        password = request.form.get("password")

        if not session.get("human_verified"):
            return redirect(url_for("verify_human"))

        conn = mysql.connect()
        cursor = conn.cursor()

        cursor.execute(
            "INSERT INTO clients (name, email, password, status) VALUES (%s, %s, %s, 'active')",
            (name, email, password)     # ← note: password should be hashed!
        )
        conn.commit()

        client_id = cursor.lastrowid

        DEFAULT_PLAN_ID = 1
        cursor.execute(
            """
            INSERT INTO client_subscriptions
            (client_id, plan_id, start_date, status)
            VALUES (%s, %s, NOW(), 'active')
            """,
            (client_id, DEFAULT_PLAN_ID)
        )
        conn.commit()

        session["client_id"] = client_id
        session["client_name"] = name

        cursor.close()
        conn.close()

        return redirect(url_for("client_dashboard"))

    return render_template("client/register.html")


@app.route("/client/login", methods=["GET", "POST"])
def client_login():
    if request.method == "POST":
        email = request.form.get("email")
        password = request.form.get("password")

        conn = mysql.connect()
        cursor = conn.cursor()

        cursor.execute(
            "SELECT id, name, password FROM clients WHERE email=%s AND status='active'",
            (email,)
        )
        client = cursor.fetchone()

        cursor.close()
        conn.close()

        if client and bcrypt.check_password_hash(client[2], password):
            session["client_id"] = client[0]
            session["client_name"] = client[1]
            print("✅ Login success:", client[1])
            return redirect(url_for("client_dashboard"))

    return render_template(
        "client/login.html",
        email=session.get("verified_email")
    )


@app.route("/client/forgot-password", methods=["GET", "POST"])
def client_forgot_password():
    if request.method == "POST":
        email = request.form["email"]

        token = str(uuid4())
        expiry = datetime.now() + timedelta(minutes=15)

        conn = mysql.connect()
        cur = conn.cursor(DictCursor)

        cur.execute(
            "UPDATE clients SET reset_token=%s, reset_token_expiry=%s WHERE email=%s",
            (token, expiry, email)
        )

        conn.commit()
        cur.close()
        conn.close()

        reset_link = url_for("client_reset_password", token=token, _external=True)
        print("RESET LINK:", reset_link)

        return render_template("client/forgot_password.html", sent=True)

    return render_template("client/forgot_password.html")


@app.route("/client/reset-password/<token>", methods=["GET", "POST"])
def reset_password(token):
    conn = mysql.connect()
    cursor = conn.cursor(pymysql.cursors.DictCursor)

    cursor.execute(
        "SELECT id, reset_token_expiry FROM clients WHERE reset_token=%s",
        (token,)
    )
    user = cursor.fetchone()

    if not user:
        return render_template("client/reset_password.html", error="Invalid or expired reset link.")

    if user["reset_token_expiry"] < datetime.utcnow():
        return render_template("client/reset_password.html", error="Reset link has expired.")

    if request.method == "POST":
        password = request.form.get("password")
        confirm = request.form.get("confirm")

        if not password or not confirm:
            return render_template("client/reset_password.html", error="All fields are required.")

        if password != confirm:
            return render_template("client/reset_password.html", error="Passwords do not match.")

        if len(password) < 8:
            return render_template("client/reset_password.html", error="Password must be at least 8 characters.")

        hashed_password = bcrypt.generate_password_hash(password).decode("utf-8")

        cursor.execute(
            """
            UPDATE clients
            SET password = %s, reset_token = NULL, reset_token_expiry = NULL
            WHERE id = %s
            """,
            (hashed_password, user["id"])
        )

        conn.commit()
        cursor.close()
        conn.close()

        return render_template("client/reset_password.html", success=True)

    cursor.close()
    conn.close()
    return render_template("client/reset_password.html")


@app.route("/auth/google")
def google_login():
    redirect_uri = url_for("google_callback", _external=True)
    return oauth.google.authorize_redirect(redirect_uri)


@app.route("/auth/google/callback")
def google_callback():
    token = oauth.google.authorize_access_token()
    user_info = oauth.google.get("userinfo").json()

    email = user_info["email"]
    name = user_info.get("name")

    conn = mysql.connect()
    cursor = conn.cursor()

    cursor.execute("SELECT id FROM clients WHERE email = %s", (email,))
    client = cursor.fetchone()

    if not client:
        cursor.execute(
            "INSERT INTO clients (name, email, status) VALUES (%s, %s, 'active')",
            (name, email)
        )
        conn.commit()
        client_id = cursor.lastrowid

        DEFAULT_PLAN_ID = 1
        cursor.execute(
            """
            INSERT INTO client_subscriptions
            (client_id, plan_id, start_date, status)
            VALUES (%s, %s, NOW(), 'active')
            """,
            (client_id, DEFAULT_PLAN_ID)
        )
        conn.commit()
    else:
        client_id = client[0]

        cursor.execute(
            "SELECT id FROM client_subscriptions WHERE client_id = %s",
            (client_id,)
        )
        sub = cursor.fetchone()

        if not sub:
            cursor.execute(
                """
                INSERT INTO client_subscriptions
                (client_id, plan_id, start_date, status)
                VALUES (%s, %s, NOW(), 'active')
                """,
                (client_id, 1)
            )
            conn.commit()

    session["client_id"] = client_id
    session["client_email"] = email
    session["client_name"] = name

    cursor.close()
    conn.close()   # ← missing in original

    return redirect(url_for("client_dashboard"))


@app.route("/client/logout")
def client_logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/logout")
def logout():
    session.clear()
    flash("You have been logged out successfully", "success")
    return redirect(url_for("client_login"))


# ────────────────────────────────────────────────
#  CLIENT DASHBOARD & PROFILE
# ────────────────────────────────────────────────
@app.route("/client/dashboard")
@login_required("client")
def client_dashboard():
    conn = get_db_connection()
    cur = conn.cursor(DictCursor)
    
    client_id = session["client_id"]

    cur.execute("SELECT COUNT(*) AS total_galleries FROM galleries")
    total_galleries = cur.fetchone()["total_galleries"]

    cur.execute("SELECT COUNT(*) AS total_photos FROM photos")
    total_photos = cur.fetchone()["total_photos"]

    cur.execute("""
        SELECT IFNULL(SUM(size_kb), 0) AS total_size_kb
        FROM photos
        WHERE client_id = %s
    """, (client_id,))
    used_kb = cur.fetchone()["total_size_kb"]
    used_gb = round(used_kb / (1024 * 1024), 2)

    cur.execute("""
        SELECT p.storage
        FROM client_subscriptions cs
        JOIN plans p ON cs.plan_id = p.id
        WHERE cs.client_id = %s AND cs.status = 'Active'
        LIMIT 1
    """, (client_id,))
    plan = cur.fetchone()

    total_storage_gb = plan["storage"] if plan else 0
    remaining_gb = round(total_storage_gb - used_gb, 2)

    progress = 0
    if total_storage_gb > 0:
        progress = min(int((used_gb / total_storage_gb) * 100), 100)

    cur.close()
    conn.close()

    return render_template(
        "client/dashboard.html",
        total_galleries=total_galleries,
        total_photos=total_photos,
        storage_used=used_gb,
        total_storage=total_storage_gb,
        remaining_storage=remaining_gb,
        storage_percent=progress
    )


@app.route("/edit-profile")
def edit_profile():
    return render_template("client/edit_profile.html")


# ────────────────────────────────────────────────
#  CLIENT GALLERIES & PHOTOS
# ────────────────────────────────────────────────
@app.route("/client/galleries")
@login_required("client")
def client_galleries():
    client_id = session["client_id"]

    conn = mysql.connect()
    cur = conn.cursor(pymysql.cursors.DictCursor)

    cur.execute("""
        SELECT g.id, g.title,
        COUNT(p.id) AS photo_count,
        MIN(p.photo_path) AS cover_photo
        FROM galleries g
        LEFT JOIN photos p ON g.id = p.gallery_id
        WHERE g.client_id = %s
        GROUP BY g.id
        ORDER BY g.id DESC
    """, (client_id,))

    galleries = cur.fetchall()

    cur.close()
    conn.close()

    return render_template("client/galleries.html", galleries=galleries)


@app.route("/client/create-gallery", methods=["GET", "POST"])
def create_gallery():
    if request.method == "POST":
        title = request.form["title"]
        client_id = session["client_id"]

        folder_path, gallery_slug = get_gallery_path(client_id, title)

        conn = get_db_connection()
        cur = conn.cursor()

        cur.execute(
            "INSERT INTO galleries (title, client_id) VALUES (%s, %s)",
            (title, client_id)
        )

        conn.commit()
        conn.close()

        return redirect(url_for("client_galleries"))

    return render_template("client/create-gallery.html")


@app.route("/client/gallery/<int:gallery_id>/photos")
def gallery_photos(gallery_id):
    conn = mysql.connect()
    cursor = conn.cursor(pymysql.cursors.DictCursor)

    cursor.execute("SELECT * FROM galleries WHERE id = %s", (gallery_id,))
    gallery = cursor.fetchone()

    cursor.execute("""
        SELECT * FROM photos
        WHERE gallery_id = %s
        ORDER BY created_at ASC
    """, (gallery_id,))
    photos = cursor.fetchall()

    cursor.close()
    conn.close()

    return render_template(
        "client/gallery_photos.html",
        gallery=gallery,
        photos=photos
    )


@app.route("/client/gallery/<int:gallery_id>/upload", methods=["POST"])
def upload_gallery_photos(gallery_id):
    files = request.files.getlist("photos")

    if not files:
        return {"error": "No files"}, 400

    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute(
        "SELECT title, client_id FROM galleries WHERE id=%s",
        (gallery_id,)
    )
    gallery = cur.fetchone()

    if not gallery:
        return {"error": "Gallery not found"}, 404

    folder_path, _ = get_gallery_path(gallery["client_id"], gallery["title"])

    for file in files:
        if file.filename == "":
            continue

        filename = secure_filename(file.filename).lower()
        save_path = os.path.join(folder_path, filename)
        file.save(save_path)

        relative_path = save_path.replace("static/", "")

        cur.execute(
            "INSERT INTO photos (gallery_id, client_id, photo_path) VALUES (%s, %s, %s)",
            (gallery_id, gallery["client_id"], relative_path)
        )

        cur.execute(
            "UPDATE galleries SET cover_photo = COALESCE(cover_photo, %s) WHERE id=%s",
            (relative_path, gallery_id)
        )

    conn.commit()
    conn.close()

    return {"success": True}


@app.route("/client/upload-photos/<int:gallery_id>", methods=["POST"])
def upload_photos(gallery_id):
    files = request.files.getlist("photos")

    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)

    cur.execute(
        "SELECT title, client_id FROM galleries WHERE id=%s",
        (gallery_id,)
    )
    gallery = cur.fetchone()

    folder_path, gallery_slug = get_gallery_path(
        gallery["client_id"],
        gallery["title"]
    )

    for file in files:
        if not file.filename:
            continue

        filename = secure_filename(file.filename).lower()
        save_path = os.path.join(folder_path, filename)
        file.save(save_path)

        relative_path = "/".join([
            "uploads",
            f"client_{gallery['client_id']}",
            gallery_slug,
            filename
        ])

        cur.execute("""
            INSERT INTO photos (gallery_id, client_id, photo_path)
            VALUES (%s, %s, %s)
        """, (gallery_id, gallery["client_id"], relative_path))

    conn.commit()
    conn.close()

    return redirect(url_for("view_gallery", gallery_id=gallery_id))


@app.route("/client/gallery/<int:gallery_id>/delete", methods=["POST"])
@login_required("client")
def delete_gallery(gallery_id):
    client_id = session["client_id"]

    conn = mysql.connect()
    cur = conn.cursor()

    cur.execute("DELETE FROM photos WHERE gallery_id=%s AND client_id=%s",
                (gallery_id, client_id))

    cur.execute("DELETE FROM galleries WHERE id=%s AND client_id=%s",
                (gallery_id, client_id))

    conn.commit()
    cur.close()
    conn.close()

    return redirect(url_for("client_galleries"))


@app.route("/client/photo/delete/<int:photo_id>", methods=["POST"])
@login_required("client")
def delete_photo(photo_id):
    client_id = session["client_id"]
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)

    cur.execute("""
        SELECT photo_path
        FROM photos
        WHERE id = %s AND client_id = %s
    """, (photo_id, client_id))
    photo = cur.fetchone()

    if photo:
        file_path = os.path.join("static", *photo["photo_path"].split("/"))

        if os.path.exists(file_path):
            os.remove(file_path)

        cur.execute("DELETE FROM photos WHERE id = %s", (photo_id,))
        conn.commit()

    conn.close()
    return jsonify({"success": True})


# ────────────────────────────────────────────────
#  CLIENT SUBSCRIPTION & PAYMENT
# ────────────────────────────────────────────────
@app.route("/client/plan/<int:plan_id>")
@login_required("client")
def plan_details(plan_id):
    conn = mysql.connect()
    cursor = conn.cursor(DictCursor)

    cursor.execute("""
        SELECT id, name, price, storage, duration
        FROM plans
        WHERE id = %s AND status = 'Active'
    """, (plan_id,))
    
    plan = cursor.fetchone()

    cursor.close()
    conn.close()

    if not plan:
        return redirect(url_for("pricing"))

    return render_template("client/plan_details.html", plan=plan)


@app.route("/client/checkout/<int:plan_id>")
@login_required("client")
def client_checkout(plan_id):
    conn = mysql.connect()
    cursor = conn.cursor(pymysql.cursors.DictCursor)

    cursor.execute("""
        SELECT id, name, price, storage, duration
        FROM plans
        WHERE id = %s AND status = 'Active'
    """, (plan_id,))
    plan = cursor.fetchone()

    cursor.close()
    conn.close()

    if plan["price"] == 0:
        return activate_free_plan(plan["id"])

    return render_template("client/checkout.html", plan=plan)


def activate_free_plan(plan_id):
    client_id = session["client_id"]

    conn = mysql.connect()
    cur = conn.cursor()

    start_date = datetime.now()
    end_date = start_date + relativedelta(months=1)

    cur.execute("""
        INSERT INTO client_subscriptions
        (client_id, plan_id, start_date, end_date, status)
        VALUES (%s, %s, %s, %s, 'Active')
        ON DUPLICATE KEY UPDATE
            plan_id = VALUES(plan_id),
            start_date = VALUES(start_date),
            end_date = VALUES(end_date),
            status = 'Active'
    """, (client_id, plan_id, start_date, end_date))

    conn.commit()
    cur.close()
    conn.close()

    flash("🎉 Free plan activated!", "success")
    return redirect(url_for("client_dashboard"))


@app.route("/client/activate-free/<int:plan_id>")
@login_required("client")
def activate_free_plan_route(plan_id):
    return activate_free_plan(plan_id)


@app.route("/client/pay/razorpay/<int:plan_id>")
@login_required("client")
def razorpay_pay(plan_id):
    conn = mysql.connect()
    cur = conn.cursor(pymysql.cursors.DictCursor)

    cur.execute("SELECT price FROM plans WHERE id=%s", (plan_id,))
    plan = cur.fetchone()

    amount = int(plan["price"] * 100)

    order = razorpay_client.order.create({
        "amount": amount,
        "currency": "INR",
        "payment_capture": 1
    })

    session["selected_plan"] = plan_id

    cur.close()
    conn.close()

    return render_template(
        "client/razorpay_checkout.html",
        order=order,
        razorpay_key=os.getenv("RAZORPAY_KEY_ID")
    )


@app.route("/client/razorpay/success")
@login_required("client")
def razorpay_success():
    payment_id = request.args.get("razorpay_payment_id")
    order_id = request.args.get("razorpay_order_id")
    signature = request.args.get("razorpay_signature")

    if not payment_id:
        flash("Payment failed", "error")
        return redirect(url_for("pricing"))

    client_id = session["client_id"]
    plan_id = session.get("selected_plan")

    conn = mysql.connect()
    cur = conn.cursor(pymysql.cursors.DictCursor)

    cur.execute("SELECT duration FROM plans WHERE id=%s", (plan_id,))
    plan = cur.fetchone()

    duration_months = plan["duration"]
    start_date = datetime.now()
    end_date = start_date + timedelta(days=duration_months * 30)

    cur.execute(
        "UPDATE client_subscriptions SET status='Expired' WHERE client_id=%s",
        (client_id,)
    )

    cur.execute("""
        INSERT INTO client_subscriptions
        (client_id, plan_id, start_date, end_date, status)
        VALUES (%s, %s, %s, %s, 'Active')
    """, (client_id, plan_id, start_date, end_date))

    conn.commit()
    cur.close()
    conn.close()

    session.pop("selected_plan", None)
    
    flash("Payment successful! Plan activated 🎉", "success")
    return redirect(url_for("client_dashboard"))


@app.route("/razorpay-test")
def razorpay_test():
    order = razorpay_client.order.create({
        "amount": 10000,
        "currency": "INR",
        "payment_capture": 1
    })
    return order


# ────────────────────────────────────────────────
#  ADMIN AUTH & DASHBOARD
# ────────────────────────────────────────────────
@app.route('/admin/register', methods=['GET', 'POST'])
def admin_register():
    if request.method == 'POST':
        name = request.form['name']
        email = request.form['email']
        password = request.form['password']

        hashed_password = bcrypt.generate_password_hash(password).decode('utf-8')

        conn = mysql.connect()
        cursor = conn.cursor()

        try:
            cursor.execute(
                "INSERT INTO admin (name, email, password) VALUES (%s, %s, %s)",
                (name, email, hashed_password)
            )
            conn.commit()

            flash("Registration successful. Please login.", "success")
            return redirect(url_for('admin_login'))

        except:
            flash("Email already exists", "danger")

        finally:
            cursor.close()
            conn.close()

    return render_template('admin/register.html')


@app.route('/admin/login', methods=['GET', 'POST'])
def admin_login():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']

        conn = mysql.connect()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM admin WHERE email=%s", (email,))
        admin = cursor.fetchone()

        if admin and bcrypt.check_password_hash(admin[3], password):
            session['admin_logged_in'] = True
            session['admin_id'] = admin[0]
            session['admin_name'] = admin[1]
            return redirect(url_for('admin_dashboard'))
        else:
            flash("Invalid email or password", "danger")

        cursor.close()
        conn.close()

    return render_template('admin/login.html')


@app.route('/admin/logout')
def admin_logout():
    session.clear()
    return redirect(url_for('admin_login'))


@app.route('/admin/dashboard')
def admin_dashboard():
    if not session.get('admin_logged_in'):
        return redirect(url_for('admin_login'))

    conn = mysql.connect()
    cursor = conn.cursor()

    cursor.execute("SELECT COUNT(*) FROM clients")
    total_clients = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM admin WHERE status='active'")
    active_admins = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM subscriptions")
    total_plans = cursor.fetchone()[0]

    cursor.close()
    conn.close()

    return render_template(
        'admin/dashboard.html',
        name=session['admin_name'],
        total_clients=total_clients,
        active_admins=active_admins,
        total_plans=total_plans
    )


@app.route('/admin/stats')
def admin_stats():
    if not session.get('admin_logged_in'):
        return jsonify({'error': 'unauthorized'}), 401

    conn = mysql.connect()
    cursor = conn.cursor()

    cursor.execute("SELECT COUNT(*) FROM clients")
    total_clients = cursor.fetchone()[0] or 0

    cursor.execute("SELECT COUNT(*) FROM admin WHERE status='active'")
    active_admins = cursor.fetchone()[0] or 0

    cursor.execute("SELECT COUNT(*) FROM subscriptions")
    total_plans = cursor.fetchone()[0] or 0

    cursor.close()
    conn.close()

    return {
        "total_clients": total_clients,
        "active_admins": active_admins,
        "total_plans": total_plans
    }


# ────────────────────────────────────────────────
#  ADMIN → MANAGE ADMINS
# ────────────────────────────────────────────────
@app.route('/admin/manage-admins')
def manage_admins():
    if not session.get('admin_logged_in'):
        return redirect(url_for('admin_login'))

    conn = mysql.connect()
    cursor = conn.cursor()

    cursor.execute("SELECT id, name, email, status FROM admin")
    admins = cursor.fetchall()

    cursor.close()
    conn.close()

    return render_template('admin/manage_admins.html', admins=admins)


@app.route('/admin/toggle-admin/<int:id>')
def toggle_admin(id):
    if not session.get('admin_logged_in'):
        return redirect(url_for('admin_login'))

    conn = mysql.connect()
    cursor = conn.cursor()

    cursor.execute("SELECT status FROM admin WHERE id=%s", (id,))
    current_status = cursor.fetchone()[0]

    new_status = 'inactive' if current_status == 'active' else 'active'

    cursor.execute("UPDATE admin SET status=%s WHERE id=%s", (new_status, id))

    conn.commit()
    cursor.close()
    conn.close()

    return redirect(url_for('manage_admins'))


# ────────────────────────────────────────────────
#  ADMIN → MANAGE USERS (CLIENTS)
# ────────────────────────────────────────────────
@app.route('/admin/manage-users')
def manage_users():
    if not session.get('admin_logged_in'):
        return redirect(url_for('admin_login'))

    conn = mysql.connect()
    cursor = conn.cursor()
    cursor.execute("SELECT id, name, business_name, email, phone, status FROM clients")
    users = cursor.fetchall()
    cursor.close()
    conn.close()

    return render_template('admin/manage_users.html', users=users)


@app.route('/admin/toggle-user/<int:id>')
def toggle_user(id):
    if not session.get('admin_logged_in'):
        return redirect(url_for('admin_login'))

    conn = mysql.connect()
    cursor = conn.cursor()

    cursor.execute("SELECT status FROM clients WHERE id=%s", (id,))
    current_status = cursor.fetchone()[0]

    new_status = 'inactive' if current_status == 'active' else 'active'

    cursor.execute("UPDATE clients SET status=%s WHERE id=%s", (new_status, id))

    conn.commit()
    cursor.close()
    conn.close()

    return redirect(url_for('manage_users'))


# ────────────────────────────────────────────────
#  ADMIN → MANAGE PLANS / SUBSCRIPTIONS
# ────────────────────────────────────────────────
@app.route('/admin/plans')
def admin_plans():
    if 'admin_id' not in session:
        return redirect(url_for('login'))

    conn = mysql.connect()
    cur = conn.cursor()

    cur.execute("SELECT * FROM plans")
    plans = cur.fetchall()

    cur.close()
    conn.close()

    return render_template('admin/plans.html', plans=plans)


@app.route('/admin/plans/edit/<int:id>', methods=['GET', 'POST'])
def edit_plan(id):
    if 'admin_id' not in session:
        return redirect(url_for('login'))

    conn = mysql.connect()
    cur = conn.cursor()

    if request.method == 'POST':
        name = request.form['name']
        price = request.form['price']
        storage = request.form['storage']
        duration = request.form['duration']
        status = request.form['status']
        recommended = request.form.get('recommended', 0)

        cur.execute("""
            UPDATE plans
            SET name=%s, price=%s, storage=%s,
                duration=%s, status=%s, is_recommended=%s
            WHERE id=%s
        """, (name, price, storage, duration, status, recommended, id))

        conn.commit()
        cur.close()
        conn.close()

        return redirect(url_for('admin_plans'))

    cur.execute("SELECT * FROM plans WHERE id=%s", (id,))
    plan = cur.fetchone()

    cur.close()
    conn.close()

    return render_template('admin/edit_plan.html', plan=plan)


@app.route('/admin/manage-subscriptions')
def manage_subscriptions():
    if not session.get('admin_logged_in'):
        return redirect(url_for('admin_login'))

    conn = mysql.connect()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT id, name, price, size, duration, status
        FROM subscriptions
    """)
    plans = cursor.fetchall()

    cursor.close()
    conn.close()

    return render_template('admin/manage_subscriptions.html', plans=plans)


@app.route('/admin/edit-subscription/<int:id>', methods=['GET', 'POST'])
def edit_subscription(id):
    if not session.get('admin_logged_in'):
        return redirect(url_for('admin_login'))

    conn = mysql.connect()
    cursor = conn.cursor(pymysql.cursors.DictCursor)

    cursor.execute("SELECT * FROM subscriptions WHERE id=%s", (id,))
    plan = cursor.fetchone()

    if not plan:
        cursor.close()
        conn.close()
        return redirect(url_for('manage_subscriptions'))

    if request.method == 'POST':
        name = request.form['name']
        price = request.form['price']
        size = request.form['size']
        duration = request.form['duration']
        features = request.form['features']

        cursor.execute("""
            UPDATE subscriptions
            SET name=%s, price=%s, size=%s, duration=%s, features=%s
            WHERE id=%s
        """, (name, price, size, duration, features, id))

        conn.commit()
        cursor.close()
        conn.close()

        flash("Subscription updated successfully", "success")
        return redirect(url_for('manage_subscriptions'))

    cursor.close()
    conn.close()
    return render_template('admin/edit_subscription.html', plan=plan)


@app.route('/admin/add-subscription', methods=['GET', 'POST'])
def add_subscription():
    if not session.get('admin_logged_in'):
        return redirect(url_for('admin_login'))

    if request.method == 'POST':
        name = request.form['name']
        price = request.form['price']
        size = request.form['size']
        duration = request.form['duration']
        features = request.form['features']

        conn = mysql.connect()
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO subscriptions (name, price, size, duration, features)
            VALUES (%s, %s, %s, %s, %s)
        """, (name, price, size, duration, features))
        conn.commit()
        flash("a new plan had been sucessfully added.", "success")

        cursor.close()
        conn.close()

        return redirect(url_for('manage_subscriptions'))   # ← was render_template → fixed

    return render_template('admin/add_subscription.html')


@app.route('/admin/toggle-subscription/<int:id>')
def toggle_subscription(id):
    if not session.get('admin_logged_in'):
        return redirect(url_for('admin_login'))

    conn = mysql.connect()
    cursor = conn.cursor()

    cursor.execute("SELECT status FROM subscriptions WHERE id=%s", (id,))
    current_status = cursor.fetchone()[0]

    new_status = 'inactive' if current_status == 'active' else 'active'

    cursor.execute("UPDATE subscriptions SET status=%s WHERE id=%s", (new_status, id))

    conn.commit()
    cursor.close()
    conn.close()

    return redirect(url_for('manage_subscriptions'))


# ────────────────────────────────────────────────
#  LEGACY / UNUSED / DUPLICATED ROUTES
#   (kept for compatibility – consider removing later)
# ────────────────────────────────────────────────
@app.route("/login")
def login_redirect():
    return redirect(url_for("client_login"))


@app.route('/payment-success/<int:plan_id>', methods=['POST'])
def payment_success(plan_id):
    # ← seems unused / legacy – table client_plans not used elsewhere
    client_id = session.get('client_id')
    if not client_id:
        return redirect(url_for('login'))

    conn = mysql.connect()
    cur = conn.cursor()

    cur.execute("SELECT duration FROM plans WHERE id=%s", (plan_id,))
    plan = cur.fetchone()

    duration = plan[0]
    start_date = datetime.date.today()
    end_date = start_date + relativedelta(months=duration)

    cur.execute("DELETE FROM client_plans WHERE client_id=%s", (client_id,))

    cur.execute("""
        INSERT INTO client_plans (client_id, plan_id, start_date, end_date)
        VALUES (%s, %s, %s, %s)
    """, (client_id, plan_id, start_date, end_date))

    conn.commit()
    cur.close()
    conn.close()

    return redirect(url_for('client_dashboard'))


if __name__ == "__main__":
    app.run(debug=True)
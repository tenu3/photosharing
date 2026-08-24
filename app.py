from flask import Flask, jsonify, render_template, request, redirect, url_for, flash, session, send_from_directory
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
import os
import cv2
import numpy as np
from PIL import Image
from skimage.metrics import structural_similarity as ssim
import os
import razorpay

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

import os
from dotenv import load_dotenv

load_dotenv()

RAZORPAY_KEY_ID = os.getenv("RAZORPAY_KEY_ID")
RAZORPAY_KEY_SECRET = os.getenv("RAZORPAY_KEY_SECRET")

mysql.init_app(app)

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



razorpay_client = razorpay.Client(auth=(RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET))

def login_required(role="client"):
    def decorator(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            if role == "client" and "client_id" not in session:
                return redirect(url_for("client_login"))
            return f(*args, **kwargs)
        return wrapper
    return decorator


@app.route("/")
def homepage():
    conn = mysql.connect()
    cursor = conn.cursor(pymysql.cursors.DictCursor)

    # Plans (already working)
    cursor.execute("""
        SELECT id, name, price,storage, duration
        FROM plans
        WHERE status = 'active'
    """)
    plans = cursor.fetchall()

    # 🔥 ADD THIS: Featured galleries with cover photo
    cursor.execute("""
        SELECT * FROM galleries
        WHERE is_public = 1
        ORDER BY id DESC
        LIMIT 8
    """)
    galleries = cursor.fetchall()

    demo_galleries = [
        {"title": "Wedding Moments", "image": "demo/wedding.jpg"},
        {"title": "Food & Lifestyle", "image": "demo/food.jpg"},
        {"title": "Concert Nights", "image": "demo/event.jpg"},
        {"title": "Travel Diaries", "image": "demo/travel.jpg"},
        {"title": "Zoo", "image": "demo/animals.jpg"},
        
    ]
    cursor.close()
    conn.close()

    return render_template(
        "home.html",
        demo_galleries=demo_galleries,   # 👈 THIS WAS MISSING
        current_year=datetime.now().year
    )

@app.route("/demo")
def demo_gallery():
    conn = mysql.connect()
    cursor = conn.cursor(pymysql.cursors.DictCursor)

    # get any one gallery as demo
    cursor.execute("""
        SELECT * FROM galleries
        ORDER BY id DESC
        LIMIT 1
    """)
    gallery = cursor.fetchone()

    if not gallery:
        cursor.close()
        conn.close()
        return "No demo gallery available"

    # get photos
    cursor.execute("""
        SELECT * FROM photos
        WHERE gallery_id = %s
    """, (gallery["id"],))
    photos = cursor.fetchall()

    cursor.close()
    conn.close()

    return render_template(
        "/public/gallery_view.html",
        gallery=gallery,
        photos=photos
    )

@app.route("/features/<feature>")
def feature_deeplink(feature):
    return render_template(
        "home.html",
        is_client_logged_in="client_id" in session,
        open_feature=feature
    )




@app.route("/pricing")
def pricing():
    conn = mysql.connect()
    cursor = conn.cursor(pymysql.cursors.DictCursor)

    cursor.execute("SELECT * FROM plans WHERE status='active' ORDER BY id")
    plans = cursor.fetchall()

    cursor.close()
    conn.close()

    return render_template(
        "client/plans.html",   # same template as client upgrade
        plans=plans,
        page_title="Choose Your Plan"
    )

@app.route("/examples")
def examples_page():
    conn = mysql.connect()
    cursor = conn.cursor(pymysql.cursors.DictCursor)

    cursor.execute("""
        SELECT id, title, cover_photo
        FROM galleries
        WHERE is_public = 1
        ORDER BY id DESC
    """)
    galleries = cursor.fetchall()

    cursor.close()
    conn.close()

    return render_template("examples.html", galleries=galleries)


@app.route("/client/gallery/<int:gallery_id>")
@login_required("client")
def view_gallery(gallery_id):
    client_id = session["client_id"]

    conn = mysql.connect()
    cursor = conn.cursor(pymysql.cursors.DictCursor)

    cursor.execute("""
        SELECT id, title, cover_photo
        FROM galleries
        WHERE id=%s AND client_id=%s
    """, (gallery_id, client_id))
    gallery = cursor.fetchone()

    cursor.close()
    conn.close()

    if not gallery:
        return "Gallery not found",404

    return render_template(
        "client/gallery.html",
        gallery=gallery,
        gallery_id=gallery_id
    )


@app.route("/uploads/<path:filename>")
def uploaded_file(filename):
    return send_from_directory("uploads", filename)


@app.route("/photos")
def photos_page():
    conn = mysql.connect()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT photo_path
        FROM photos
        ORDER BY id DESC
    """)
    photos = cursor.fetchall()

    conn.close()
    return render_template("client/photos.html", photos=photos, gallery={"title": "All Photos"})
@app.route("/gallery/photo/<int:photo_id>/like", methods=["POST"])
def public_like(photo_id):
    try:
        client_id = session.get("client_id")

        # 🚨 must be logged in
        if not client_id:
            return jsonify({
                "success": False,
                "message": "Login required"
            }), 401

        conn = mysql.connect()
        cursor = conn.cursor(pymysql.cursors.DictCursor)

        # ✅ check if already liked
        cursor.execute("""
            SELECT id FROM photo_likes
            WHERE photo_id=%s AND client_id=%s
        """, (photo_id, client_id))

        existing = cursor.fetchone()

        if existing:
            # ❌ UNLIKE (toggle)
            cursor.execute("""
                DELETE FROM photo_likes
                WHERE photo_id=%s AND client_id=%s
            """, (photo_id, client_id))
            liked = False
        else:
            # ❤️ LIKE
            cursor.execute("""
                INSERT INTO photo_likes (photo_id, client_id, created_at)
                VALUES (%s, %s, NOW())
            """, (photo_id, client_id))
            liked = True

        conn.commit()

        # ✅ return updated count
        cursor.execute("""
            SELECT COUNT(*) AS total
            FROM photo_likes
            WHERE photo_id=%s
        """, (photo_id,))
        count = cursor.fetchone()["total"]

        return jsonify({
            "success": True,
            "liked": liked,
            "count": count
        })

    except Exception as e:
        print("LIKE ERROR:", e)
        return jsonify({"success": False}), 500

    finally:
        cursor.close()
        conn.close()
# ===============================
# FAVORITE TOGGLE (PUBLIC)
# ===============================
@app.route("/favorite/toggle", methods=["POST"])
def toggle_favorite():
    data = request.get_json()

    photo_id = data.get("photo_id")
    email = data.get("email")

    if not photo_id or not email:
        return {"success": False, "error": "Missing data"}, 400

    conn = mysql.connect()
    cursor = conn.cursor(pymysql.cursors.DictCursor)

    # 🔍 check if already exists
    cursor.execute("""
        SELECT id FROM favorites
        WHERE photo_id=%s AND email=%s
    """, (photo_id, email))

    existing = cursor.fetchone()

    if existing:
        # ❌ remove favorite (toggle off)
        cursor.execute("""
            DELETE FROM favorites
            WHERE id=%s
        """, (existing["id"],))
        favorited= "False"
    else:
        # ✅ add favorite
        cursor.execute("""
            INSERT INTO favorites (photo_id, email)
            VALUES (%s, %s)
        """, (photo_id, email))
        favorited = "True"
        # ⭐ GET LIVE COUNT
    cursor.execute("""
        SELECT COUNT(*) AS total
        FROM favorites
        WHERE photo_id=%s
    """, (photo_id,))
    count = cursor.fetchone()["total"]    

    conn.commit()
    cursor.close()
    conn.close()

    return {"success": True, "favorited": favorited, "count": count}

@app.route("/proof/toggle", methods=["POST"])
def toggle_proof():
    data = request.get_json()

    photo_id = data.get("photo_id")
    email = data.get("email")

    if not photo_id or not email:
        return {"success": False}

    conn = mysql.connect()
    cursor = conn.cursor()

    # check existing
    cursor.execute("""
        SELECT id FROM photo_proofs
        WHERE photo_id=%s AND client_email=%s
    """, (photo_id, email))

    existing = cursor.fetchone()

    if existing:
        cursor.execute("""
            DELETE FROM photo_proofs
            WHERE photo_id=%s AND client_email=%s
        """, (photo_id, email))
        selected = False
    else:
        cursor.execute("""
            INSERT INTO photo_proofs (photo_id, gallery_id, client_email)
            SELECT id, gallery_id, %s
            FROM photos WHERE id=%s
        """, (email, photo_id))
        selected = True

    conn.commit()
    cursor.close()
    conn.close()

    return {"success": True, "selected": selected}

@app.route("/gallery/<int:gallery_id>/proof-count")
def proof_count(gallery_id):
    email = request.args.get("email")

    conn = mysql.connect()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT COUNT(*)
        FROM photo_proofs
        WHERE gallery_id=%s AND client_email=%s
    """, (gallery_id, email))

    count = cursor.fetchone()[0]

    cursor.close()
    conn.close()

    return {"count": count}

@app.route("/photo/<int:photo_id>/download", methods=["POST"])
def download_photo(photo_id):
    try:
        data = request.get_json()
        email = data.get("email")

        conn = mysql.connect()
        cursor = conn.cursor(pymysql.cursors.DictCursor)

        # get photo
        cursor.execute("""
            SELECT photo_path, original_name, gallery_id
            FROM photos
            WHERE id=%s
        """, (photo_id,))
        photo = cursor.fetchone()

        if not photo:
            return jsonify({"success": False})

        # ⭐ INSERT DOWNLOAD ANALYTICS
        cursor.execute("""
            INSERT INTO photo_downloads
            (photo_id, gallery_id, email, ip_address)
            VALUES (%s, %s, %s, %s)
        """, (
            photo_id,
            photo["gallery_id"],
            email,
            request.remote_addr
        ))

        conn.commit()
        cursor.close()
        conn.close()

        return jsonify({
            "success": True,
            "file": url_for(
                "static",
                filename=photo["photo_path"]
            )
        })

    except Exception as e:
        print("Download error:", e)
        return jsonify({"success": False})
# ===============================
# VERIFY DOWNLOAD PIN
# ===============================
@app.route("/gallery/<int:gallery_id>/verify-download", methods=["POST"])
def verify_download(gallery_id):
    data = request.get_json()
    pin = data.get("pin")

    conn = mysql.connect()
    cur = conn.cursor(pymysql.cursors.DictCursor)

    cur.execute(
        "SELECT download_pin FROM galleries WHERE id=%s",
        (gallery_id,)
    )
    gallery = cur.fetchone()

    cur.close()
    conn.close()

    if gallery and gallery["download_pin"] == pin:
        return jsonify({"success": True})
    else:
        return jsonify({"success": False})


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
    error = None
    client = None   # ✅ IMPORTANT FIX

    if request.method == "POST":
        email = request.form["email"]
        password = request.form["password"]

        conn = mysql.connect()
        cursor = conn.cursor()

        cursor.execute(
            "SELECT id, email, password FROM clients WHERE email=%s",
            (email,)
        )
        client = cursor.fetchone()

        cursor.close()
        conn.close()

        if client and bcrypt.check_password_hash(client[2], password):
            session["client_id"] = client[0]
            session["client_email"] = client[1]
            return redirect(url_for("client_dashboard"))
        else:
            error = "Invalid email or password"

    return render_template("client/login.html", error=error)



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
    session.pop("client_id", None)
    session.pop("client_name", None)
    return redirect(url_for("homepage"))



# ────────────────────────────────────────────────
#  CLIENT DASHBOARD & PROFILE
# ────────────────────────────────────────────────
@app.route("/client/dashboard")
@login_required("client")
def client_dashboard():
    client_id = session["client_id"]

    conn = mysql.connect()
    cursor = conn.cursor(pymysql.cursors.DictCursor)

    # ---------------------------
    # Total Galleries
    # ---------------------------
    cursor.execute("""
        SELECT COUNT(*) AS total
        FROM galleries
        WHERE client_id = %s
    """, (client_id,))
    total_galleries = cursor.fetchone()["total"]

    # ---------------------------
    # Total Photos
    # ---------------------------
    cursor.execute("""
        SELECT COUNT(p.id) AS total
        FROM photos p
        JOIN galleries g ON p.gallery_id = g.id
        WHERE g.client_id = %s
    """, (client_id,))
    total_photos = cursor.fetchone()["total"]

    # ---------------------------
    # Total Favorites
    # ---------------------------
    cursor.execute("""
        SELECT COUNT(*) AS total
        FROM favorites f
        JOIN photos p ON f.photo_id = p.id
        JOIN galleries g ON p.gallery_id = g.id
        WHERE g.client_id = %s
    """, (client_id,))
    total_favorites = cursor.fetchone()["total"]
   # total downloads
    cursor.execute("""
      SELECT COUNT(*) AS total
      FROM photo_downloads pd
      JOIN galleries g ON pd.gallery_id = g.id
      WHERE g.client_id = %s
      """, (client_id,))

    total_downloads = cursor.fetchone()["total"]

    # ---------------------------
    # Expire old subscriptions
    # ---------------------------
    cursor.execute("""
        UPDATE client_subscriptions
        SET status='expired'
        WHERE end_date < CURDATE()
        AND client_id=%s
    """, (client_id,))
    conn.commit()

    # ---------------------------
    # Get ACTIVE plan
    # ---------------------------
    cursor.execute("""
        SELECT cs.*, p.name, p.storage
        FROM client_subscriptions cs
        JOIN plans p ON cs.plan_id = p.id
        WHERE cs.client_id=%s
        AND cs.status='active'
        ORDER BY cs.end_date DESC
        LIMIT 1
    """, (client_id,))
    current_plan = cursor.fetchone()

    # ---------------------------
    # STORAGE USED (⭐ FIXED)
    # ---------------------------
    cursor.execute("""
        SELECT SUM(p.file_size) AS total_storage
        FROM photos p
        JOIN galleries g ON p.gallery_id = g.id
        WHERE g.client_id = %s
    """, (client_id,))
    storage_data = cursor.fetchone()

    total_storage_bytes = storage_data["total_storage"] or 0

    # Convert bytes → GB
    total_storage_gb = round(total_storage_bytes / (1024 * 1024 * 1024), 2)

    # ---------------------------
    # PLAN LIMIT + %
    # ---------------------------
    if current_plan and current_plan["storage"]:
        plan_limit_gb = current_plan["storage"]
        storage_percent = round(
            (total_storage_gb / plan_limit_gb) * 100, 2
        )
    else:
        plan_limit_gb = 5  # fallback free limit
        storage_percent = 0

    cursor.close()
    conn.close()

    return render_template(
        "client/dashboard.html",
        total_galleries=total_galleries,
        total_photos=total_photos,
        total_favorites=total_favorites,
        total_downloads=total_downloads,
        total_storage_gb=total_storage_gb,
        plan_limit_gb=plan_limit_gb,
        storage_percent=storage_percent
    )


 # adjust import according to your structure

# ─── PLANS LIST (unchanged, but good to have) ───
@app.route("/client/plans")
@login_required("client")
def client_plans():
    conn = mysql.connect()
    cursor = conn.cursor(pymysql.cursors.DictCursor)

    cursor.execute("SELECT * FROM plans WHERE status = 'Active' ORDER BY price ASC")
    plans = cursor.fetchall()

    client_id = session["client_id"]
    cursor.execute("""
        SELECT p.name, p.storage AS storage, cs.end_date
        FROM client_subscriptions cs
        JOIN plans p ON cs.plan_id = p.id
        WHERE cs.client_id = %s 
          AND cs.status = 'active'
          AND (cs.end_date IS NULL OR cs.end_date >= CURDATE())
        LIMIT 1
    """, (client_id,))
    current_plan = cursor.fetchone()

    cursor.close()
    conn.close()

    return render_template(
        "client/plans.html",
        plans=plans,
        current_plan=current_plan,
        page_title="Choose a Plan",
        razorpay_key_id=RAZORPAY_KEY_ID   # ← pass to template if needed
    )

@app.route("/client/purchase/<int:plan_id>", methods=["GET"])
@login_required("client")
def purchase_plan(plan_id):
    conn = mysql.connect()
    cursor = conn.cursor(pymysql.cursors.DictCursor)

    # Get plan
    cursor.execute("""
        SELECT id, name, price, duration, storage AS storage, is_recommended 
        FROM plans 
        WHERE id = %s AND status = 'Active'
    """, (plan_id,))
    plan = cursor.fetchone()

    if not plan:
        cursor.close()
        conn.close()
        flash("Plan not found or inactive.", "danger")
        return redirect(url_for("client_plans"))

    # Get current logged-in client details
    client_id = session["client_id"]
    cursor.execute("""
        SELECT name, email, phone 
        FROM clients 
        WHERE id = %s AND status = 'active'
        LIMIT 1
    """, (client_id,))
    client = cursor.fetchone()

    cursor.close()
    conn.close()

    if not client:
        flash("Client account not found or inactive.", "danger")
        return redirect(url_for("client_plans"))

    # Convert price to paise
    amount_paise = int(plan["price"] * 100)

    # Create Razorpay Order
    try:
        order_data = {
            "amount": amount_paise,
            "currency": "INR",
            "receipt": f"plan_{plan_id}_client_{client_id}_{int(time.time())}",  # better uniqueness
            "notes": {
                "plan_id": plan_id,
                "client_id": client_id
            }
        }
        razorpay_order = razorpay_client.order.create(order_data)
        order_id = razorpay_order["id"]
    except Exception as e:
        flash(f"Error creating payment order: {str(e)}", "danger")
        return redirect(url_for("client_plans"))

    return render_template(
        "client/purchase-confirm.html",
        plan=plan,
        client=client,                    # ← pass client dict to template
        razorpay_order_id=order_id,
        razorpay_key_id=RAZORPAY_KEY_ID,
        amount_paise=amount_paise,
        page_title=f"Pay for {plan['name']}"
    )
    
# ─── STEP 2: Verify payment & activate plan (called after checkout) ───
@app.route("/client/payment-verification", methods=["POST"])
@login_required("client")
def payment_verification():
    client_id = session.get("client_id")
    data = request.form

    if not data.get("razorpay_payment_id") or not data.get("razorpay_order_id") or not data.get("razorpay_signature"):
        flash("Payment details missing.", "danger")
        return redirect(url_for("client_plans"))

    try:
        # Verify signature
        razorpay_client.utility.verify_payment_signature({
            "razorpay_order_id": data["razorpay_order_id"],
            "razorpay_payment_id": data["razorpay_payment_id"],
            "razorpay_signature": data["razorpay_signature"]
        })

        # Signature valid → payment success
        # Get plan_id from order (you can also fetch from razorpay_order notes)
        # For simplicity — we assume you pass it or fetch from DB

        # You should ideally capture payment here if payment_capture='0'
        # razorpay_client.payment.capture(payment_id, amount)

        # Now activate plan (same logic as before)
        conn = mysql.connect()
        cursor = conn.cursor(pymysql.cursors.DictCursor)

        # Get plan_id — best way: store it temporarily or fetch from order notes via API
        # For now — assume you pass plan_id in hidden field or session
        plan_id = request.form.get("plan_id")  # add this hidden field!

        if not plan_id:
            raise ValueError("Plan ID missing")

        cursor.execute("SELECT id, name, duration, storage FROM plans WHERE id = %s AND status = 'Active'", (plan_id,))
        plan = cursor.fetchone()

        if not plan:
            raise ValueError("Plan not found")

        # Deactivate old plans
        cursor.execute("""
            UPDATE client_subscriptions 
            SET status = 'expired' 
            WHERE client_id = %s AND status = 'active'
        """, (client_id,))

        # Activate new one
        cursor.execute("""
            INSERT INTO client_subscriptions 
            (client_id, plan_id, start_date, end_date, status,
             payment_id, payment_provider)
            VALUES 
            (%s, %s, CURDATE(), DATE_ADD(CURDATE(), INTERVAL %s DAY), 'active',
             %s, 'razorpay')
        """, (client_id, plan_id, plan["duration"], data["razorpay_payment_id"]))

        conn.commit()
        cursor.close()
        conn.close()

        flash(f"🎉 {plan['name']} activated successfully! Payment ID: {data['razorpay_payment_id']}", "success")
        return redirect(url_for("client_dashboard"))

    except razorpay.errors.SignatureVerificationError:
        flash("Payment signature verification failed. Please contact support.", "danger")
        return redirect(url_for("client_plans"))
    except Exception as e:
        flash(f"Payment processing error: {str(e)}", "danger")
        return redirect(url_for("client_plans"))
    
#__________________________________________________________
@app.route("/edit-profile")
def edit_profile():
    return render_template("client/edit_profile.html")

@app.route("/client/collections")
@login_required("client")
def client_collections():
    client_id = session["client_id"]

    conn = mysql.connect()
    cursor = conn.cursor(pymysql.cursors.DictCursor)

    cursor.execute("""
        SELECT 
            g.id,
            g.title,
            g.cover_photo,
            COUNT(p.id) AS photo_count
        FROM galleries g
        LEFT JOIN photos p ON g.id = p.gallery_id
        WHERE g.client_id = %s
        GROUP BY g.id
        ORDER BY g.created_at DESC
    """, (client_id,))

    galleries = cursor.fetchall()

    cursor.close()
    conn.close()

    return render_template(
        "client/collections.html",
        galleries=galleries
    )

#______________________________________________________
from flask import flash, redirect, url_for, render_template, request, session
from werkzeug.utils import secure_filename
import os
import pymysql
from datetime import datetime

# Assuming these are defined at module level or in config
UPLOAD_FOLDER = os.path.join("static", "uploads")
ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "webp"}


def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


@app.route("/client/gallery/<int:gallery_id>/manage", methods=["GET", "POST"])
@login_required("client")  # ← your custom decorator
def manage_gallery(gallery_id):
    client_id = session.get("client_id")
    
    # Extra safety in case session was tampered with or expired
    if not client_id:
        flash("Please log in to continue.", "danger")
        return redirect(url_for("client_login"))  # ← adjust to your actual login route name

    conn = mysql.connect()
    cursor = conn.cursor(pymysql.cursors.DictCursor)

    # 1. Verify ownership
    cursor.execute("""
        SELECT id, title, description, cover_photo, is_public
        FROM galleries
        WHERE id = %s AND client_id = %s
    """, (gallery_id, client_id))
    gallery = cursor.fetchone()

    if not gallery:
        cursor.close()
        conn.close()
        flash("Gallery not found or access denied.", "danger")
        return redirect(url_for("client_collections"))

    # 2. Handle form submissions
    if request.method == "POST":
        action = request.form.get("action")

        try:
            if action == "update_details":
                title = (request.form.get("title") or "").strip()
                description = (request.form.get("description") or "").strip()
                is_public = 1 if request.form.get("is_public") else 0   # checkbox sends "on" or nothing

                cover_photo_path = gallery["cover_photo"]

                if "cover_photo" in request.files:
                    file = request.files["cover_photo"]
                    if file and file.filename and allowed_file(file.filename):
                        filename = secure_filename(file.filename)
                        client_folder = os.path.join(UPLOAD_FOLDER, f"client_{client_id}")
                        os.makedirs(client_folder, exist_ok=True)
                        save_path = os.path.join(client_folder, filename)
                        file.save(save_path)
                        cover_photo_path = f"/{save_path.replace(os.sep, '/')}"

                cursor.execute("""
                    UPDATE galleries
                    SET title = %s, description = %s, is_public = %s, cover_photo = %s
                    WHERE id = %s
                """, (title, description, is_public, cover_photo_path, gallery_id))
                conn.commit()
                flash("Gallery details updated.", "success")

            elif action == "upload_photos":
                files = request.files.getlist("photos")
                uploaded_count = 0
                client_folder = os.path.join(UPLOAD_FOLDER, f"client_{client_id}")
                os.makedirs(client_folder, exist_ok=True)

                for file in files:
                    if not file or not file.filename or not allowed_file(file.filename):
                        continue

                    filename = secure_filename(file.filename)
                    save_path = os.path.join(client_folder, filename)

                    # Prevent overwriting existing files (simple version)
                    base, ext = os.path.splitext(filename)
                    counter = 1
                    while os.path.exists(save_path):
                        save_path = os.path.join(client_folder, f"{base}_{counter}{ext}")
                        counter += 1

                    file.save(save_path)
                    relative_path = f"/{save_path.replace(os.sep, '/')}"

                    file_size_bytes = os.path.getsize(save_path) // 1024

                    cursor.execute("""
                        INSERT INTO photos
                        (client_id, gallery_id, filename, original_name, photo_path, file_size, created_at)
                        VALUES (%s, %s, %s, %s, %s, %s, %s)
                    """, (
                        client_id,
                        gallery_id,
                        os.path.basename(save_path),   # may include counter suffix
                        file.filename,                 # original name from user
                        relative_path,
                        file_size_bytes,
                        datetime.now()
                    ))
                    uploaded_count += 1

                if uploaded_count > 0:
                    conn.commit()
                    flash(f"{uploaded_count} photo{'s' if uploaded_count != 1 else ''} uploaded.", "success")
                else:
                    flash("No valid photos were uploaded.", "warning")

            elif action == "delete_photos":
                photo_ids = request.form.getlist("photo_ids")
                deleted_count = 0

                for pid_str in photo_ids:
                    try:
                        pid = int(pid_str)
                        cursor.execute("""
                            SELECT photo_path FROM photos 
                            WHERE id = %s AND gallery_id = %s AND client_id = %s
                        """, (pid, gallery_id, client_id))
                        row = cursor.fetchone()

                        if row and row["photo_path"]:
                            full_path = row["photo_path"].lstrip("/").replace("/", os.sep)
                            if os.path.exists(full_path):
                                os.remove(full_path)
                            cursor.execute("DELETE FROM photos WHERE id = %s", (pid,))
                            deleted_count += 1
                    except (ValueError, OSError):
                        continue

                if deleted_count > 0:
                    conn.commit()
                    flash(f"{deleted_count} photo{'s' if deleted_count != 1 else ''} deleted.", "success")
                else:
                    flash("No photos selected or deleted.", "warning")

        except Exception as e:
            conn.rollback()
            flash("An error occurred. Please try again.", "danger")
            # In production: log.exception(e)

    # 3. Load fresh data for display
    cursor.execute("""
        SELECT id, title, description, cover_photo, is_public
        FROM galleries WHERE id = %s
    """, (gallery_id,))
    gallery = cursor.fetchone()
    cursor.execute("""
    SELECT 
        p.*,
        COUNT(DISTINCT pl.id) AS like_count,
        COUNT(DISTINCT pd.id) AS download_count
    FROM photos p
    LEFT JOIN photo_likes pl ON pl.photo_id = p.id
    LEFT JOIN photo_downloads pd ON pd.photo_id = p.id
    WHERE p.gallery_id = %s
    GROUP BY p.id
    ORDER BY p.sort_order ASC, p.id ASC
    """, (gallery_id,))
    photos = cursor.fetchall()

    total_size_kb = sum(p["file_size"] or 0 for p in photos)
    total_size_mb = round(total_size_kb / 1024, 1) if total_size_kb > 0 else 0.0

    cursor.close()
    conn.close()

    return render_template(
        "client/manage_gallery.html",
        gallery=gallery,
        photos=photos,
        total_size_mb=total_size_mb,
        photo_count=len(photos),
        gallery_id=gallery_id
    )
#^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
@app.route("/gallery/<int:gallery_id>", methods=["GET", "POST"])
def public_gallery(gallery_id):

    conn = mysql.connect()
    cursor = conn.cursor(pymysql.cursors.DictCursor)

    # Get gallery
    cursor.execute("""
        SELECT *
        FROM galleries
        WHERE id = %s AND is_public = 1
    """, (gallery_id,))
    gallery = cursor.fetchone()

    if not gallery:
        cursor.close()
        conn.close()
        return "Gallery not found or private", 404

    # ================================
    # 🔒 PASSWORD PROTECTION
    # ================================
    session_key = f"gallery_access_{gallery_id}"

    if gallery.get("password"):
        # If not already unlocked
        if not session.get(session_key):

            # If user submitted password
            if request.method == "POST":
                entered = request.form.get("password")

                if entered == gallery["password"]:
                    session[session_key] = True
                    return redirect(url_for("public_gallery", gallery_id=gallery_id))
                else:
                    return render_template(
                        "public/gallery_password.html",
                        gallery=gallery,
                        error="Incorrect password"
                    )

            # First visit → show password page
            return render_template(
                "public/gallery_password.html",
                gallery=gallery
            )

    # ================================
    # LOAD PHOTOS (only after access)
    # ================================
    cursor.execute("""
    SELECT p.*,
           COUNT(l.id) AS likes,
           MAX(CASE WHEN l.client_id = %s THEN 1 ELSE 0 END) AS liked_by_user
    FROM photos p
    LEFT JOIN photo_likes l ON p.id = l.photo_id
    WHERE p.gallery_id=%s
    GROUP BY p.id
    ORDER BY p.created_at DESC
""", (session.get("client_id", 0), gallery_id))
    photos = cursor.fetchall()

    cursor.close()
    conn.close()

    return render_template(
        "public/gallery.html",
        gallery=gallery,
        photos=photos
    )

@app.route("/favorites")
def public_favorites():
    email = session.get("visitor_email")

    if not email:
        return "No favorites yet"

    conn = mysql.connect()
    cursor = conn.cursor(pymysql.cursors.DictCursor)

    cursor.execute("""
        SELECT p.*
        FROM photos p
        JOIN photo_likes l ON p.id = l.photo_id
        WHERE l.client_name=%s
        ORDER BY l.id DESC
    """, (email,))

    photos = cursor.fetchall()

    cursor.close()
    conn.close()

    return render_template("public/favorites.html", photos=photos)

@app.route("/client/preview-gallery/<int:gallery_id>/preview")
@login_required("client")  # your custom decorator
def preview_gallery(gallery_id):
    client_id = session.get("client_id")
    if not client_id:
        flash("Please log in to continue.", "danger")
        return redirect(url_for("client_login"))  # adjust route name if different

    conn = mysql.connect()
    cursor = conn.cursor(pymysql.cursors.DictCursor)

    # Fetch gallery + verify ownership
    cursor.execute("""
        SELECT id, title, description, cover_photo, is_public, client_id
        FROM galleries
        WHERE id = %s
    """, (gallery_id,))
    gallery = cursor.fetchone()

    if not gallery:
        cursor.close()
        conn.close()
        flash("Gallery not found.", "danger")
        return redirect(url_for("client_collections"))

    if gallery["client_id"] != client_id:
        cursor.close()
        conn.close()
        flash("You do not have permission to preview this gallery.", "danger")
        return redirect(url_for("client_collections"))

    # Fetch all photos
    cursor.execute("""
        SELECT id, original_name, photo_path, filename
        FROM photos
        WHERE gallery_id = %s
       ORDER BY sort_order ASC, id ASC
    """, (gallery_id,))
    photos = cursor.fetchall()

    cursor.close()
    conn.close()

    return render_template(
        "client/preview_gallery.html",
        gallery=gallery,
        photos=photos,
        is_preview_mode=True   # optional flag to show "Preview Mode" banner if you want
    )    
    #^^^^^^^^^^^^^^^^^^^^^^^^6
#========================================================
@app.route("/client/collection/create", methods=["GET", "POST"])
@login_required("client")
def create_collection():
    if request.method == "POST":
        title = request.form.get("title")
        client_id = session["client_id"]

        conn = mysql.connect()
        cursor = conn.cursor()

        cursor.execute("""
            INSERT INTO galleries (title, client_id, created_at)
            VALUES (%s, %s, NOW())
        """, (title, client_id))

        conn.commit()
        cursor.close()
        conn.close()

        return redirect(url_for("client_collections"))

    return render_template("client/create_collection.html")



@app.route("/client/settings", methods=["GET", "POST"])
@login_required("client")
def client_settings():
    client_id = session["client_id"]
    conn = get_db_connection()
    cursor = conn.cursor(pymysql.cursors.DictCursor)

    if request.method == "POST":
        name = request.form["name"].strip()
        email = request.form["email"].strip()

        cursor.execute("""
            UPDATE clients
            SET name = %s, email = %s
            WHERE id = %s
        """, (name, email, client_id))

        conn.commit()
        session["client_name"] = name  # keep session updated

    cursor.execute(
        "SELECT name, email FROM clients WHERE id = %s",
        (client_id,)
    )
    client = cursor.fetchone()

    cursor.close()
    conn.close()

    return render_template(
        "client/settings.html",
        client=client
    )

@app.route("/client/settings/profile", methods=["POST"])
@login_required("client")
def update_profile():
    name = request.form["name"]

    conn = mysql.connect()
    cur = conn.cursor()
    cur.execute(
        "UPDATE clients SET name=%s WHERE id=%s",
        (name, session["client_id"])
    )
    conn.commit()
    conn.close()

    return redirect(url_for("client_settings"))


@app.route("/client/change-password", methods=["POST"])
@login_required("client")
def change_password():
    client_id = session["client_id"]
    current_password = request.form["current_password"]
    new_password = request.form["new_password"]

    conn = mysql.connect()
    cursor = conn.cursor(pymysql.cursors.DictCursor)

    cursor.execute(
        "SELECT password FROM clients WHERE id = %s",
        (client_id,)
    )
    client = cursor.fetchone()

    if not bcrypt.check_password_hash(client["password"], current_password):
        cursor.close()
        conn.close()
        return "Incorrect current password", 400

    hashed = bcrypt.generate_password_hash(new_password).decode("utf-8")

    cursor.execute(
        "UPDATE clients SET password = %s WHERE id = %s",
        (hashed, client_id)
    )
    conn.commit()

    cursor.close()
    conn.close()

    return redirect(url_for("client_settings"))



# ────────────────────────────────────────────────
#  CLIENT GALLERIES & PHOTOS
# ────────────────────────────────────────────────
@app.route("/client/galleries")
@login_required("client")
def manage_galleries():
    client_id = session["client_id"]

    conn = mysql.connect()
    cur = conn.cursor(pymysql.cursors.DictCursor)
     
    cur.execute("""
        SELECT g.id, g.title, g.description, g.cover_photo
        FROM galleries g
        WHERE g.client_id = %s AND g.is_public = 1
        ORDER BY g.created_at DESC
    """, (session["client_id"],))


    galleries = cur.fetchall()

    cur.close()
    conn.close()

    return render_template("client/manage_galleries.html", galleries=galleries)

import os
from flask import request, session, redirect, url_for, render_template, flash, current_app

# Assuming these are already defined in your app
# get_db_connection() → your mysql connection function
# BASE_DIR should be defined once at the top of app.py

# Recommended: define this once at the top of your app.py (after app = Flask(...))
BASE_DIR = os.path.dirname(os.path.abspath(__file__))  # folder containing app.py
GALLERY_UPLOAD_ROOT = os.path.join(BASE_DIR, 'static', 'uploads', 'galleries')

# Optional helper (you can keep or remove your existing get_gallery_path)
def get_gallery_folder(client_id, gallery_id):
    """
    Returns the absolute path to the gallery's upload folder.
    Uses gallery_id (more reliable than slug/title).
    """
    return os.path.join(GALLERY_UPLOAD_ROOT, str(gallery_id))


@app.route("/client/create-gallery", methods=["GET", "POST"])
def create_gallery():
    if request.method == "POST":
        title = request.form.get("title", "").strip()
        
        if not title:
            flash("Gallery title is required.", "error")
            return redirect(url_for("create_gallery"))

        client_id = session.get("client_id")
        if not client_id:
            flash("Please log in to create a gallery.", "error")
            return redirect(url_for("login"))  # ← change to your actual login route

        conn = None
        cur = None
        try:
            conn = get_db_connection()
            cur = conn.cursor()

            # Insert gallery and get the new ID
            cur.execute(
                """
                INSERT INTO galleries (title, client_id, created_at)
                VALUES (%s, %s, NOW())
                """,
                (title, client_id)
            )
            conn.commit()

            # Get the newly created gallery ID
            gallery_id = cur.lastrowid

            # Create the folder using the gallery ID
            gallery_folder = get_gallery_folder(client_id, gallery_id)
            
            try:
                os.makedirs(gallery_folder, exist_ok=True)
                current_app.logger.info(f"Created gallery folder: {gallery_folder}")
            except Exception as folder_err:
                current_app.logger.error(f"Failed to create gallery folder {gallery_folder}: {folder_err}")
                # Still continue — folder creation failure shouldn't block gallery creation
                flash("Gallery created, but folder creation failed. Contact support.", "warning")
            else:
                flash(f"Gallery '{title}' created successfully.", "success")

            return redirect(url_for("manage_galleries"))

        except pymysql.Error as db_err:
            if conn:
                conn.rollback()
            current_app.logger.error(f"Database error creating gallery: {db_err}")
            flash("Failed to create gallery due to a database error.", "error")
            return redirect(url_for("create_gallery"))

        except Exception as e:
            current_app.logger.error(f"Unexpected error creating gallery: {e}")
            flash("An unexpected error occurred.", "error")
            return redirect(url_for("create_gallery"))

        finally:
            if cur:
                cur.close()
            if conn:
                conn.close()

    # GET request → show form
    return render_template("client/create-gallery.html")

@app.route("/client/gallery/<int:gallery_id>/photos")
@login_required("client")
def gallery_photos(gallery_id):
    conn = mysql.connect()
    cursor = conn.cursor(pymysql.cursors.DictCursor)

    # Get gallery
    cursor.execute("""
        SELECT * FROM galleries
        WHERE id = %s
    """, (gallery_id,))
    gallery = cursor.fetchone()

    if not gallery:
        cursor.close()
        conn.close()
        return "Gallery not found"

    # Get photos with like count
    cursor.execute("""
        SELECT p.*,
               COUNT(pl.id) AS like_count
        FROM photos p
        LEFT JOIN photo_likes pl
            ON p.id = pl.photo_id
        WHERE p.gallery_id = %s
        GROUP BY p.id
        ORDER BY p.id DESC
    """, (gallery_id,))
    photos = cursor.fetchall()

    cursor.close()
    conn.close()

    return render_template(
        "client/photos.html",
        gallery=gallery,
        gallery_id=gallery_id,
        photos=photos
    )

@app.route("/client/gallery/<int:gallery_id>/settings", methods=["GET", "POST"])
@login_required("client")
def gallery_settings(gallery_id):
    client_id = session["client_id"]

    conn = mysql.connect()
    cursor = conn.cursor(pymysql.cursors.DictCursor)

    # ---- GET GALLERY ----
    cursor.execute(
        "SELECT * FROM galleries WHERE id=%s AND client_id=%s",
        (gallery_id, client_id)
    )
    gallery = cursor.fetchone()

    if not gallery:
        cursor.close()
        conn.close()
        abort(404)

    # ---- POST: SAVE SETTINGS ----
    if request.method == "POST":
        title = request.form.get("title", "").strip()
        is_public = 1 if request.form.get("is_public") else 0

        if not title:
            flash("Gallery title cannot be empty", "error")
            return redirect(request.url)

        cursor.execute("""
            UPDATE galleries
            SET title=%s,
                is_public=%s
            WHERE id=%s AND client_id=%s
        """, (
            title,
            is_public,
            gallery_id,
            client_id
        ))

        conn.commit()
        cursor.close()
        conn.close()

        flash("Gallery settings updated successfully", "success")
        return redirect(url_for("manage_gallery", gallery_id=gallery_id))

    # ---- GET: SHOW PAGE ----
    cursor.close()
    conn.close()

    return render_template(
        "client/gallery_settings.html",
        gallery=gallery
    )



@app.route("/client/gallery/<int:gallery_id>/access", methods=["GET", "POST"])
@login_required("client")
def gallery_access(gallery_id):
    client_id = session["client_id"]

    conn = mysql.connect()
    cursor = conn.cursor(pymysql.cursors.DictCursor)

    # GET gallery
    cursor.execute(
        "SELECT * FROM galleries WHERE id=%s AND client_id=%s",
        (gallery_id, client_id)
    )
    gallery = cursor.fetchone()

    if not gallery:
        conn.close()
        abort(404)

    if request.method == "POST":
        is_public = 1 if request.form.get("is_public") else 0
        password_enabled = request.form.get("password_enabled")
        password = request.form.get("password")

        if password_enabled:
            password_to_save = password if password else gallery["password"]
        else:
            password_to_save = None

        cursor.execute("""
            UPDATE galleries
            SET is_public=%s, password=%s
            WHERE id=%s AND client_id=%s
        """, (is_public, password_to_save, gallery_id, client_id))

        conn.commit()
        conn.close()

        flash("Gallery access updated", "success")
        return redirect(url_for("manage_gallery", gallery_id=gallery_id))

    conn.close()
    return render_template(
        "client/gallery_access.html",
        gallery=gallery
    )
    
@app.route("/client/gallery/<int:gallery_id>/favorites")
@login_required("client")
def gallery_favorites(gallery_id):
    conn = mysql.connect()
    cursor = conn.cursor(pymysql.cursors.DictCursor)

    # Get all liked photos for this gallery
    cursor.execute("""
        SELECT DISTINCT p.*
        FROM photos p
        JOIN photo_likes l
            ON p.id = l.photo_id
        WHERE p.gallery_id = %s
        ORDER BY p.id DESC
    """, (gallery_id,))

    photos = cursor.fetchall()

    cursor.close()
    conn.close()

    return render_template(
        "client/favorites.html",
        photos=photos
    )
import os
import time
import requests
from datetime import datetime
from urllib.parse import urlparse
from werkzeug.utils import secure_filename
from flask import (
    request, session, jsonify, flash, redirect,
    render_template, url_for, current_app
)
import pymysql

# ────────────────────────────────────────────────
#   Force absolute path — no more relative surprises
# ────────────────────────────────────────────────
BASE_DIR = os.path.dirname(os.path.abspath(__file__))  # folder where app.py lives
UPLOAD_ROOT = os.path.join(BASE_DIR, 'static', 'uploads', 'galleries')

# Log once at startup so you can see the real path immediately
print(f"[STARTUP] BASE_DIR: {BASE_DIR}")
print(f"[STARTUP] UPLOAD_ROOT resolved to: {UPLOAD_ROOT}")
print(f"[STARTUP] Current working directory: {os.getcwd()}")
print(f"[STARTUP] Can write to UPLOAD_ROOT? {os.access(UPLOAD_ROOT, os.W_OK) if os.path.exists(UPLOAD_ROOT) else 'folder not exist yet'}")

def allowed_file(filename):
    ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp'}
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


@app.route("/client/gallery/<int:gallery_id>/upload", methods=["GET"])
def upload_photos_page(gallery_id):
    @login_required("client")
    def inner():
        client_id = session.get("client_id")
        if not client_id:
            flash("Please log in again", "error")
            return redirect(url_for("login"))  # ← CHANGE to your real login route name

        conn = mysql.connect()
        cursor = conn.cursor(pymysql.cursors.DictCursor)

        cursor.execute(
            "SELECT * FROM galleries WHERE id=%s AND client_id=%s",
            (gallery_id, client_id)
        )
        gallery = cursor.fetchone()

        cursor.close()
        conn.close()

        if not gallery:
            flash("Gallery not found", "error")
            return redirect(url_for("client_dashboard"))

        return render_template("client/upload_photos.html", gallery=gallery)

    return inner()


@app.route("/client/gallery/<int:gallery_id>/upload", methods=["POST"])
def upload_photos(gallery_id):
    @login_required("client")
    def inner():
        client_id = session.get("client_id")
        if not client_id:
            flash("Session expired. Please log in.", "error")
            return redirect(url_for("login"))  # ← CHANGE to your real login route

        print(f"[LOCAL UPLOAD] Route called for gallery {gallery_id} by client {client_id}")

        conn = mysql.connect()
        cursor = conn.cursor(pymysql.cursors.DictCursor)

        cursor.execute(
            "SELECT id FROM galleries WHERE id=%s AND client_id=%s LIMIT 1",
            (gallery_id, client_id)
        )
        if not cursor.fetchone():
            cursor.close()
            conn.close()
            print(f"[LOCAL UPLOAD] Gallery {gallery_id} not found or not owned by {client_id}")
            flash("Gallery not found or access denied", "error")
            return redirect(url_for("client_dashboard"))

        files = request.files.getlist("photos")   # Make sure form has <input name="photos" multiple ...>

        print(f"[LOCAL UPLOAD] Files received: {len(files)}")
        print(f"[LOCAL UPLOAD] Filenames: {[f.filename for f in files]}")

        if not files or all(f.filename == "" for f in files):
            cursor.close()
            conn.close()
            print("[LOCAL UPLOAD] No files received")
            flash("No files selected", "warning")
            return redirect(url_for("manage_gallery", gallery_id=gallery_id))

        gallery_folder = os.path.join(UPLOAD_ROOT, str(gallery_id))
        print(f"[LOCAL UPLOAD] Target folder: {gallery_folder}")

        try:
            os.makedirs(gallery_folder, exist_ok=True)
            print(f"[LOCAL UPLOAD] Folder created / already exists: {gallery_folder}")
        except Exception as e:
            print(f"[LOCAL UPLOAD] Folder creation failed: {e}")
            flash("Server error - could not create upload folder", "error")
            return redirect(url_for("manage_gallery", gallery_id=gallery_id))

        uploaded_count = 0

        for file in files:
            if not file.filename or not allowed_file(file.filename):
                print(f"[LOCAL UPLOAD] Skipping invalid file: {file.filename}")
                continue

            try:
                filename = secure_filename(file.filename)
                save_path = os.path.join(gallery_folder, filename)

                base, ext = os.path.splitext(filename)
                counter = 1
                while os.path.exists(save_path):
                    filename = f"{base}_{counter}{ext}"
                    save_path = os.path.join(gallery_folder, filename)
                    counter += 1

                print(f"[LOCAL UPLOAD] Saving file to: {save_path}")
                file.save(save_path)

                file_size_bytes = os.path.getsize(save_path)
                print(f"[LOCAL UPLOAD] File saved successfully: {save_path} (size: {file_size_bytes} bytes)")

                photo_path = f"uploads/galleries/{gallery_id}/{filename}"

                cursor.execute("""
                    INSERT INTO photos
                    (client_id, gallery_id, filename, original_name, photo_path, file_size, created_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                """, (
                    client_id,
                    gallery_id,
                    filename,
                    file.filename,
                    photo_path,
                    file_size_bytes,
                    datetime.now()
                ))

                uploaded_count += 1

            except Exception as e:
                print(f"[LOCAL UPLOAD] Error saving {file.filename}: {type(e).__name__} - {str(e)}")
                current_app.logger.error(f"Local upload error: {e}", exc_info=True)
                continue

        conn.commit()
        cursor.close()
        conn.close()

        flash(f"{uploaded_count} photo(s) uploaded successfully.", "success")
        return redirect(url_for("manage_gallery", gallery_id=gallery_id))

    return inner()


@app.route("/client/gallery/<int:gallery_id>/upload-from-url", methods=["POST"])
def upload_photo_from_url(gallery_id):
    @login_required("client")
    def inner():
        client_id = session.get("client_id")
        if not client_id:
            return jsonify({"success": False, "error": "Not authenticated"}), 401

        print(f"[URL UPLOAD] Started for gallery {gallery_id} by client {client_id}")

        data = request.get_json(silent=True)
        if not data:
            print("[URL UPLOAD] Invalid JSON received")
            return jsonify({"success": False, "error": "Invalid JSON"}), 400

        image_url = data.get("image_url")
        if not image_url:
            print("[URL UPLOAD] No image_url provided")
            return jsonify({"success": False, "error": "No image URL provided"}), 400

        print(f"[URL UPLOAD] Downloading from: {image_url}")

        conn = None
        cursor = None
        try:
            conn = mysql.connect()
            cursor = conn.cursor(pymysql.cursors.DictCursor)

            cursor.execute(
                "SELECT id FROM galleries WHERE id=%s AND client_id=%s LIMIT 1",
                (gallery_id, client_id)
            )
            if not cursor.fetchone():
                print(f"[URL UPLOAD] Gallery {gallery_id} not found or not owned")
                return jsonify({"success": False, "error": "Gallery not found or not owned"}), 404

            response = requests.get(image_url, timeout=15, stream=True)
            response.raise_for_status()

            content_type = response.headers.get("content-type", "").lower()
            if "image" not in content_type:
                print(f"[URL UPLOAD] Not an image: {content_type}")
                return jsonify({"success": False, "error": "URL does not point to an image"}), 400

            parsed = urlparse(image_url)
            original_name = os.path.basename(parsed.path) or "imported_image"
            filename = secure_filename(original_name)

            if not filename or filename == ".":
                ext = ".jpg"
                if "png" in content_type: ext = ".png"
                elif "webp" in content_type: ext = ".webp"
                filename = f"imported_{int(time.time())}{ext}"
            elif not os.path.splitext(filename)[1]:
                filename += ".jpg"

            gallery_folder = os.path.join(UPLOAD_ROOT, str(gallery_id))
            print(f"[URL UPLOAD] Target folder: {gallery_folder}")

            os.makedirs(gallery_folder, exist_ok=True)
            print(f"[URL UPLOAD] Folder ready: {gallery_folder}")

            save_path = os.path.join(gallery_folder, filename)

            base, ext = os.path.splitext(filename)
            counter = 1
            while os.path.exists(save_path):
                filename = f"{base}_{counter}{ext}"
                save_path = os.path.join(gallery_folder, filename)
                counter += 1

            print(f"[URL UPLOAD] Saving to: {save_path}")
            with open(save_path, "wb") as f:
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)

            file_size_bytes = os.path.getsize(save_path)
            print(f"[URL UPLOAD] File saved: {save_path} (size: {file_size_bytes} bytes)")

            db_path = f"uploads/galleries/{gallery_id}/{filename}"

            cursor.execute("""
                INSERT INTO photos
                (client_id, gallery_id, filename, original_name, photo_path, file_size, created_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
            """, (
                client_id,
                gallery_id,
                filename,
                original_name,
                db_path,
                file_size_bytes,
                datetime.now()
            ))

            conn.commit()
            print(f"[URL UPLOAD] Database insert successful")

            return jsonify({"success": True, "filename": filename})

        except requests.RequestException as e:
            print(f"[URL UPLOAD] Download failed: {str(e)}")
            return jsonify({"success": False, "error": f"Download failed: {str(e)}"}), 400

        except pymysql.Error as e:
            if conn: conn.rollback()
            print(f"[URL UPLOAD] DB error: {str(e)}")
            return jsonify({"success": False, "error": "Database error"}), 500

        except Exception as e:
            if conn: conn.rollback()
            print(f"[URL UPLOAD] General error: {type(e).__name__} - {str(e)}")
            current_app.logger.error(f"URL upload error: {e}", exc_info=True)
            return jsonify({"success": False, "error": "Server error"}), 500

        finally:
            if cursor: cursor.close()
            if conn: conn.close()

    return inner()
@app.route("/client/gallery/<int:gallery_id>/cover/<int:photo_id>", methods=["POST"])
@login_required("client")
def set_gallery_cover(gallery_id, photo_id):
    client_id = session.get("client_id")
    if not client_id:
        return jsonify({"success": False, "error": "Not authenticated"}), 401

    conn = None
    cursor = None
    try:
        conn = mysql.connect()
        cursor = conn.cursor(pymysql.cursors.DictCursor)

        # Verify photo belongs to this gallery & client
        cursor.execute("""
            SELECT photo_path
            FROM photos
            WHERE id = %s AND gallery_id = %s AND client_id = %s
        """, (photo_id, gallery_id, client_id))

        photo = cursor.fetchone()

        if not photo:
            return jsonify({"success": False, "error": "Photo not found or not owned"}), 404

        # Update cover
        cursor.execute("""
            UPDATE galleries
            SET cover_photo = %s
            WHERE id = %s AND client_id = %s
        """, (photo["photo_path"], gallery_id, client_id))

        conn.commit()

        return jsonify({
            "success": True,
            "message": "Cover photo updated",
            "cover_path": photo["photo_path"]
        })

    except pymysql.Error as e:
        if conn:
            conn.rollback()
        current_app.logger.error(f"DB error setting cover: {e}")
        return jsonify({"success": False, "error": "Database error"}), 500

    except Exception as e:
        current_app.logger.error(f"Error setting cover: {e}")
        return jsonify({"success": False, "error": "Server error"}), 500

    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()
                
@app.route("/client/gallery/<int:gallery_id>/delete", methods=["POST"])
@login_required("client")
def delete_gallery(gallery_id):
    client_id = session["client_id"]

    conn = mysql.connect()
    cursor = conn.cursor(pymysql.cursors.DictCursor)

    # --- Get gallery (security check) ---
    cursor.execute("""
        SELECT id, title
        FROM galleries
        WHERE id = %s AND client_id = %s
    """, (gallery_id, client_id))
    gallery = cursor.fetchone()

    if not gallery:
        cursor.close()
        conn.close()
        abort(404)

    # --- Get photos for file deletion ---
    cursor.execute("""
        SELECT photo_path
        FROM photos
        WHERE gallery_id = %s
    """, (gallery_id,))
    photos = cursor.fetchall()

    # --- Delete likes ---
    cursor.execute("""
        DELETE FROM photo_likes
        WHERE photo_id IN (
            SELECT id FROM photos WHERE gallery_id = %s
        )
    """, (gallery_id,))

    # --- Delete photos from DB ---
    cursor.execute("""
        DELETE FROM photos
        WHERE gallery_id = %s
    """, (gallery_id,))

    # --- Delete gallery ---
    cursor.execute("""
        DELETE FROM galleries
        WHERE id = %s AND client_id = %s
    """, (gallery_id, client_id))

    conn.commit()
    cursor.close()
    conn.close()

    # --- Delete image files ---
    for p in photos:
        file_path = os.path.join("static", p["photo_path"])
        if os.path.exists(file_path):
            os.remove(file_path)

    flash("Gallery deleted successfully", "success")
    return redirect(url_for("client_dashboard"))

@app.route("/client/gallery/<int:gallery_id>/delete/confirm")
@login_required("client")
def delete_gallery_confirm(gallery_id):
    client_id = session["client_id"]

    conn = mysql.connect()
    cursor = conn.cursor(pymysql.cursors.DictCursor)

    cursor.execute("""
        SELECT id, title
        FROM galleries
        WHERE id = %s AND client_id = %s
    """, (gallery_id, client_id))
    gallery = cursor.fetchone()

    cursor.close()
    conn.close()

    if not gallery:
        abort(404)

    return render_template(
        "client/delete_gallery.html",
        gallery=gallery
    )
    
@app.route("/client/gallery/<int:gallery_id>/reorder", methods=["POST"])
@login_required("client")
def reorder_photos(gallery_id):
    client_id = session["client_id"]
    data = request.get_json()
    order_list = data.get("order", [])

    conn = mysql.connect()
    cursor = conn.cursor()

    for item in order_list:
        cursor.execute("""
            UPDATE photos p
            JOIN galleries g ON p.gallery_id = g.id
            SET p.sort_order = %s
            WHERE p.id = %s AND g.client_id = %s
        """, (item["position"], item["id"], client_id))

    conn.commit()
    cursor.close()
    conn.close()

    return {"success": True}

    
@app.route("/client/photo/<int:photo_id>/like", methods=["POST"])
@login_required("client")
def toggle_like(photo_id):
    client_id = session["client_id"]

    conn = mysql.connect()
    cursor = conn.cursor(pymysql.cursors.DictCursor)

    # Check if already liked
    cursor.execute("""
        SELECT id FROM photo_likes
        WHERE photo_id = %s AND client_id = %s
    """, (photo_id, client_id))
    like = cursor.fetchone()

    if like:
        # Unlike
        cursor.execute("""
            DELETE FROM photo_likes
            WHERE photo_id = %s AND client_id = %s
        """, (photo_id, client_id))
        liked = False
    else:
        # Like
        cursor.execute("""
            INSERT INTO photo_likes (photo_id, client_id, created_at)
            VALUES (%s, %s, NOW())
        """, (photo_id, client_id))
        liked = True

    # Recalculate total likes
    cursor.execute("""
        SELECT COUNT(*) AS total
        FROM photo_likes
        WHERE photo_id = %s
    """, (photo_id,))
    count = cursor.fetchone()["total"]

    # Update like_count in photos table
    cursor.execute("""
        UPDATE photos
        SET like_count = %s
        WHERE id = %s
    """, (count, photo_id))

    conn.commit()
    cursor.close()
    conn.close()

    return jsonify({
        "liked": liked,
        "count": count
    })

@app.route("/client/favorites")
@login_required("client")
def client_favorites():
    conn = mysql.connect()
    cursor = conn.cursor(pymysql.cursors.DictCursor)

    cursor.execute("""
        SELECT f.*, p.photo_path
        FROM favorites f
        JOIN photos p ON f.photo_id = p.id
        ORDER BY f.created_at DESC
    """)

    favorites = cursor.fetchall()

    cursor.close()
    conn.close()

    return render_template(
        "client/favorites.html",
        favorites=favorites
    )

@app.route("/client/check-favorite-session")
def check_favorite_session():
    return jsonify({
        "has_email": bool(session.get("favorite_email") or session.get("client_id"))
    })

@app.route("/client/set-favorite-email", methods=["POST"])
def set_favorite_email():
    data = request.get_json()
    session["favorite_email"] = data["email"]
    return jsonify(success=True)




@app.route("/client/photo/<int:photo_id>/likes")
@login_required("client")
def photo_likes(photo_id):
    conn=mysql.connect()
    cursor = conn.cursor(pymysql.cursors.DictCursor)


    cursor.execute("""
        SELECT c.name
        FROM photo_likes pl
        JOIN clients c ON c.id = pl.client_id
        WHERE pl.photo_id = %s
    """, (photo_id,))

    return jsonify(cursor.fetchall())

@app.route("/like_photo/<int:photo_id>", methods=["POST"])
def like_photo(photo_id):
    try:
        client_id = session.get("client_id")

        if not client_id:
            return {"success": False, "message": "Not logged in"}

        conn = get_db_connection()
        cursor = conn.cursor()

        # check if already liked
        cursor.execute("""
            SELECT id FROM photo_likes
            WHERE photo_id=%s AND client_id=%s
        """, (photo_id, client_id))
        existing = cursor.fetchone()

        if existing:
            # unlike
            cursor.execute("""
                DELETE FROM photo_likes
                WHERE photo_id=%s AND client_id=%s
            """, (photo_id, client_id))
        else:
            # like
            cursor.execute("""
                INSERT INTO photo_likes (photo_id, client_id)
                VALUES (%s, %s)
            """, (photo_id, client_id))

        conn.commit()
        cursor.close()
        conn.close()

        return {"success": True}

    except Exception as e:
        print("Like error:", e)
        return {"success": False}






import os
@app.route("/client/photo/<int:photo_id>/delete", methods=["POST"])
@login_required("client")
def delete_photo(photo_id):
    client_id = session["client_id"]

    conn = mysql.connect()
    cursor = conn.cursor(pymysql.cursors.DictCursor)

    # ✅ verify ownership
    cursor.execute("""
        SELECT p.photo_path, p.gallery_id
        FROM photos p
        JOIN galleries g ON p.gallery_id = g.id
        WHERE p.id=%s AND g.client_id=%s
    """, (photo_id, client_id))

    photo = cursor.fetchone()

    if not photo:
        flash("Photo not found.", "error")
        return redirect(url_for("client_dashboard"))

    # ✅ delete file from disk
    file_path = os.path.join("static", photo["photo_path"])
    if os.path.exists(file_path):
        os.remove(file_path)

    # ✅ delete from DB
    cursor.execute("DELETE FROM photos WHERE id=%s", (photo_id,))
    conn.commit()

    gallery_id = photo["gallery_id"]

    cursor.close()
    conn.close()

    flash("Photo deleted successfully.", "success")

    # 🔥 IMPORTANT: return to SAME gallery manage page
    return redirect(url_for("manage_gallery", gallery_id=gallery_id))



# ────────────────────────────────────────────────
#  CLIENT SUBSCRIPTION & PAYMENT
# ────────────────────────────────────────────────
@app.route("/client/plan/<int:plan_id>")
@login_required("client")
def plan_details(plan_id):
    conn = mysql.connect()
    cursor = conn.cursor(DictCursor)

      
    cursor.execute("SELECT * FROM plans WHERE id=%s", (plan_id,))
    
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
        SELECT id, name, price,storage, duration
        FROM plans
        WHERE id = %s AND status = 'active'
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

@app.route("/client/activate-plan/<int:plan_id>")
@login_required("client")
def activate_plan(plan_id):
    client_id = session["client_id"]

    conn = mysql.connect()
    cursor = conn.cursor(pymysql.cursors.DictCursor)

    # ✅ get plan
    cursor.execute("SELECT * FROM plans WHERE id=%s", (plan_id,))
    plan = cursor.fetchone()

    if not plan:
        cursor.close()
        conn.close()
        flash("Plan not found", "danger")
        return redirect(url_for("pricing"))

    start_date = datetime.today().date()
    end_date = start_date + timedelta(days=plan["duration"])

    # ✅ deactivate old subscriptions
    cursor.execute("""
        UPDATE client_subscriptions
        SET status='expired'
        WHERE client_id=%s AND status='active'
    """, (client_id,))

    # ✅ insert new active subscription
    cursor.execute("""
        INSERT INTO client_subscriptions
        (client_id, plan_id, start_date, end_date, status)
        VALUES (%s, %s, %s, %s, 'active')
    """, (client_id, plan_id, start_date, end_date))

    conn.commit()
    cursor.close()
    conn.close()

    flash("🎉 Plan activated successfully!", "success")
    return redirect(url_for("client_dashboard"))


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
# =========================================
# AI VISUAL SIMILARITY SEARCH (NO DLIB)
# =========================================
# =========================================
# AI VISUAL SIMILARITY SEARCH (PREMIUM)
# =========================================

def extract_features(image_source):
    """
    Premium hybrid features:
    - grayscale structure (SSIM)
    - color histogram (normalized)
    """
    try:
        if isinstance(image_source, str):
            img = Image.open(image_source).convert("RGB")
        else:
            img = Image.open(image_source).convert("RGB")

        img = img.resize((256, 256))
        img_np = np.array(img)

        # ⭐ structural feature
        gray = cv2.cvtColor(img_np, cv2.COLOR_RGB2GRAY)

        # ⭐ color histogram
        hist = cv2.calcHist(
            [img_np],
            [0, 1, 2],
            None,
            [8, 8, 8],
            [0, 256, 0, 256, 0, 256],
        )

        # 🔥 normalize histogram
        hist = cv2.normalize(hist, hist).flatten()

        return gray, hist

    except Exception as e:
        print("Feature extraction error:", e)
        return None, None


# =========================================
# SIMILAR IMAGE SEARCH
# =========================================
@app.route("/gallery/<int:gallery_id>/search-similar", methods=["POST"])
def search_similar_faces(gallery_id):

    # ---------- check upload ----------
    if "image" not in request.files:
        return jsonify({"success": False, "error": "No image uploaded"})

    file = request.files["image"]

    try:
        query_gray, query_hist = extract_features(file.stream)

        if query_gray is None:
            return jsonify({
                "success": False,
                "error": "Invalid image"
            })

    except Exception:
        return jsonify({"success": False, "error": "Invalid image"})

    # ---------- DB ----------
    conn = mysql.connect()
    cur = conn.cursor(pymysql.cursors.DictCursor)

    cur.execute("""
        SELECT id, photo_path
        FROM photos
        WHERE gallery_id = %s
    """, (gallery_id,))
    photos = cur.fetchall()

    results = []

    # ---------- compare images ----------
    for photo in photos:
        try:
            full_path = os.path.join(
                app.root_path,
                "static",
                photo["photo_path"]
            )

            if not os.path.exists(full_path):
                continue

            db_gray, db_hist = extract_features(full_path)
            if db_gray is None:
                continue

            # ⭐ structure similarity (0–1)
            ssim_score = ssim(query_gray, db_gray)

            # ⭐ color similarity (-1 to 1 → normalize to 0–1)
            hist_score = cv2.compareHist(
                query_hist,
                db_hist,
                cv2.HISTCMP_CORREL
            )

            hist_score = max(0, min((hist_score + 1) / 2, 1))

            # ⭐ FINAL PREMIUM SCORE
            final_score = (0.65 * ssim_score) + (0.35 * hist_score)

            # ⭐ convert to percentage
            percent_score = final_score * 100

            # =====================================
            # 🔥 SHOW ONLY 60–100% MATCHES
            # =====================================
            if percent_score >= 40:
                results.append({
                    "id": photo["id"],
                    "path": photo["photo_path"],
                    "score": round(percent_score, 2)
                })

        except Exception as e:
            print("Similarity compare error:", e)
            continue

    # ---------- sort best match ----------
    results.sort(key=lambda x: x["score"], reverse=True)

    cur.close()
    conn.close()

    return jsonify({
        "success": True,
        "results": results[:12]
    })
if __name__ == "__main__":
    app.run(debug=True)
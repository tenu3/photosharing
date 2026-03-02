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

from flask import Flask, render_template, request, jsonify, session, redirect, url_for
from werkzeug.security import generate_password_hash, check_password_hash
import sqlite3
import os
from datetime import datetime, timedelta
from functools import wraps

app = Flask(__name__)
app.secret_key = 'expense-tracker-secret-key-2024'
DB_PATH = os.path.join(os.path.dirname(__file__), 'expense_tracker.db')

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        email TEXT UNIQUE NOT NULL,
        password TEXT NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS expenses (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        title TEXT NOT NULL,
        amount REAL NOT NULL,
        category TEXT NOT NULL,
        date TEXT NOT NULL,
        note TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (user_id) REFERENCES users(id)
    )''')
    conn.commit()
    conn.close()

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session:
            return jsonify({'error': 'Unauthorized'}), 401
        return f(*args, **kwargs)
    return decorated

@app.route('/')
def index():
    if 'user_id' in session:
        return redirect(url_for('dashboard'))
    return redirect(url_for('login_page'))

@app.route('/login')
def login_page():
    return render_template('login.html')

@app.route('/signup')
def signup_page():
    return render_template('signup.html')

@app.route('/dashboard')
def dashboard():
    if 'user_id' not in session:
        return redirect(url_for('login_page'))
    return render_template('dashboard.html')

@app.route('/api/signup', methods=['POST'])
def signup():
    data = request.json
    name = data.get('name','').strip()
    email = data.get('email','').strip().lower()
    password = data.get('password','')
    if not name or not email or not password:
        return jsonify({'error': 'All fields required'}), 400
    if len(password) < 6:
        return jsonify({'error': 'Password must be at least 6 characters'}), 400
    conn = get_db()
    try:
        hashed = generate_password_hash(password)
        conn.execute('INSERT INTO users (name, email, password) VALUES (?, ?, ?)', (name, email, hashed))
        conn.commit()
        user = conn.execute('SELECT * FROM users WHERE email = ?', (email,)).fetchone()
        session['user_id'] = user['id']
        session['user_name'] = user['name']
        seed_sample_data(user['id'], conn)
        conn.commit()
        return jsonify({'success': True, 'name': user['name']})
    except sqlite3.IntegrityError:
        return jsonify({'error': 'Email already registered'}), 400
    finally:
        conn.close()

@app.route('/api/login', methods=['POST'])
def login():
    data = request.json
    email = data.get('email','').strip().lower()
    password = data.get('password','')
    conn = get_db()
    user = conn.execute('SELECT * FROM users WHERE email = ?', (email,)).fetchone()
    conn.close()
    if not user or not check_password_hash(user['password'], password):
        return jsonify({'error': 'Invalid email or password'}), 401
    session['user_id'] = user['id']
    session['user_name'] = user['name']
    return jsonify({'success': True, 'name': user['name']})

@app.route('/api/logout', methods=['POST'])
def logout():
    session.clear()
    return jsonify({'success': True})

@app.route('/api/me')
@login_required
def me():
    return jsonify({'id': session['user_id'], 'name': session['user_name']})

@app.route('/api/expenses', methods=['GET'])
@login_required
def get_expenses():
    uid = session['user_id']
    month = request.args.get('month')
    category = request.args.get('category')
    conn = get_db()
    query = 'SELECT * FROM expenses WHERE user_id = ?'
    params = [uid]
    if month:
        query += ' AND date LIKE ?'
        params.append(f'{month}%')
    if category and category != 'all':
        query += ' AND category = ?'
        params.append(category)
    query += ' ORDER BY date DESC, id DESC'
    expenses = [dict(e) for e in conn.execute(query, params).fetchall()]
    conn.close()
    return jsonify(expenses)

@app.route('/api/expenses', methods=['POST'])
@login_required
def add_expense():
    data = request.json
    uid = session['user_id']
    title = data.get('title','').strip()
    amount = data.get('amount')
    category = data.get('category','').strip()
    date = data.get('date','')
    note = data.get('note','').strip()
    if not title or not amount or not category or not date:
        return jsonify({'error': 'Required fields missing'}), 400
    conn = get_db()
    cursor = conn.execute(
        'INSERT INTO expenses (user_id, title, amount, category, date, note) VALUES (?, ?, ?, ?, ?, ?)',
        (uid, title, float(amount), category, date, note)
    )
    conn.commit()
    expense = dict(conn.execute('SELECT * FROM expenses WHERE id = ?', (cursor.lastrowid,)).fetchone())
    conn.close()
    return jsonify(expense), 201

@app.route('/api/expenses/<int:eid>', methods=['DELETE'])
@login_required
def delete_expense(eid):
    uid = session['user_id']
    conn = get_db()
    conn.execute('DELETE FROM expenses WHERE id = ? AND user_id = ?', (eid, uid))
    conn.commit()
    conn.close()
    return jsonify({'success': True})

@app.route('/api/expenses/<int:eid>', methods=['PUT'])
@login_required
def update_expense(eid):
    uid = session['user_id']
    data = request.json
    conn = get_db()
    conn.execute(
        'UPDATE expenses SET title=?, amount=?, category=?, date=?, note=? WHERE id=? AND user_id=?',
        (data['title'], float(data['amount']), data['category'], data['date'], data.get('note',''), eid, uid)
    )
    conn.commit()
    expense = dict(conn.execute('SELECT * FROM expenses WHERE id = ?', (eid,)).fetchone())
    conn.close()
    return jsonify(expense)

@app.route('/api/analytics')
@login_required
def analytics():
    uid = session['user_id']
    month = request.args.get('month', datetime.now().strftime('%Y-%m'))
    conn = get_db()
    by_cat = conn.execute(
        'SELECT category, SUM(amount) as total FROM expenses WHERE user_id=? AND date LIKE ? GROUP BY category ORDER BY total DESC',
        (uid, f'{month}%')
    ).fetchall()
    daily = conn.execute(
        'SELECT date, SUM(amount) as total FROM expenses WHERE user_id=? AND date LIKE ? GROUP BY date ORDER BY date',
        (uid, f'{month}%')
    ).fetchall()
    monthly = []
    for i in range(5, -1, -1):
        d = datetime.now() - timedelta(days=30*i)
        m = d.strftime('%Y-%m')
        row = conn.execute(
            'SELECT COALESCE(SUM(amount),0) as total FROM expenses WHERE user_id=? AND date LIKE ?',
            (uid, f'{m}%')
        ).fetchone()
        monthly.append({'month': m, 'total': round(row['total'], 2)})
    total_month = conn.execute(
        'SELECT COALESCE(SUM(amount),0) as t FROM expenses WHERE user_id=? AND date LIKE ?',
        (uid, f'{month}%')
    ).fetchone()['t']
    total_all = conn.execute(
        'SELECT COALESCE(SUM(amount),0) as t FROM expenses WHERE user_id=?', (uid,)
    ).fetchone()['t']
    count_month = conn.execute(
        'SELECT COUNT(*) as c FROM expenses WHERE user_id=? AND date LIKE ?',
        (uid, f'{month}%')
    ).fetchone()['c']
    prev_month_dt = datetime.strptime(month, '%Y-%m') - timedelta(days=1)
    prev_month = prev_month_dt.strftime('%Y-%m')
    total_prev = conn.execute(
        'SELECT COALESCE(SUM(amount),0) as t FROM expenses WHERE user_id=? AND date LIKE ?',
        (uid, f'{prev_month}%')
    ).fetchone()['t']
    conn.close()
    return jsonify({
        'by_category': [dict(r) for r in by_cat],
        'daily': [dict(r) for r in daily],
        'monthly': monthly,
        'summary': {
            'total_month': round(total_month, 2),
            'total_all': round(total_all, 2),
            'count_month': count_month,
            'total_prev': round(total_prev, 2)
        }
    })

def seed_sample_data(user_id, conn):
    expenses = [
        ('Grocery Store', 85.50, 'Food', '2025-02-01'),
        ('Uber to Office', 12.00, 'Transport', '2025-02-02'),
        ('Netflix', 15.99, 'Entertainment', '2025-02-03'),
        ('Restaurant Dinner', 67.00, 'Food', '2025-02-04'),
        ('Electricity Bill', 120.00, 'Utilities', '2025-02-05'),
        ('Coffee Shop', 8.50, 'Food', '2025-02-06'),
        ('Pharmacy', 34.20, 'Health', '2025-02-07'),
        ('Amazon Order', 95.00, 'Shopping', '2025-02-08'),
        ('Gym Membership', 45.00, 'Health', '2025-02-10'),
        ('Lunch', 18.00, 'Food', '2025-02-11'),
        ('Bus Pass', 30.00, 'Transport', '2025-02-12'),
        ('Spotify', 9.99, 'Entertainment', '2025-02-13'),
        ('Supermarket', 110.00, 'Food', '2025-02-14'),
        ('Taxi', 22.00, 'Transport', '2025-02-15'),
        ('Clothes Shopping', 145.00, 'Shopping', '2025-02-16'),
        ('Doctor Visit', 55.00, 'Health', '2025-02-17'),
        ('Internet Bill', 60.00, 'Utilities', '2025-02-18'),
        ('Movie Tickets', 28.00, 'Entertainment', '2025-02-19'),
        ('Sushi Restaurant', 78.00, 'Food', '2025-02-20'),
        ('Flight Ticket', 320.00, 'Travel', '2025-02-22'),
        ('Grocery Run', 65.00, 'Food', '2025-03-01'),
        ('Uber', 15.00, 'Transport', '2025-03-02'),
        ('Dinner Out', 55.00, 'Food', '2025-03-04'),
        ('Electricity', 115.00, 'Utilities', '2025-03-05'),
        ('Coffee', 6.50, 'Food', '2025-03-07'),
        ('Headphones', 199.00, 'Shopping', '2025-03-08'),
        ('Pharmacy', 28.00, 'Health', '2025-03-09'),
        ('Lunch', 22.00, 'Food', '2025-03-10'),
    ]
    for title, amount, cat, date in expenses:
        conn.execute(
            'INSERT INTO expenses (user_id, title, amount, category, date, note) VALUES (?, ?, ?, ?, ?, ?)',
            (user_id, title, amount, cat, date, '')
        )

if __name__ == '__main__':
    init_db()
    app.run(debug=True, port=5000)

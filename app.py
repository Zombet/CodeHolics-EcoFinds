# app.py - Modified for Firebase Authentication
import os
import datetime
from functools import wraps
from flask import Flask, request, jsonify
from flask_cors import CORS
import mysql.connector
import firebase_admin
from firebase_admin import credentials, auth

# ---------------- Config ----------------
app = Flask(__name__, static_folder=None)
CORS(app)  # Configure this properly for production

# Firebase Admin SDK setup
# Download your service account key from Firebase Console
# and set the path in environment variable
cred = credentials.Certificate(os.getenv('FIREBASE_SERVICE_ACCOUNT_PATH', 'path/to/serviceAccountKey.json'))
firebase_admin.initialize_app(cred)

# MySQL config
DB_CONFIG = {
    'host': os.getenv('MYSQL_HOST', 'localhost'),
    'user': os.getenv('MYSQL_USER', 'root'),
    'password': os.getenv('MYSQL_PASSWORD', 'password'),
    'database': os.getenv('MYSQL_DB', 'ecofinds'),
    'auth_plugin': os.getenv('MYSQL_AUTH', 'mysql_native_password')
}

# ------------- Helpers -------------------
def get_db_connection():
    return mysql.connector.connect(**DB_CONFIG)

def firebase_auth_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        auth_header = request.headers.get('Authorization', None)
        if not auth_header or not auth_header.startswith('Bearer '):
            return jsonify({'error': 'Authorization header missing'}), 401
        
        token = auth_header.split(' ', 1)[1]
        try:
            # Verify Firebase ID token
            decoded_token = auth.verify_id_token(token)
            firebase_uid = decoded_token['uid']
            email = decoded_token.get('email', '')
            
            # Get or create user in our database
            user_id = get_or_create_user(firebase_uid, email, decoded_token)
            
        except Exception as e:
            return jsonify({'error': 'Invalid token', 'detail': str(e)}), 401
        
        return f(user_id, *args, **kwargs)
    return wrapper

def get_or_create_user(firebase_uid, email, decoded_token):
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        # Check if user exists by firebase_uid
        cur.execute("SELECT id FROM users WHERE firebase_uid=%s", (firebase_uid,))
        user = cur.fetchone()
        
        if user:
            return user['id']
        else:
            # Create new user
            username = decoded_token.get('name', email.split('@')[0])
            cur.execute(
                "INSERT INTO users (firebase_uid, username, email) VALUES (%s, %s, %s)",
                (firebase_uid, username, email)
            )
            conn.commit()
            return cur.lastrowid
    finally:
        cur.close()
        conn.close()

# -------------- Products ------------------
@app.route('/products', methods=['POST'])
@firebase_auth_required
def create_product(current_user):
    data = request.get_json() or {}
    title = data.get('title', '').strip()
    description = data.get('description', '').strip()
    price = data.get('price')
    category = data.get('category', '').strip()
    image = data.get('image', '').strip()

    if not (title and price is not None):
        return jsonify({'error': 'title and price required'}), 400

    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute(
            "INSERT INTO products (user_id, title, description, price, category, image) VALUES (%s,%s,%s,%s,%s,%s)",
            (current_user, title, description, float(price), category, image)
        )
        conn.commit()
        return jsonify({'message': 'product created', 'id': cur.lastrowid}), 201
    except Exception as e:
        return jsonify({'error': 'server error', 'detail': str(e)}), 500
    finally:
        cur.close()
        conn.close()

@app.route('/products', methods=['GET'])
def list_products():
    # optional filters: q, category
    q = request.args.get('q', '').strip()
    category = request.args.get('category', '').strip()

    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        base = """SELECT p.id, p.user_id, p.title, p.description, p.price, p.category, p.image, 
                         u.username as seller_name FROM products p 
                         JOIN users u ON p.user_id = u.id"""
        conditions = []
        params = []
        if q:
            conditions.append("(p.title LIKE %s OR p.description LIKE %s)")
            like = f"%{q}%"
            params.extend([like, like])
        if category:
            conditions.append("p.category=%s")
            params.append(category)
        if conditions:
            base += " WHERE " + " AND ".join(conditions)
        base += " ORDER BY p.id DESC"
        cur.execute(base, tuple(params))
        rows = cur.fetchall()
        return jsonify(rows)
    except Exception as e:
        return jsonify({'error': 'server error', 'detail': str(e)}), 500
    finally:
        cur.close()
        conn.close()

# Continue with other endpoints (cart, orders, etc.) using @firebase_auth_required decorator
# ... (rest of your endpoints with firebase_auth_required instead of jwt_required)

@app.route('/profile', methods=['GET'])
@firebase_auth_required
def profile(current_user):
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        cur.execute("SELECT id, username, email FROM users WHERE id=%s", (current_user,))
        user = cur.fetchone()
        if not user:
            return jsonify({'error': 'not found'}), 404
        return jsonify(user)
    except Exception as e:
        return jsonify({'error': 'server error', 'detail': str(e)}), 500
    finally:
        cur.close()
        conn.close()

if __name__ == '__main__':
    print("Starting EcoFinds Backend with SQLite...")
    print(f"Firebase available: {FIREBASE_AVAILABLE}")
    print(f"Database file: {DATABASE_FILE}")
    
    # Initialize database
    init_database()
    
    # Use PORT environment variable for Render
    port = int(os.getenv('PORT', 5000))
    
    app.run(
        host='0.0.0.0', 
        port=port, 
        debug=(os.getenv('FLASK_ENV', 'development') == 'development')
    )

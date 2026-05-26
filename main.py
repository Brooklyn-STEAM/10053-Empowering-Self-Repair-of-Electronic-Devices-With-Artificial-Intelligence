from email.mime import image
import os
from flask import Flask, render_template, request, flash, redirect, abort, url_for, session, jsonify
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
import pymysql, re, sqlite3, mysql.connector, secrets, hashlib, pdfplumber, uuid
from dynaconf import Dynaconf
from scipy import stats
from ai_agent import run_agent
from datetime import datetime, timedelta
from anthropic import Anthropic
from openai import OpenAI
from werkzeug.security import generate_password_hash, check_password_hash
from flask_wtf import CSRFProtect
import base64
import uuid
import os

UPLOAD_FOLDER = os.path.join("static", "uploads")
from werkzeug.utils import secure_filename

app = Flask(__name__)
csrf = CSRFProtect(app)

config = Dynaconf(settings_file =["settings.toml", ".env"])

#client = OpenAI(api_key=config.get("OPENAI_API_KEY"))
#client = Anthropic(api_key=config.get("ANTHROPIC_API_KEY"))

app.secret_key = config.secret_key

app.config.update(
    SESSION_COOKIE_SECURE=False,  # Set to True in production with HTTPS
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE='Lax',
    PERMANENT_SESSION_LIFETIME=3600  # 1 hour
)

limiter = Limiter(
    app=app,
    key_func=get_remote_address,
    default_limits=["200 per day", "50 per hour"]
)

login_manager = LoginManager(app)

login_manager.login_view = "/login"

class User:
    is_authenticated = True
    is_active = True
    is_anonymous = False

    def __init__(self, result):
        self.name = result["Name"]
        self.email = result["Email"]
        self.address = result["Address"]
        self.id = result["ID"]
        self.password = result["Password"] 

    def get_id(self):
        return str(self.id)

@login_manager.user_loader  
def load_user(user_id):
    connection  = connect_db()
    cursor = connection.cursor()

    cursor.execute("SELECT * FROM `User` WHERE `ID` = %s ", (user_id,))

    result = cursor.fetchone()
    connection.close()
    if result is None:
        return None

    
    return User(result)


def connect_db():
    conn = pymysql.connect(
        host="db.steamcenter.tech",
        user = config.user,
        password = config.password,
        database="blueprint",
        autocommit= True,
        cursorclass= pymysql.cursors.DictCursor
    )
    return conn

def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()

@app.route("/")
def index():
    
    connection = connect_db()

    cursor = connection.cursor()

    cursor.execute("SELECT * FROM `RepairItems`")
    
    result = cursor.fetchmany(5)
    
    connection.close()

    return render_template("homepage.html.jinja", guides=result)


@app.route("/login", methods=["POST", "GET"])
@limiter.limit("5 per minute; 20 per hour")
def login_page():

    if request.method == "POST":

        email = request.form["email"].strip().lower()
        password = request.form["password"]

        connection = None
        cursor = None
        result = None
        connection = connect_db()
        cursor = connection.cursor()

        try:
            cursor.execute(
                "SELECT * FROM User WHERE Email = %s",
                (email,)
            )

            result = cursor.fetchone()

        finally:
            cursor.close()
            connection.close()

        if result is None:
            flash("Invalid email or password.", "error")
            return render_template("login.html.jinja")

        if not check_password_hash(result["Password"], password):
            flash("Invalid email or password.", "error")
            return render_template("login.html.jinja")

        # ✅ success
        session.pop("has_seen_greeting", None)
        login_user(User(result))
        session["has_seen_greeting"] = False

        flash("Welcome back!", "success")
        return redirect("/")

    return render_template("login.html.jinja")


@app.route("/signup", methods=["POST", "GET"])
@limiter.limit("3 per minute; 10 per hour")
def signup_page():

    if request.method == "POST":
        name = request.form["full_name"]
        email = request.form["email"]
        password = request.form["password"]
        confirm_password = request.form["confirm_password"]
        address = request.form["address"]

        if password != confirm_password:
            flash("Passwords do not match", "error")
        elif len(password) < 8:
            flash("Password must be at least 8 characters long", "error")
        else:
            connection = connect_db()

            cursor = connection.cursor()
            try:
                hashed_password = generate_password_hash(password)
                
                cursor.execute("""
                    INSERT INTO `User` (`Name`, `Email`, `Password`,  `Address`)
                    VALUES (%s, %s, %s, %s)
                """, (name, email, hashed_password, address))
                
            except pymysql.err.IntegrityError:
                flash("Email is already in use", "error")
                
            else:
                flash("Account created successfully!", "success")
                return redirect("/login")
            finally:
                cursor.close()
                connection.close()

    return render_template("signup.html.jinja")

@app.route("/forgot_password", methods=["GET", "POST"])
@limiter.limit("4 per minute")
def forgot_password():

    if request.method == "POST":

        email = request.form["email"].strip().lower()

        connection = None
        cursor = None

        try:
            connection = connect_db()
            cursor = connection.cursor()

            cursor.execute(
                "SELECT * FROM User WHERE Email = %s",
                (email,)
            )

            user = cursor.fetchone()

            # ONLY if account exists
            if user:

                # Generate secure token
                token = secrets.token_urlsafe(32)
                token_hash = hash_token(token)

                # Expiration = 1 hour from now
                expiry = datetime.now() + timedelta(hours=1)

                # Save token to DB
                cursor.execute("""
                    UPDATE User
                    SET ResetToken = %s,
                        ResetTokenExpiry = %s
                    WHERE Email = %s
                """, (token_hash, expiry, email))

                connection.commit()

                # TEMPORARY: print link in terminal
                print(f"""
                    RESET LINK:
                    http://127.0.0.1:5000/reset_password/{token}
                                    """)

        finally:
            if cursor:
                cursor.close()

            if connection:
                connection.close()

        flash(
            "If an account exists, a reset link has been sent.",
            "success"
        )

        return redirect("/login")

    return render_template("forgot_password.html.jinja")


@app.route("/reset_password/<token>", methods=["GET", "POST"])
@limiter.limit("5 per minute")
def reset_password(token):

    connection = None
    cursor = None

    try:
        connection = connect_db()
        cursor = connection.cursor()

        # Find matching token
        cursor.execute("""
            SELECT *
            FROM User
            WHERE ResetToken = %s
        """, (hash_token(token),))

        user = cursor.fetchone()

        # Invalid token
        if not user:
            flash("Invalid or expired reset link.", "error")
            return redirect("/forgot_password")

        # Expired token
        if datetime.now() > user["ResetTokenExpiry"]:
            flash("Reset link has expired.", "error")
            return redirect("/forgot_password")

        # FORM SUBMIT
        if request.method == "POST":

            password = request.form["password"]
            confirm_password = request.form["confirm_password"]

            # Password mismatch
            if password != confirm_password:
                flash("Passwords do not match.", "error")
                return render_template(
                    "reset_password.html.jinja"
                )

            # Password too short
            if len(password) < 8:
                flash(
                    "Password must be at least 8 characters.",
                    "error"
                )
                return render_template(
                    "reset_password.html.jinja"
                )

            # Hash new password
            hashed_password = generate_password_hash(password)

            # Update password + clear token
            cursor.execute("""
                UPDATE User
                SET Password = %s,
                    ResetToken = NULL,
                    ResetTokenExpiry = NULL
                WHERE ID = %s
            """, (hashed_password, user["ID"]))

            connection.commit()

            flash(
                "Password reset successfully. Please log in.",
                "success"
            )

            return redirect("/login")

    finally:
        if cursor:
            cursor.close()

        if connection:
            connection.close()

    return render_template("reset_password.html.jinja")

@app.route("/logout")
@login_required
def logout():

    session.pop("has_seen_greeting", None)
    logout_user()

    flash("You have been logged out successfully.", "success")

    return redirect("/")

# ============================================
# GAMIFICATION SYSTEM
# ============================================

BADGES = [
    {"name": "First Steps", "icon": "🌱", "description": "Complete your first repair", "requirement": 1},
    {"name": "Handy Helper", "icon": "🔧", "description": "Complete 5 repairs", "requirement": 5},
    {"name": "Repair Pro", "icon": "⚡", "description": "Complete 10 repairs", "requirement": 10},
    {"name": "Master Fixer", "icon": "🏆", "description": "Complete 25 repairs", "requirement": 25},
    {"name": "Eco Warrior", "icon": "🌍", "description": "Save the planet - 50 repairs", "requirement": 50},
    {"name": "Legend", "icon": "👑", "description": "100 repairs completed", "requirement": 100},
]

POINTS_PER_REPAIR = 100

def check_and_award_badges(user_id, repairs_completed):
    """Award any new badges the user qualifies for"""
    connection = connect_db()
    cursor = connection.cursor()
    new_badges = []
    try:
        with connection.cursor() as cursor:
            # Get already earned badges
            cursor.execute("SELECT badge_name FROM User_badges WHERE user_id = %s", (user_id,))
            earned = {row['badge_name'] for row in cursor.fetchall()}
            
            # Check each badge
            for badge in BADGES:
                if badge['name'] not in earned and repairs_completed >= badge['requirement']:
                    cursor.execute(
                        "INSERT INTO User_badges (user_id, badge_name, badge_icon, badge_description) VALUES (%s, %s, %s, %s)",
                        (user_id, badge['name'], badge['icon'], badge['description'])
                    )
                    new_badges.append(badge)
            connection.commit()
    finally:
        connection.close()
    return new_badges


@app.route('/complete_repair', methods=['POST'])
@login_required
def complete_repair():
    """Mark a repair as completed and award points/badges"""
    user_id = current_user.id
    guide_id = request.json.get('guide_id')
    
    if not guide_id:
        return jsonify({"error": "Guide ID required"}), 400
    
    connection = connect_db()
    try:
        with connection.cursor() as cursor:
            # Check if already completed (prevent farming points)
            cursor.execute(
                "SELECT 1 FROM completed_repairs WHERE user_id = %s AND guide_id = %s",
                (user_id, guide_id)
            )
            if cursor.fetchone():
                return jsonify({"already_done": True, "success": False, "message": "Repair already completed."})

            # Log completion
            cursor.execute(
                "INSERT INTO completed_repairs (user_id, guide_id) VALUES (%s, %s)",
                (user_id, guide_id)
            )
            
            # Update user stats
            cursor.execute(
                "UPDATE User SET points = points + %s, repairs_completed = repairs_completed + 1, level = FLOOR((repairs_completed + 1) / 5) + 1 WHERE ID = %s",
                (POINTS_PER_REPAIR, user_id)
            )
            
            # Get updated stats
            cursor.execute("SELECT points, repairs_completed, level FROM User WHERE ID = %s", (user_id,))
            stats = cursor.fetchone()
            print(stats)
            print(type(stats))
            connection.commit()
            
            # Check for new badges
            new_badges = check_and_award_badges(user_id, stats['repairs_completed'])
            
            return jsonify({
                "success": True,
                "points_earned": POINTS_PER_REPAIR,
                "total_points": stats['points'],
                "repairs_completed": stats['repairs_completed'],
                "level": stats['level'],
                "new_badges": new_badges
            })
    finally:
        connection.close()


@app.route('/leaderboard')
def leaderboard():
    """Top 10 users by points"""
    connection = connect_db()
    try:
        with connection.cursor(pymysql.cursors.DictCursor) as cursor:
            cursor.execute("SELECT Name AS username, points, repairs_completed, level FROM `User` ORDER BY points DESC LIMIT 10")
            top_user = cursor.fetchall()
        return render_template('leaderboard.html.jinja', users=top_user)
    finally:
        connection.close()


@app.route('/submit_repair', methods=['POST'])
@login_required
def submit_repair():
    # Safely check for the user depending on how your auth is set up
    if not current_user or not current_user.is_authenticated:
        return jsonify({"error": "Login required"}), 401
    
    # It's safer to use current_user.id if using Flask-Login, 
    # but we'll use session.get() safely based on your original code
    user_id = session.get('user_id') or current_user.id
    
    guide_id = request.form.get('guide_id')
    before_img = request.files.get('before_image')
    after_img = request.files.get('after_image')
    easy = request.form.get('easy_parts', '')
    difficult = request.form.get('difficult_parts', '')
    
    if not all([guide_id, before_img, after_img]):
        return jsonify({"error": "Missing fields"}), 400
    
    os.makedirs("static/repairs", exist_ok=True)
    import time
    ts = int(time.time())
    
    # 1. Sanitize the filenames so they are safe to use
    safe_before_filename = secure_filename(before_img.filename)
    safe_after_filename = secure_filename(after_img.filename)
    
    # 2. Use the safe variables in your path strings
    before_path = f"repairs/{user_id}_{ts}_before_{safe_before_filename}"
    after_path = f"repairs/{user_id}_{ts}_after_{safe_after_filename}"
    
    # 3. Save the files
    before_img.save(f"static/{before_path}")
    after_img.save(f"static/{after_path}")
    
    conn = connect_db()
    try:
        with conn.cursor() as cursor:
            # Check duplicate
            cursor.execute("SELECT id FROM completed_repairs WHERE user_id=%s AND guide_id=%s", (user_id, guide_id))
            if cursor.fetchone():
                return jsonify({"already_done": True})
            
            # Insert into repair_showcases
            cursor.execute("INSERT INTO repair_showcases (user_id, guide_id, before_image, after_image, easy_parts, difficult_parts) VALUES (%s,%s,%s,%s,%s,%s)",
                (user_id, guide_id, before_path, after_path, easy, difficult))
                
            # Insert into completed_repairs
            cursor.execute("INSERT INTO completed_repairs (user_id, guide_id) VALUES (%s, %s)", (user_id, guide_id))
            
            # Update user stats
            cursor.execute("UPDATE User SET points = points + %s, repairs_completed = repairs_completed + 1, level = FLOOR((repairs_completed + 1)/5) + 1 WHERE ID = %s",
                (POINTS_PER_REPAIR, user_id))
                
            # Fetch new stats to return to frontend
            cursor.execute("SELECT points, repairs_completed, level FROM User WHERE ID = %s", (user_id,))
            stats = cursor.fetchone()
            
            conn.commit()
            
        # Check badges outside the DB transaction block but before closing connection
        new_badges = check_and_award_badges(user_id, stats['repairs_completed'])
        
        return jsonify({
            "success": True, 
            "points_earned": POINTS_PER_REPAIR, 
            "total_points": stats['points'], 
            "level": stats['level'], 
            "new_badges": new_badges
        })
    except Exception as e:
        # Good practice to catch unexpected SQL errors in development
        print(f"Database error: {e}")
        return jsonify({"error": "A database error occurred"}), 500
    finally:
        conn.close()


@app.route('/user_repairs/<int:user_id>')
def user_repairs(user_id):
    conn = connect_db()
    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT username FROM users WHERE id = %s", (user_id,))
            user = cursor.fetchone()
            
            cursor.execute("""
                SELECT rs.*, g.Name as guide_name 
                FROM repair_showcases rs 
                LEFT JOIN guides g ON rs.guide_id = g.id 
                WHERE rs.user_id = %s 
                ORDER BY rs.created_at DESC
            """, (user_id,))
            repairs = cursor.fetchall()
            
        return render_template('user_repairs.html.jinja', user=user, repairs=repairs)
    finally:
        conn.close()



@app.route("/repairs")
def repair_page():

    return render_template("repairs.html.jinja")

@app.route("/phone_guides")
def phone_guides():
    connection = connect_db()

    cursor = connection.cursor()

    cursor.execute("SELECT * FROM `RepairItems`")
    
    result = cursor.fetchall()
    
    connection.close()

    return render_template("phone_guides.html.jinja", guides=result)


@app.route('/cost_calculator')
@limiter.limit("25 per minute")
def cost_calculator():
    return render_template('cost_calculator.html.jinja')

@app.route("/about_us")
def about_us():
    return render_template("about_us.html.jinja")

@app.route("/products")
def products():
    connection = connect_db()
    cursor = connection.cursor()

    cursor.execute("SELECT * FROM Product")
    products = cursor.fetchall()

    cursor.close()
    connection.close()

    return render_template("individual_products.html.jinja", products=products)



@app.route("/search", methods=["GET"])
@limiter.limit("30 per minute")
def search():
    query = request.args.get("q", "").strip()
    connection = connect_db()
    cursor = connection.cursor(pymysql.cursors.DictCursor)

    results = []
    if query:
        # Split into keywords, remove empty strings
        keywords = [word.strip() for word in query.split() if word.strip()]
        if not keywords:
            return render_template("search_results.html.jinja", query=query, results=[])

        # Build dynamic SQL with multiple LIKE conditions (AND logic)
        conditions = []
        params = []
        for kw in keywords:
            conditions.append("Name LIKE %s")
            params.append(f"%{kw}%")
        where_clause = " AND ".join(conditions)

        sql = f"""
            SELECT 
                ID,
                Name,
                Image,
                Price,
                'product' AS type
            FROM Product
            WHERE {where_clause}

            UNION ALL

            SELECT 
                ID,
                Name,
                Image,
                NULL AS Price,
                'repair_item' AS type
            FROM RepairItems
            WHERE {where_clause}
        """
        # Duplicate params for UNION (two sets of conditions)
        cursor.execute(sql, params + params)
        results = cursor.fetchall()

    connection.close()
    return render_template("search_results.html.jinja", query=query, results=results)

@app.route("/browse")
def browse():
    connection = connect_db()

    cursor = connection.cursor()

    cursor.execute("SELECT * FROM `Product` ") 

    result = cursor.fetchall()
    connection.close() 
    return render_template("browse.html.jinja" , products = result)

@app.route("/product/<int:product_id>")
def product_page(product_id):
    connection = connect_db()
    cursor = connection.cursor()

    try:
        # Get product
        cursor.execute("SELECT * FROM Product WHERE ID = %s", (product_id,))
        product = cursor.fetchone()

        if product is None:
            abort(404)

        # Get reviews
        cursor.execute("""
            SELECT Review.*, User.Name
            FROM Review
            JOIN User ON User.ID = Review.UserID
            WHERE Review.ProductID = %s
        """, (product_id,))
        reviews = cursor.fetchall()

    finally:
        cursor.close()
        connection.close()

    return render_template("individual_product.html.jinja", product=product, reviews=reviews)

@app.route("/product/<int:product_id>/review", methods=["POST"])
@login_required
def submit_review(product_id):

    rating = request.form.get("rating", 5)
    comment = request.form.get("comment", "").strip()

    try:
        rating = int(rating)
        rating = max(1, min(rating, 5))
    except:
        rating = 5

    conn = connect_db()
    cursor = conn.cursor()

    try:
        cursor.execute("""
            INSERT INTO Review (ProductID, UserID, Ratings, Comment)
            VALUES (%s, %s, %s, %s)
        """, (product_id, current_user.id, rating, comment))

        conn.commit()

        return redirect(url_for("product_page", product_id=product_id))

    finally:
        cursor.close()
        conn.close()

@app.errorhandler(404)
def page_not_found(e):
    return render_template("404.html.jinja"), 404

@app.route("/cart")
@login_required
def cart():
    connection = connect_db()
    cursor = connection.cursor(pymysql.cursors.DictCursor)  

    cursor.execute("""
        SELECT Cart.ProductID, Cart.Quantity, Product.Name, Product.Price, Product.Image
        FROM Cart
        JOIN Product ON Cart.ProductID = Product.ID
        WHERE Cart.UserID = %s
    """, (current_user.id,))

    cart_items = cursor.fetchall()

    cursor.close()
    connection.close()
    
    return render_template("cart.html.jinja", cart=cart_items)

@app.route('/guide/<int:id>')
def guide_detail(id):
    connection = connect_db()
    cursor = connection.cursor(pymysql.cursors.DictCursor)

    cursor.execute("SELECT * FROM `RepairGuides` WHERE ID = %s", (id,))
    guide = cursor.fetchone()

    guide_completed = False
    if current_user.is_authenticated:
        cursor.execute(
            "SELECT 1 FROM completed_repairs WHERE user_id = %s AND guide_id = %s",
            (current_user.id, id)
        )
        guide_completed = cursor.fetchone() is not None

    connection.close()

    if guide is None:
        return "Guide not found", 404

    return render_template('guides_detail.html.jinja', guide=guide, guide_completed=guide_completed)

@app.route('/repair-item/<int:id>')
def repair_item_detail(id):
    connection = connect_db()
    cursor = connection.cursor(pymysql.cursors.DictCursor)
    
    cursor.execute("SELECT * FROM RepairItems WHERE ID = %s", (id,))
    item = cursor.fetchone()

    cursor.execute("SELECT * FROM RepairGuides WHERE Repair_Item_ID = %s", (id,))
    guides = cursor.fetchall()

    connection.close()
    

    if item is None:
        return "Repair item not found", 404
    
    return render_template('repair_items.html.jinja', item=item, guides=guides)

@app.route("/cart/<int:product_id>/add_to_cart", methods=["POST"])
@login_required
def add_to_cart(product_id):

    try:
        quantity = int(request.form.get("quantity", 1))
        if quantity <= 0:
            raise ValueError
    except:
        flash("Invalid quantity", "error")
        return redirect(url_for("product_page", product_id=product_id))

    conn = connect_db()
    cursor = conn.cursor()

    try:
        cursor.execute("""
            INSERT INTO Cart (Quantity, ProductID, UserID)
            VALUES (%s, %s, %s)
            ON DUPLICATE KEY UPDATE
            Quantity = Quantity + VALUES(Quantity)
        """, (quantity, product_id, current_user.id))

        conn.commit()

    finally:
        cursor.close()
        conn.close()

    flash("Product added to cart successfully!", "cart_success")

    return redirect(url_for("cart"))

@app.route("/cart/<int:product_id>/update_qty", methods=["POST"])
@login_required
def update_quantity(product_id):

    connection = None
    cursor = None

    try:
        quantity = int(request.form.get("quantity", 1))

        if quantity < 1:
            flash("Quantity must be at least 1.", "error")
            return redirect("/cart")

        connection = connect_db()
        cursor = connection.cursor()

        cursor.execute("""
            UPDATE Cart
            SET Quantity = %s
            WHERE ProductID = %s AND UserID = %s
        """, (quantity, product_id, current_user.id))

        connection.commit()

        flash("Cart updated successfully!", "cart_success")

    except ValueError:
        flash("Invalid quantity.", "error")

    except Exception as e:
        if connection:
            connection.rollback()
        print(e)
        flash("Error updating quantity.", "error")

    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()

    return redirect("/cart")

@app.route("/cart/<int:product_id>/remove", methods=["POST"])
@login_required
def remove_from_cart(product_id):

    connection = None
    cursor = None

    try:
        connection = connect_db()
        cursor = connection.cursor()

        cursor.execute("""
            DELETE FROM Cart
            WHERE ProductID = %s AND UserID = %s
        """, (product_id, current_user.id))

        connection.commit()

        flash("Item removed from cart.", "cart_success")

    except Exception as e:
        if connection:
            connection.rollback()
        print(e)
        flash("Error removing item from cart.", "error")

    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()

    return redirect("/cart")

@app.route("/checkout", methods=["GET", "POST"])
@login_required
def checkout():
    connection = connect_db()
    cursor = connection.cursor()

    cursor.execute("""
        SELECT 
            Cart.ProductID AS product_id,
            Cart.Quantity AS quantity,
            Product.Price AS price,
            Product.Name AS name,
            Product.Image AS image
        FROM Cart
        JOIN Product ON Product.ID = Cart.ProductID
        WHERE Cart.UserID = %s
    """, (current_user.id,))

    cart_items = cursor.fetchall()

    if request.method == "POST":

        if not cart_items:
            return redirect("/cart")

        total = 0

        # ADDRESS (NOW VALID)
        street = request.form.get("street")
        city = request.form.get("city")
        state = request.form.get("state")
        zip_code = request.form.get("zip")

        # CREATE ORDER
        cursor.execute("""
            INSERT INTO orders (
                user_id, total_amount, status,
                street, city, state, zip, created_at
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, NOW())
        """, (
            current_user.id,
            0,
            "Pending",
            street,
            city,
            state,
            zip_code
        ))

        order_id = cursor.lastrowid

        # ITEMS
        for item in cart_items:
            product_id = item["product_id"]
            price = float(item["price"])
            quantity = int(request.form.get(f"quantity_{product_id}", item["quantity"]))

            if quantity <= 0:
                continue

            total += price * quantity

            cursor.execute("""
                INSERT INTO SalesCart (order_id, product_id, quantity)
                VALUES (%s, %s, %s)
            """, (order_id, product_id, quantity))

        # UPDATE TOTAL
        cursor.execute("""
            UPDATE orders
            SET total_amount = %s
            WHERE ID = %s
        """, (total, order_id))

        # CLEAR CART
        cursor.execute("""
            DELETE FROM Cart
            WHERE UserID = %s
        """, (current_user.id,))

        connection.commit()
        connection.close()

        return redirect("/thank_you")

    return render_template("checkout.html.jinja", cart=cart_items)

@app.route("/thank_you")
@login_required
def thank_you():
    return render_template("thank_you.html.jinja")


@app.route('/ai-help', methods=['POST'])
@limiter.limit("100 per hour")
@csrf.exempt
def ai_help():
   
    try:
        # Make session permanent

        session.permanent = True
        
        user_input = request.form.get("message", "")
        image = request.files.get("image")

        if image:
            # Limit to 5MB
            image.seek(0, 2)  # Seek to end
            size = image.tell()
            image.seek(0)  # Reset
            if size > 5 * 1024 * 1024:
                return jsonify({"reply": "⚠️ Image too large. Please upload under 5MB."}), 400
            
        guide_id = request.form.get("guide_id")
        
        image_path = None  # ✅ Track image path
        
        if image:
            os.makedirs("temp_uploads", exist_ok=True)
            filename = secure_filename(image.filename)
            unique_filename = f"{uuid.uuid4()}_{filename}"
            image_path = os.path.join("temp_uploads", unique_filename)
            image.save(image_path)
            if not user_input:
                user_input = "Please analyze this image and tell me what's wrong with the device."

        if "chat_history" not in session:
            session["chat_history"] = []

            # Keep only last 20 messages
            session["chat_history"] = session["chat_history"][-20:]

        # Save user message (note if image was uploaded)
        display_message = user_input
        if image_path:
            display_message = f"📷 [Image uploaded] {user_input}"
        session["chat_history"].append({"role": "user", "content": display_message})

        # ✅ Pass image_path to run_agent
        result = run_agent(
            user_input,
            session["chat_history"],
            guide_id=guide_id,
            image_path=image_path
        )

        session["chat_history"].append({"role": "ai", "content": result["summary"]})
        session.modified = True

        return jsonify({
            "reply": result.get("summary", str(result))
        })

    except Exception as e:
        return jsonify({
            "reply": f"Server error: {str(e)}"
        }), 500

@app.route('/chat-history', methods=['GET'])
def get_chat_history():
    session.permanent = True
    history = session.get("chat_history", [])
    return jsonify({"history": history})

@app.route('/clear-chat', methods=['POST'])
def clear_chat():
    session.permanent = True
    session["chat_history"] = []
    session.modified = True
    return jsonify({"status": "cleared"})

@app.route("/profile")
@login_required
def profile():
    """User profile page with stats + badges"""

    connection = connect_db()
    cursor = None

    try:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT ID AS id, Name AS name, Email AS email, profile_pic, points, repairs_completed, level FROM User WHERE ID = %s",
                (current_user.id,)
            )
            user = cursor.fetchone()
            
            cursor.execute("SELECT badge_name, badge_icon, badge_description, earned_at FROM User_badges WHERE user_id = %s ORDER BY earned_at DESC", (current_user.id,))
            badges = cursor.fetchall()
        
        # Calculate progress to next badge
        next_badge = next((b for b in BADGES if b['requirement'] > user['repairs_completed']), None)
        progress_percent = (user['repairs_completed'] / next_badge['requirement'] * 100) if next_badge else 100
        
        return render_template("profile.html.jinja", user=user, 
                               badges=badges,
                               all_badges=BADGES,
                               next_badge=next_badge, 
                               progress_percent=progress_percent)
    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()


# --------------------------------------------------

@app.route("/edit_profile")
@login_required
def edit_profile():
    return render_template("edit_profile.html.jinja")


# --------------------------------------------------

@app.route("/profile/update", methods=["POST"])
@login_required
@limiter.limit("3 per minute")
def update_profile():

    print("ROUTE HIT")
    print("FORM DATA:", request.form)

    name = request.form.get("name", "").strip()
    email = request.form.get("email", "").strip().lower()
    address = request.form.get("address", "").strip()

    if not name or not email:
        flash("Name and email are required.", "error")
        return redirect("/edit_profile")

    connection = None
    cursor = None

    try:
        connection = connect_db()
        cursor = connection.cursor()

        cursor.execute("""
            UPDATE User
            SET Name=%s, Email=%s, Address=%s
            WHERE ID=%s
        """, (name, email, address, current_user.id))

        connection.commit()

        flash("Profile updated successfully!", "success")
        return redirect("/profile")

    except Exception as e:
        print("UPDATE ERROR:", repr(e))
        if connection:
            connection.rollback()

        flash("An error occurred while updating your profile.", "error")
        return redirect("/edit_profile")

    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()


# --------------------------------------------------

@app.route("/upload_profile_pic", methods=["POST"])
@login_required
def upload_profile_pic():

    connection = None
    cursor = None

    try:
        data = request.get_json()

        if not data or "image" not in data:
            return jsonify({"success": False, "error": "No image provided"}), 400

        image_data = data["image"]

        if "," not in image_data:
            return jsonify({"success": False, "error": "Invalid image format"}), 400

        header, encoded = image_data.split(",", 1)

        binary_data = base64.b64decode(encoded)

        os.makedirs(UPLOAD_FOLDER, exist_ok=True)

        filename = f"{uuid.uuid4().hex}.jpg"
        filepath = os.path.join(UPLOAD_FOLDER, filename)

        with open(filepath, "wb") as f:
            f.write(binary_data)

        image_url = f"/static/uploads/{filename}"

        connection = connect_db()
        cursor = connection.cursor()

        cursor.execute("""
            UPDATE User
            SET Profile_pic = %s
            WHERE ID = %s
        """, (image_url, current_user.id))

        connection.commit()

        if cursor.rowcount == 0:
            return jsonify({"success": False, "error": "User not found"}), 400

        return jsonify({
            "success": True,
            "url": image_url
        })

    except Exception as e:
        print("UPLOAD ERROR:", repr(e))

        return jsonify({
            "success": False,
            "error": str(e)
        }), 500

    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()

@app.route("/orders")
@login_required
def orders():
    connection = connect_db()
    cursor = connection.cursor(pymysql.cursors.DictCursor)

    cursor.execute("""
        SELECT 
            o.ID,
            o.created_at,
            o.total_amount,
            o.status AS order_status,

            p.name AS product_name,
            p.image,
            sc.quantity,
            p.price,

            ot.status AS tracking_status,
            ot.location,
            ot.updated_at,
            ot.remarks,
            ot.shipping_carrier,
            ot.estimated_delivery_date

        FROM orders o
        LEFT JOIN SalesCart sc ON o.ID = sc.order_id
        LEFT JOIN Product p ON sc.product_id = p.ID
        LEFT JOIN order_tracking ot ON o.ID = ot.order_id
        WHERE o.user_id = %s
        ORDER BY o.ID DESC, ot.updated_at ASC
    """, (current_user.id,))

    results = cursor.fetchall()

    orders_dict = {}

    for row in results:
        order_id = row["ID"]

        # CREATE ORDER
        if order_id not in orders_dict:
            orders_dict[order_id] = {
                "id": order_id,
                "created_at": row["created_at"],
                "total_amount": row["total_amount"],
                "status": row["order_status"],
                "current_status": row["order_status"],
                "order_items": [],
                "tracking": [],
                "progress": 10
            }

        # ADD ITEM (ONLY IF EXISTS)
        if row["product_name"]:
            item = {
                "name": row["product_name"],
                "image": row["image"],
                "quantity": row["quantity"],
                "price": row["price"]
            }

            if item not in orders_dict[order_id]["order_items"]:
                orders_dict[order_id]["order_items"].append(item)

        # ADD TRACKING
        if row["tracking_status"]:
            tracking = {
                "status": row["tracking_status"],
                "location": row["location"],
                "updated_at": row["updated_at"],
                "remarks": row["remarks"],
                "carrier": row["shipping_carrier"],
                "eta": row["estimated_delivery_date"]
            }

            if tracking not in orders_dict[order_id]["tracking"]:
                orders_dict[order_id]["tracking"].append(tracking)

    cursor.close()
    connection.close()

    # CALCULATE STATUS + PROGRESS
    for order in orders_dict.values():

        if order["tracking"]:
            order["current_status"] = order["tracking"][-1]["status"]

        status = order["current_status"]

        order["progress"] = {
            "Processing": 25,
            "Shipped": 50,
            "Out for Delivery": 75,
            "Delivered": 100
        }.get(status, 10)

    return render_template("orders.html.jinja", orders=list(orders_dict.values()))
  
@app.route("/delete_account", methods=["POST"])
@login_required
def delete_account():
    connection = None
    cursor = None

    try:
        password = request.form.get("password", "").strip()

        print("FORM DATA:", request.form)

        if not password:
            flash("Password required.", "error")
            return redirect("/profile")

        if not check_password_hash(current_user.password, password):
            flash("Incorrect password.", "error")
            return redirect("/profile")

        connection = connect_db()
        cursor = connection.cursor()

        user_id = current_user.id
        print("Deleting user:", user_id)

        cursor.execute("DELETE FROM User WHERE ID = %s", (user_id,))
        connection.commit()

        logout_user()

        flash("Account deleted successfully.", "success")
        return redirect("/")

    except Exception as e:
        if connection:
            connection.rollback()

        print("DELETE ERROR:", e)
        flash("Error deleting account.", "error")
        return redirect("/profile")

    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()

@app.route("/map", methods=["GET"])
def map():
    connection = connect_db() 

    cursor = connection.cursor()

    cursor.execute("""SELECT * FROM `ShopLocation`""")

    result = [{"lat": row["Latitude"], "lng": row["Longitude"], "name": row["Name"], "address": row["Address"], "image": row["Image"]} for row in cursor.fetchall()]

    cursor.close()

    connection.close()

    return render_template("map.html.jinja", centers=result)

@app.route("/edit_review/<int:review_id>", methods=["POST"])
@login_required
def edit_review(review_id):

    connection = connect_db()
    cursor = connection.cursor()

    try:
        rating = request.form.get("rating")
        comment = request.form.get("comment")

        if not rating or not comment:
            return jsonify({"success": False, "error": "Missing data"}), 400

        cursor.execute("""
            UPDATE Review
            SET Ratings = %s, Comment = %s
            WHERE ID = %s AND UserID = %s
        """, (rating, comment, review_id, current_user.id))

        if cursor.rowcount == 0:
            return jsonify({"success": False, "error": "Not allowed or not found"}), 403
    
        connection.commit()

        return jsonify({
            "success": True,
            "rating": rating,
            "comment": comment
        })

    except Exception as e:
        connection.rollback()
        return jsonify({"success": False, "error": str(e)}), 500

    finally:
        cursor.close()
        connection.close()


@app.after_request
def add_security_headers(response):
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "SAMEORIGIN"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"

    return response

@app.route("/delete_review/<int:product_id>/<int:review_id>", methods=["POST"])
@login_required
def delete_review(product_id, review_id):

    connection = connect_db()
    cursor = connection.cursor()

    try:
        cursor.execute("""
            DELETE FROM Review
            WHERE ID = %s AND UserID = %s
        """, (review_id, current_user.id))

        if cursor.rowcount == 0:
            return jsonify({"success": False, "error": "Not found or not allowed"}), 403

        connection.commit()

        return jsonify({"success": True})

    except Exception as e:
        connection.rollback()
        return jsonify({"success": False, "error": str(e)}), 500

    finally:
        cursor.close()
        connection.close()

if __name__ == '__main__':
    app.run(debug=config.get("DEBUG", cast="@bool", default=False))
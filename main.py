from flask import Flask, render_template, request, flash, redirect, abort, url_for, session, jsonify
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
import pymysql, re, sqlite3, mysql.connector
from dynaconf import Dynaconf
from ai_agent import run_agent
from datetime import datetime
from anthropic import Anthropic
import re
from openai import OpenAI
import sqlite3
import pdfplumber





app = Flask(__name__)

if __name__ == "__main__":
    app.run(debug=True)

config = Dynaconf(settings_file =["settings.toml", ".env"])

client = OpenAI(api_key=config.get("OPENAI_API_KEY"))
client = Anthropic(api_key=config.get("ANTHROPIC_API_KEY"))

app.secret_key = config.secret_key

app.config.update(
    SESSION_COOKIE_SECURE=False,  # Set to True in production with HTTPS
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE='Lax',
    PERMANENT_SESSION_LIFETIME=3600  # 1 hour
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
        user = config.USER,
        password = config.password,
        database="blueprint",
        autocommit= True,
        cursorclass= pymysql.cursors.DictCursor
    )
    return conn

@app.route("/")
def index():
    
    connection = connect_db()

    cursor = connection.cursor()

    cursor.execute("SELECT * FROM `RepairItems`")
    
    result = cursor.fetchmany(5)
    
    connection.close()

    return render_template("homepage.html.jinja", guides=result)

@app.route("/login", methods=["POST", "GET"])
def login_page():

    if request.method == "POST":

        email = request.form["email"]
        password = request.form["password"]

        connection = None
        cursor = None

        try:
            connection = connect_db()
            cursor = connection.cursor()

            cursor.execute(
                "SELECT * FROM User WHERE Email = %s",
                (email,)
            )

            result = cursor.fetchone()

        finally:
            if cursor:
                cursor.close()
            if connection:
                connection.close()

        if result is None:
            flash("No user found. Please check your email or password.", "error")
            return render_template("login.html.jinja")

        if password != result["Password"]:
            flash("Incorrect password.", "error")
            return render_template("login.html.jinja")

        # ✅ success
        login_user(User(result))

        session["has_seen_greeting"] = False

        flash("Welcome back!", "success")

        return redirect("/")

    return render_template("login.html.jinja")

@app.route("/signup", methods=["POST", "GET"])
def signup_page():

    if request.method == "POST":
        name = request.form["full_name"]
        email = request.form["email"]
        password = request.form["password"]
        confirm_password = request.form["confirm_password"]
        address = request.form["address"]
        
        if password != confirm_password:
            flash("Passwords do not match")
        elif len(password) < 8:
            flash("Password is too short")
        else:
            connection = connect_db()

            cursor = connection.cursor()
            try:
                cursor.execute("""
                    INSERT INTO `User` (`Name`, `Email`, `Password`,  `Address`)
                    VALUES (%s, %s, %s, %s)
                """, (name, email, password, address))
                connection.close()
            except pymysql.err.IntegrityError:
                flash("Email is already in use")
                connection.close()
            else:
                return redirect("/login")


    return render_template("signup.html.jinja")

@app.route("/logout")
@login_required
def logout():

    session.pop("has_seen_greeting", None)
    logout_user()

    flash("You have been logged out successfully.", "success")

    return redirect("/")

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
def submit_review(product_id):
    rating = request.form.get("rating")
    comment = request.form.get("comment")


    connection = connect_db()
    cursor = connection.cursor()

    if not current_user.is_authenticated:
        return redirect(url_for("login"))

    

    # Save review to database
    cursor.execute("""
        INSERT INTO Review 
                (ProductID, UserID, Ratings, Comment)
        VALUES 
        (%s, %s, %s, %s)
    """, (product_id, current_user.id, rating, comment))


    connection.close()

    return redirect(url_for("product_page", product_id=product_id))

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

    connection.close()

    if guide is None:
        return "Guide not found", 404

    return render_template('guides_detail.html.jinja', guide=guide)

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
    except (ValueError, TypeError):
        flash("Invalid quantity", "error")
        return redirect(url_for("product_page", product_id=product_id))

    connection = connect_db()
    cursor = connection.cursor()

    cursor.execute("""
        INSERT INTO Cart (Quantity, ProductID, UserID)
        VALUES (%s, %s, %s)
        ON DUPLICATE KEY UPDATE
        Quantity = Quantity + VALUES(Quantity)
    """, (quantity, product_id, current_user.id))

    connection.commit()
    cursor.close()
    connection.close()

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
def ai_help():
    try:
        # Make session permanent
        session.permanent = True
        
        user_input = request.form.get("message", "")
        image = request.files.get("image")
        guide_id = request.form.get("guide_id")

        if image:
            image_path = f"static/uploads/{image.filename}"
            image.save(image_path)
            user_input += "\nUser uploaded an image."

        if "chat_history" not in session:
            session["chat_history"] = []

        session["chat_history"].append({"role": "user", "content": user_input})

        # Pass guide_id to run_agent
        result = run_agent(
            user_input,
            session["chat_history"],
            guide_id=guide_id
        )

        session["chat_history"].append({"role": "ai", "content": result["summary"]})
        
        # Explicitly save session
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
    user = get_user(current_user.id)
    return render_template("profile.html.jinja", user=user)

@app.route("/profile/update", methods=["POST"])
@login_required
def update_profile():
    name = re.sub(r'\s+', ' ', request.form.get("full_name", "").strip()).title()
    email = request.form.get("email", "").strip()
    address = request.form.get("address", "").strip()

    connection = connect_db()
    cursor = connection.cursor(pymysql.cursors.DictCursor)

    try:
        cursor.execute(
            "SELECT Name, Email, Address FROM User WHERE ID=%s",
            (current_user.id,)
        )

        old_user = cursor.fetchone()

        if old_user:
            if (
                old_user["Name"] == name and
                old_user["Email"] == email and
                old_user["Address"] == address
            ):
                flash("No changes detected", "error")
                return redirect("/edit_profile")

        cursor.execute("""
            UPDATE User
            SET Name=%s, Email=%s, Address=%s
            WHERE ID=%s
        """, (name, email, address, current_user.id))

        connection.commit()

        flash("Profile updated successfully!", "profile_success")

    except pymysql.err.IntegrityError:
        connection.rollback()
        flash("Email already exists", "error")

    finally:
        cursor.close()
        connection.close()

    return redirect("/profile")
@app.route("/edit_profile")
@login_required
def edit_profile():
    user = get_user(current_user.id)
    return render_template("edit_profile.html.jinja", user=user)

def get_user(user_id):
    connection = connect_db()
    cursor = connection.cursor(pymysql.cursors.DictCursor)

    cursor.execute(
        "SELECT * FROM User WHERE ID = %s",
        (user_id,)
    )

    user = cursor.fetchone()

    cursor.close()
    connection.close()

    return user

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
        connection = connect_db()
        cursor = connection.cursor()

        user_id = current_user.id

        # 1. Delete order tracking
        cursor.execute("""
            DELETE FROM order_tracking
            WHERE order_id IN (
                SELECT ID FROM orders WHERE user_id = %s
            )
        """, (user_id,))

        # 2. Delete sales cart items
        cursor.execute("""
            DELETE FROM SalesCart
            WHERE order_id IN (
                SELECT ID FROM orders WHERE user_id = %s
            )
        """, (user_id,))

        # 3. Delete orders
        cursor.execute("DELETE FROM orders WHERE user_id = %s", (user_id,))

        # 4. Delete reviews
        cursor.execute("DELETE FROM Review WHERE UserID = %s", (user_id,))

        # 5. Delete cart items
        cursor.execute("DELETE FROM Cart WHERE UserID = %s", (user_id,))

        # 6. Delete user
        cursor.execute("DELETE FROM User WHERE ID = %s", (user_id,))

        connection.commit()

    except Exception as e:
        if connection:
            connection.rollback()

        print(e)
        flash("Error deleting account. Please try again.", "error")
        return redirect("/profile")

    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()

    # logout AFTER deletion
    logout_user()

    flash("Account deleted successfully.", "success")

    return redirect("/")

@app.route("/map", methods=["GET"])
def map():
    connection = connect_db() 

    cursor = connection.cursor()

    cursor.execute("""SELECT * FROM `ShopLocation`""")

    result = [{"lat": row["Latitude"], "lng": row["Longitude"], "name": row["Name"], "address": row["Address"], "image": row["Image"]} for row in cursor.fetchall()]

    cursor.close()

    connection.close()

    return render_template("map.html.jinja", centers=result)


if __name__ == '__main__':
    app.run(debug=True)
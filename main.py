from flask import Flask, render_template, request, flash, redirect, abort, url_for, session, jsonify
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
import pymysql
from dynaconf import Dynaconf
from datetime import datetime
import mysql.connector



from openai import OpenAI

app = Flask(__name__)

config = Dynaconf(settings_file =["settings.toml"])

client = OpenAI(api_key=config.get("OPENAI_API_KEY"))
app.secret_key = config.secret_key

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

    cursor.execute("SELECT * FROM `User` WHERE `ID` = %s ", (user_id))

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

if __name__ == "__main__":
    app.run(debug=True)

@app.route("/")
def index():
    return render_template("homepage.html.jinja")

@app.route("/login", methods=["POST","GET"])
def login_page():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']


        connection = connect_db()
        cursor = connection.cursor()

        cursor.execute("SELECT * FROM `User`  WHERE `Email` = %s", (email))
        result = cursor.fetchone()
        connection.close()

        if result is None:
            flash("No user found. The email address and/or password you entered are invalid.")
        elif password != result["Password"]:
            flash("Incorrect Password")
        else:
            login_user(User(result))
            
            if "has_seen_greeting"  not in session:
                session["has_seen_greeting"] = False
            
            
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
    flash("You have been Logged Out")

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
    print(f"Search query: '{query}'")   # keep debug

    connection = connect_db()
    cursor = connection.cursor(pymysql.cursors.DictCursor)

    results = []
    if query:
        # Union products and repair items
        sql = """
            SELECT 
                ID,
                Name,
                Image,
                Price,
                'product' AS type
            FROM Product
            WHERE Name LIKE %s

            UNION ALL

            SELECT 
                ID,
                Name,
                Image,
                NULL AS Price,      -- RepairItems might not have price
                'repair_item' AS type
            FROM RepairItems
            WHERE Name LIKE %s
        """
        params = [f"%{query}%", f"%{query}%"]
        cursor.execute(sql, params)
        results = cursor.fetchall()
        print(f"Found {len(results)} total results")

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
        flash("Invalid quantity")
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

    flash("Product added to cart successfully!")
    return redirect('/cart')

@app.route("/cart/<int:product_id>/update_qty", methods=["POST"])
@login_required
def update_quantity(product_id):

    connection = None
    cursor = None

    try:
        quantity = int(request.form.get("quantity"))

        if quantity <= 0:
            flash("Quantity must be at least 1.")
            return redirect("/cart")

        connection = connect_db()
        cursor = connection.cursor()

        cursor.execute("""
            UPDATE Cart
            SET Quantity = %s
            WHERE ProductID = %s AND UserID = %s
        """, (quantity, product_id, current_user.id))

        connection.commit()

    except Exception as e:
        if connection:
            connection.rollback()
        print(e)
        flash("Error updating quantity.")

    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()

    return redirect("/cart")

@app.route("/cart/<int:product_id>/remove", methods=["POST"])
@login_required
def remove_from_cart(product_id):

    connection = connect_db()
    cursor = connection.cursor()

    cursor.execute("""
        DELETE FROM Cart
        WHERE ProductID = %s AND UserID = %s
    """, (product_id, current_user.id))

    connection.commit()
    cursor.close()
    connection.close()

    return redirect("/cart")

@app.route("/checkout", methods=["GET", "POST"])
@login_required
def checkout():
    connection = connect_db()
    cursor = connection.cursor()

    # GET CART ITEMS
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

        total = 0

        # CREATE ORDER FIRST
        cursor.execute("""
            INSERT INTO orders (user_id, total_amount, status, created_at)
            VALUES (%s, %s, %s, NOW())
        """, (current_user.id, 0, "Pending"))

        order_id = cursor.lastrowid

        # ADD ITEMS TO SalesCart
        for item in cart_items:
            product_id = item["product_id"]
            quantity = item["quantity"]
            price = item["price"]

            total += price * quantity

            cursor.execute("""
                INSERT INTO SalesCart (order_id, product_id, quantity)
                VALUES (%s, %s, %s)
            """, (order_id, product_id, quantity))

        # UPDATE ORDER TOTAL
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

@app.route("/profile")
@login_required
def profile():
    return render_template("profile.html.jinja")

@app.route("/profile/update", methods=["POST"])
@login_required
def update_profile():
    name = request.form["full_name"]
    email = request.form["email"]
    address = request.form["address"]

    connection = connect_db()
    cursor = connection.cursor()

    try:
        cursor.execute("""
            UPDATE `User`
            SET `Name` = %s, `Email` = %s, `Address` = %s
            WHERE `ID` = %s
        """, (name, email, address, current_user.id))
        connection.commit()
    except pymysql.err.IntegrityError:
        flash("Email is already in use")
    finally:
        cursor.close()
        connection.close()

    return redirect("/profile")


def format_date(value, format='%B %d, %Y, %I:%M %p'):
    try:
        return value.strftime(format)
    except:
        return value

app.jinja_env.filters['date'] = format_date

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
@app.route('/ai-help', methods=['POST'])
def ai_help():
    user_input = request.form.get("message")
    image = request.files.get("image")

    image_path = None

    if image:
        image_path = f"static/uploads/{image.filename}"
        image.save(image_path)

    # 🔥 ALWAYS call AI (with or without image)
    response = call_ai(user_input, image_path)

    return jsonify({"reply": response})

def load_repair_knowledge():
    try:
        with open("repair_knowledge.txt", "r") as f:
            return f.read()
    except:
        return ""

user_sessions = {}

user_sessions = {}

def call_ai(user_input, image_path=None):
    knowledge = load_repair_knowledge()

    connection = connect_db()
    cursor = connection.cursor(pymysql.cursors.DictCursor)

    cursor.execute("SELECT ID, Name FROM RepairGuides")
    guides = cursor.fetchall()
    connection.close()

    user_id = "default"

    if not user_input and image_path:
        return """
📷 I see you uploaded an image.

What device is this and what seems to be the issue?
"""

    if not user_input:
        return "Please describe your issue."

    user_input_lower = user_input.lower()

    # 🔹 Handle step-by-step
    if user_input_lower == "next step":
        if user_id in user_sessions:
            steps = user_sessions[user_id]
            if steps:
                next_step = steps.pop(0)
                return f"➡️ Next step:<br>{next_step}"
            else:
                return "✅ You're done! You've completed all steps."

    keywords = {
        "battery": ["battery", "charge", "power", "dead"],
        "screen": ["screen", "display", "crack", "touch"],
        "camera": ["camera", "lens", "photo"]
    }

    best_match = None

    for guide in guides:
        for key, words in keywords.items():
            if any(word in user_input_lower for word in words):
                if key in guide["Name"].lower():
                    best_match = guide
                    break

    # 🔹 Extract steps
    steps = []
    for line in knowledge.split("\n"):
        if "step" in line.lower() and any(word in line.lower() for word in user_input_lower.split()):
            steps.append(line.strip())

    steps = steps[:3]

    # 🔹 Save steps for session
    user_sessions[user_id] = steps.copy()

    # 🔹 Format steps OUTSIDE f-string
    if steps:
        step_text = ""
        for i, step in enumerate(steps, 1):
            step_text += f"{i}. {step}<br>"
    else:
        step_text = "1. Turn off your device<br>2. Inspect for damage<br>3. Follow the guide below<br>"

    # 🔹 Final response
    if best_match:
        return f"""
🔧 <b>{best_match['Name']} detected</b><br><br>

Here are the first steps you should try:<br><br>

{step_text}

👉 <a href="/guide/{best_match['ID']}" target="_blank" style="color:#60a5fa;">Open Full Repair Guide</a><br><br>

Reply <b>next step</b> and I’ll guide you further.
"""

    return """
I couldn't find a clear match.<br><br>

Try:
- my screen is cracked<br>
- battery drains fast<br>
- camera not working
"""

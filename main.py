from flask import Flask, render_template, request, flash, redirect, abort, session
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
import pymysql
from dynaconf import Dynaconf


app = Flask(__name__)

config = Dynaconf(settings_file =["settings.toml"])

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


    return render_template("repairs.html.jinja")

    return render_template("404.html.jinja")


@app.route("/repairs")
def repairPage():
    return render_template("repairs.html.jinja")

@app.route("/about_us")
def aboutus():
    return render_template("about_us.html.jinja")

@app.route("/404")
def error():
    return render_template("404.html.jinja")

@app.route("/products")
def products():
    connection = connect_db()

    cursor = connection.cursor()

    cursor.execute("SELECT * FROM `Product` ") 

    result = cursor.fetchall()
    connection.close() 
    return render_template("products.html.jinja" , products = result)

    

@app.route("/search", methods=["GET"])
def search():
    query = request.args.get("q", "").strip()

    connection = connect_db()
    cursor = connection.cursor(pymysql.cursors.DictCursor)

    results = []

    if query:
        sql = """
            SELECT *
            From Product
            WHERE Name LIKE %s
        """
        params = [f"%{query}%"]
        cursor.execute(sql, params)
        results = cursor. fetchall()
    
    connection.close()

    return render_template("search_results.html.jinja", query=query, results = results)

@app.route("/browse")
def browse():
    connection = connect_db()

    cursor = connection.cursor()

    cursor.execute("SELECT * FROM `Product` ") 

    result = cursor.fetchall()
    connection.close() 
    return render_template("browse.html.jinja" , products = result)


@app.route("/product/<product_id>")
def product_page(product_id):
 
    connection = connect_db()

    cursor = connection.cursor()

    cursor.execute("SELECT * FROM `Product` WHERE `ID` = %s", (product_id,) )

    result = cursor.fetchone()

    cursor.close()

    connection = connect_db()

    cursor = connection.cursor()

    cursor.execute("""
    SELECT * FROM `Review`
    
    JOIN `User` ON `Review`.`UserID` = `User`.`ID` 
                   
    WHERE `ProductID` = %s
    
    """, (product_id,) )

    review = cursor.fetchall()

    connection.close() 

    if result is None:
        abort(404)
    return render_template("product.html.jinja", product=result , review=review)


@app.route("/product/<int:product_id>/add_to_cart", methods=["POST"])
@login_required
def add_to_cart(product_id):

    try:
        quantity = int(request.form["qty"])
        if quantity <= 0:
            raise ValueError
    except (KeyError, ValueError):
        flash("Invalid quantity")
        return redirect(f"/product/{int(product_id)}")

    connection = connect_db()
    cursor = connection.cursor()

    cursor.execute("""
        INSERT INTO `Cart` (`Quantity`, `ProductID`, `UserID`)
        VALUES (%s, %s, %s)
        ON DUPLICATE KEY UPDATE
        `Quantity` = `Quantity` + VALUES(`Quantity`)
    """, (quantity, product_id, current_user.id))
    
    connection.commit()
    connection.close()

    return redirect('/cart')

@app.route("/cart/<int:product_id>/update_qty", methods=["POST"])
@login_required
def update_qty(product_id):

    try:
        quantity = int(request.form.get("Quantity", 1))

        if quantity <= 0:
            flash("Quantity must be at least 1.")
            return redirect("/cart")

        connection = connect_db()
        cursor = connection.cursor()

        cursor.execute("""
            UPDATE Cart
            SET quantity = %s
            WHERE ProductID = %s AND UserID = %s
        """, (quantity, product_id, current_user.id))

        connection.commit()

    except Exception as e:
        connection.rollback()
        print(e)
        flash("Error updating quantity.")

    finally:
        cursor.close()
        connection.close()

    return redirect("/cart")

@app.route("/cart") 
def cart():
    connection = connect_db()

    cursor = connection.cursor()
    cursor.execute("""
            SELECT * FROM `Cart` 
            JOIN `Product` ON `Cart`.`ProductID` = `Product`.`ID`
            WHERE `UserID` =  %s 
            """, (current_user.id,) )
    result = cursor.fetchall()

    connection.close()
    return render_template("cart.html.jinja", cart=result)

@app.route("/cart/<product_id>/remove", methods=["POST"])
@login_required
def remove(product_id):
   
    connection = connect_db()
    cursor = connection.cursor()
    
    cursor.execute("""
        DELETE FROM `Cart` 
        WHERE `ProductID` =%s AND `UserID` = %s
        """, (product_id, current_user.id) )
    connection.close()

    return redirect('/cart')

 @app.route("/cart/<product_id>/update_qty", methods=["POST"])
@login_required
def update_cart(product_id):
    new_quantity = request.form["Quantity"]
    connection = connect_db()
    cursor = connection.cursor()
    
    cursor.execute("""
        UPDATE `Cart` 
        SET `Quantity` = %s
        WHERE `ProductID` =%s AND `UserID` = %s
        """, (new_quantity, product_id, current_user.id) )

@app.route("/product/<product_id>/add_to_cart", methods=["POST"])
@login_required
def add_to_cart(product_id):

    try:
        quantity = int(request.form.get("qty", 1))
        if quantity <= 0:
            return redirect("/products")
    except ValueError:
        return redirect("/products")
    quantity = int(request.form["qty"])

    connection = connect_db()
    cursor = connection.cursor()

    cursor.execute("""
        INSERT INTO Cart (Quantity, ProductID, UserID)
        VALUES (%s, %s, %s)
        ON DUPLICATE KEY UPDATE
        Quantity = Quantity + %s
    """, (quantity, product_id, current_user.id, quantity))

    connection.commit()
    cursor.close()
    connection.close()

    return redirect("/cart")

@app.route("/cart/<product_id>/remove", methods=["POST"])
@login_required
def remove(product_id):

    connection = connect_db()
    cursor = connection.cursor()

    cursor.execute("""
        DELETE FROM Cart 
        WHERE ProductID = %s AND UserID = %s
    """, (product_id, current_user.id))

    connection.commit() 
    cursor.close()
    connection.close()

    return redirect('/cart')


@app.route("/checkout", methods=["GET", "POST"])
@login_required
def checkout():
    connection = connect_db()

    cursor = connection.cursor()
    cursor.execute("""
        SELECT * FROM `Cart` 
        JOIN `Product` ON `Cart`.`ProductID` = `Product`.`ID`
        WHERE `UserID` =  %s 
        """, (current_user.id,) )
    result = cursor.fetchall()

    sale = cursor.lastrowid
    if request.method == "POST":
        # create the sale in the database
        cursor.execute("INSERT INTO `Sale` (`UserID`) VALUES (%s)", (current_user.id,))
        sale = cursor.lastrowid  # Retrieve the last inserted sale ID
        # store products bought
        for item in result:
            cursor.execute("INSERT INTO `SaleProduct` (`SaleID`, `ProductID`, `Quantity`) VALUES (%s, %s, %s)", (sale, item['ID'], item['quantity']))
        # empty cart
        cursor.execute("DELETE FROM `Cart` WHERE `UserID` = %s", (current_user.id,))
        # thank you screen
        return redirect('/thank_you')

    connection.close()

    return render_template("checkout.html.jinja" , cart=result)

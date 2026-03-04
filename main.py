from flask import Flask, render_template, request, flash, redirect, abort, url_for, session
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

@app.route("/about_us")
def about_us():
    return render_template("about_us.html.jinja")
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
def repairPage():
    return render_template("repairs.html.jinja")

@app.route("/about_us")
def aboutus():
    return render_template("about_us.html.jinja")

@app.errorhandler(404)
def page_not_found(e):
    return render_template("404.html.jinja"), 404

@app.route("/products")
def products():
    connection = connect_db()
    cursor = connection.cursor()

    cursor.execute("SELECT * FROM Product")
    products = cursor.fetchall()

    cursor.close()
    connection.close()

    return render_template("products.html.jinja", products=products)

@app.route("/cart")
@login_required
def cart():
    return render_template("cart.html.jinja")

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

@app.route("/product/<int:product_id>")
def product_page(product_id):
    connection = connect_db()
    cursor = connection.cursor()

    # Get the product
    cursor.execute("SELECT * FROM Product WHERE ID = %s", (product_id,))
    product = cursor.fetchone()
    
    if product is None:
        cursor.close()
        connection.close()
        abort(404)

    cursor.execute("SELECT * FROM Review WHERE ProductID = %s", (product_id,))
    review = cursor.fetchall()

    cursor.close()
    connection.close()

    return render_template("product.html.jinja", product=product, review=review)


@app.errorhandler(404)
def page_not_found(e):
    return render_template("404.html.jinja"), 404

@app.route("/cart")
@login_required
def cart():

    connection = connect_db()
    cursor = connection.cursor()

    cursor.execute("""
        SELECT * FROM Cart
        JOIN Product ON Cart.ProductID = Product.ID
        WHERE UserID = %s
    """, (current_user.id,))

    result = cursor.fetchall()

    connection.close()

    return render_template("cart.html.jinja", cart=result)


@app.route("/product/<int:product_id>/add_to_cart", methods=["POST"])
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


@app.route("/product/<product_id>/add_to_cart", methods=["POST"])
@login_required
def add_to_cart(product_id):

    try:
        quantity = int(request.form.get("qty", 1))
        if quantity <= 0:
            return redirect("/products")
    except ValueError:
        return redirect("/products")

@app.errorhandler(404)
def page_not_found(e):
    return render_template("404.html.jinja"), 404

@app.route("/cart")
@login_required
def cart():

    connection = connect_db()
    cursor = connection.cursor()

    cursor.execute("""
        SELECT * FROM Cart
        JOIN Product ON Cart.ProductID = Product.ID
        WHERE UserID = %s
    """, (current_user.id,))

    result = cursor.fetchall()

    connection.close()

    return render_template("cart.html.jinja", cart=result)


@app.route("/product/<int:product_id>/add_to_cart", methods=["POST"])
@login_required
def remove_from_cart(product_id):
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
    connection.close()

    return redirect('/cart')

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
    connection.close()

    return redirect('/cart')



@app.route("/checkout")
def checkout():
    return render_template("checkout.html.jinja")

@app.route("/checkout", methods=["GET", "POST"])
@login_required
def checkout():
    connection = connect_db()
    cursor = connection.cursor()
    cursor.execute("""
        SELECT * FROM `Cart`
        JOIN `Product` ON `Product`.`ID` = `Cart`.`ProductID`
        WHERE `UserID` = %s
    """, (current_user.id,))
    
    result = cursor.fetchall()
    if request.method == "POST":
        cursor.execute(
            "INSERT INTO `Sales` (`UserID`) VALUES (%s)",
            (current_user.id,)
        )
        sales = cursor.lastrowid
        for item in result:
            cursor.execute(
                "INSERT INTO `SalesCart` (`SalesID`, `ProductID`, `Quantity`) VALUES (%s, %s, %s)",
                (sales, item['ProductID'], item['Quantity'])
            )

        cursor.execute(
            "DELETE FROM `Cart` WHERE `UserID` = %s",
            (current_user.id,)
        )
        connection.commit()
        return redirect('/thank_you')
    connection.close()
    return render_template("checkout.html.jinja", cart=result)
 

@app.route("/thank_you")
@login_required
def thank_you():
    return render_template("thank_you.html.jinja")

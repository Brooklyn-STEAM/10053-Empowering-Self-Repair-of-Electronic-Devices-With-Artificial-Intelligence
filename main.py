from flask import Flask, render_template, request, flash, redirect, abort, session
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
import pymysql
from dynaconf import Dynaconf


app = Flask(__name__)

config = Dynaconf(settings_file =["settings.toml"])

app.secret_key = config.secret_key

login_manager = LoginManager(app)


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

def connect_db():
    conn = pymysql.connect(
        host="db.steamcenter.tech",
        user="cogboe",
        password = config.password,
        database="cogboe_heekaudio",
        autocommit= True,
        cursorclass= pymysql.cursors.DictCursor
    )
    return conn


@app.route("/")
def index():
    return render_template("homepage.html.jinja")
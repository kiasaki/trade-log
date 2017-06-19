import os
from hashlib import md5
from datetime import datetime
from collections import namedtuple
from flask import Flask, request, session, url_for, redirect, \
    render_template, abort, g, flash, _app_ctx_stack
from werkzeug import check_password_hash, generate_password_hash

from sqlalchemy import create_engine, select, MetaData, Table, Column, \
    Integer, String, ForeignKey


# Config
# ######################################

DATABASE = 'sqlite:///tradelog.db'
DEBUG = True if os.getenv('DEBUG', '0') == '1' else False
SERVER_NAME = 'localhost:' + os.getenv('PORT', '5000')
SECRET_KEY = os.getenv('SECRET_KEY', 'keyboard cat')

app = Flask('trade_log')
app.config.from_object(__name__)

engine = create_engine(DATABASE, echo=DEBUG)


# Tables
# ######################################

metadata = MetaData()
users = Table(
    'user', metadata,
    Column('user_id', Integer, primary_key=True),
    Column('username', String(24), nullable=False),
    Column('email', String(60)),
    Column('password', String(20), nullable=False)
)

accounts = Table(
    'account', metadata,
    Column('accounts_id', Integer, primary_key=True),
    Column('user_id', Integer, ForeignKey('user.user_id'), nullable=False),
    Column('name', String(64), nullable=False),
    Column('pref_value', String(100))
)


# Commands
# ######################################

@app.cli.command('initdb')
def initdb_command():
    """Creates the database tables."""
    metadata.create_all(engine, checkfirst=True)
    app.logger.info('initialized database')


# Utils
# ######################################

def objectify(obj):
    if isinstance(obj, dict):
        for key, value in obj.iteritems():
            obj[key] = objectify(value)
        return namedtuple('GenericDict', obj.keys())(**obj)
    elif isinstance(obj, list):
        return [objectify(item) for item in obj]
    else:
        return obj


def format_datetime(timestamp):
    """Format a timestamp for display."""
    return datetime.utcfromtimestamp(timestamp).strftime('%Y-%m-%d %H:%M')


def gravatar_url(email, size=80):
    """Return the gravatar image for the given email address."""
    return 'https://www.gravatar.com/avatar/%s?d=identicon&s=%d' % \
        (md5(email.strip().lower().encode('utf-8')).hexdigest(), size)


app.jinja_env.filters['datetimeformat'] = format_datetime
app.jinja_env.filters['gravatar'] = gravatar_url


# Database
# ######################################

def get_db():
    """Opens a new database connection if there is none yet for the
    current application context.
    """
    top = _app_ctx_stack.top
    if not hasattr(top, 'db'):
        top.db = engine.connect()
    return top.db


@app.teardown_appcontext
def close_database(exception):
    """Closes the database again at the end of the request."""
    top = _app_ctx_stack.top
    if hasattr(top, 'db'):
        top.db.close()


def db_exec(ins, **kwargs):
    return get_db().execute(ins, **kwargs)


def db_get_where(table, where):
    s = select([table]).where(where)
    result = db_exec(s)
    row = result.fetchone()
    result.close()
    return objectify(row)


# Middlewares
# ######################################

@app.before_request
def before_request():
    g.user = None
    app.logger.info(session)
    if 'user_id' in session:
        g.user = db_get_where(users, users.c.user_id == session['user_id'])


@app.errorhandler(404)
def page_not_found(error):
    return 'This page does not exist', 404


# Handlers
# ######################################

@app.route('/')
def marketing():
    if g.user:
        return redirect(url_for('dashboard'))
    return render_template('marketing.html')


@app.route('/d')
def dashboard():
    if not g.user:
        return redirect(url_for('marketing'))
    return render_template('dashboard.html')


@app.route('/accounts')
def accounts():
    pass


@app.route('/signin', methods=['GET', 'POST'])
def sign_in():
    if g.user:
        return redirect(url_for('dashboard'))
    error = None
    if request.method == 'POST':
        user = db_get_where(users, users.c.email == request.form['email'].lower())
        if user is None:
            error = 'Invalid email and password combination'
        elif not check_password_hash(user['password'], request.form['password']):
            error = 'Invalid email and password combination'
        else:
            flash('You are now logged in')
            session['user_id'] = user['user_id']
            app.logger.info(session)
            return redirect(url_for('dashboard'))
    return render_template('sign_in.html', error=error)


@app.route('/signup', methods=['GET', 'POST'])
def sign_up():
    if g.user:
        return redirect(url_for('dashboard'))
    error = None
    if request.method == 'POST':
        if not request.form['username']:
            error = 'You have to enter a username'
        elif not request.form['email'] or \
                '@' not in request.form['email']:
            error = 'You have to enter a valid email address'
        elif db_get_where(users, users.c.email == request.form['email'].lower()) is not None:
            error = 'The email is already taken'
        elif not request.form['password']:
            error = 'You have to enter a password'
        elif request.form['password'] != request.form['password2']:
            error = 'The two passwords do not match'
        elif db_get_where(users, users.c.username == request.form['username']) is not None:
            error = 'The username is already taken'
        else:
            ins = users.insert()
            db_exec(
                ins,
                username=request.form['username'],
                email=request.form['email'].lower(),
                password=generate_password_hash(request.form['password']),
            )
            flash('You were successfully registered and can login now')
            return redirect(url_for('sign_in'))
    return render_template('sign_up.html', error=error)


@app.route('/signout')
def sign_out():
    session.pop('user_id', None)
    return redirect(url_for('marketing'))


# Run
# ######################################

if __name__ == '__main__':
    app.run(debug=DEBUG)

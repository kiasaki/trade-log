import os
from hashlib import md5
from functools import wraps
from datetime import datetime
from collections import namedtuple
from flask import Flask, request, session, url_for, redirect, \
    render_template, abort, g, flash, _app_ctx_stack
from werkzeug import check_password_hash, generate_password_hash

from sqlalchemy import create_engine, select, MetaData, Table, Column, \
    Integer, Text, ForeignKey


# Config
# ######################################

# SQLite
LOCAL_DATABASE_URL = 'sqlite:///trade_log.db'
# Postgres
# LOCAL_DATABASE_URL = 'postgres://trade_log:trade_log@localhost:5432/trade_log'

DATABASE = os.getenv('DATABASE_URL', LOCAL_DATABASE_URL)
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
    Column('username', Text, nullable=False),
    Column('email', Text),
    Column('password', Text, nullable=False)
)
userst = users
usersc = users.c

accounts = Table(
    'account', metadata,
    Column('account_id', Integer, primary_key=True),
    Column('user_id', Integer, ForeignKey('user.user_id'), nullable=False),
    Column('name', Text, nullable=False),
)
accountst = accounts
accountsc = accounts.c

trades = Table(
    'trade', metadata,
    Column('trade_id', Integer, primary_key=True),
    Column('account_id', Integer, ForeignKey('account.account_id'), nullable=False),
    Column('entry_reason', Text, nullable=False),
    Column('exit_reason', Text, nullable=False),
    Column('analysis', Text, nullable=False),
)
tradest = trades
tradesc = trades.c


# Commands
# ######################################

@app.cli.command('initdb')
def initdb_command():
    """Creates the database tables."""
    metadata.create_all(engine, checkfirst=True)
    app.logger.info('database initialized')


@app.cli.command('resetdb')
def resetdb_command():
    """Drop and creates all tables"""
    metadata.drop_all(engine)
    metadata.create_all(engine)
    db_exec(
        userst.insert(),
        username='test',
        email='test@test.com',
        password=generate_password_hash('test'),
    )
    app.logger.info('database reset')


# Utils
# ######################################

def objectify(row):
    if row is None:
        return None
    obj = {}
    for (key, value) in row.items():
        obj[key] = value
    return namedtuple('GenericDict', obj.keys())(**obj)


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


def db_find_where(table, where):
    s = select([table]).where(where)
    result = db_exec(s)
    rows = result.fetchall()
    result.close()
    return [objectify(row) for row in rows]


# Middlewares
# ######################################

@app.before_request
def before_request():
    g.user = None
    if 'user_id' in session:
        g.user = db_get_where(userst, usersc.user_id == session['user_id'])


def load_account(func):
    @wraps(func)
    def decorated_function(*args, **kwargs):
        g.account = None
        g.accounts = db_find_where(accountst, accountsc.user_id == g.user.user_id)
        for account in g.accounts:
            if account.account_id == kwargs['account_id']:
                g.account = account
        if not g.account:
            return redirect(url_for('accounts'))
        return func(*args, **kwargs)
    return decorated_function


def sign_in_required(func):
    @wraps(func)
    def decorated_function(*args, **kwargs):
        if not g.user:
            return redirect(url_for('marketing'))
        return func(*args, **kwargs)
    return decorated_function


def sign_out_required(func):
    @wraps(func)
    def decorated_function(*args, **kwargs):
        if g.user:
            return redirect(url_for('accounts'))
        return func(*args, **kwargs)
    return decorated_function


@app.errorhandler(404)
def page_not_found(error):
    return 'This page does not exist', 404


# Handlers
# ######################################

@app.route('/')
@sign_out_required
def marketing():
    return render_template('marketing.html')


@app.route('/accounts')
@sign_in_required
def accounts():
    accounts = db_find_where(accountst, accountsc.user_id == g.user.user_id)
    if len(accounts) == 0:
        return redirect(url_for('accounts_create'))
    else:
        return redirect(url_for('account', account_id=accounts[0].account_id))


@app.route('/accounts/switch')
@sign_in_required
def accounts_switch():
    account_id = request.args['account_id']
    if account_id == 'new':
        return redirect(url_for('accounts_create'))
    return redirect(url_for('account', account_id=account_id))


@app.route('/accounts/create', methods=['GET', 'POST'])
@sign_in_required
def accounts_create():
    if request.method == 'POST':
        if len(request.form['name']) == 0:
            flash('You have to enter a name', category='danger')
        else:
            ins = accountst.insert()
            result = db_exec(ins, user_id=g.user.user_id, name=request.form['name'])
            flash('Account created')
            return redirect(url_for('account', account_id=result.inserted_primary_key[0]))
    return render_template('accounts_create.html')


@app.route('/accounts/<int:account_id>')
@sign_in_required
@load_account
def account(account_id):
    g.trades = db_find_where(tradest, tradesc.account_id == account_id)
    return render_template('account.html')


@app.route('/accounts/<int:account_id>/trades/create', methods=['GET', 'POST'])
@sign_in_required
@load_account
def trades_create(account_id):
    if request.method == 'POST':
        if len(request.form['entry_reason']) == 0:
            flash('You have to enter a reson for your entry', category='danger')
        else:
            ins = tradest.insert()
            result = db_exec(
                ins,
                account_id=g.account.account_id,
                entry_reason=request.form['entry_reason'],
                exit_reason='',
                analysis='',
            )
            flash('Trade created')
            return redirect(url_for(
                'trade',
                account_id=account_id,
                trade_id=result.inserted_primary_key[0],
            ))
    return render_template('trades_create.html')


@app.route('/accounts/<int:account_id>/trades/<int:trade_id>', methods=['GET', 'POST'])
@sign_in_required
@load_account
def trade(account_id, trade_id):
    g.trade = db_get_where(tradest, tradesc.trade_id == trade_id and tradesc.account_id == account_id)
    return render_template('trade.html')


@app.route('/signin', methods=['GET', 'POST'])
@sign_out_required
def sign_in():
    error = None
    if request.method == 'POST':
        user = db_get_where(userst, users.c.email == request.form['email'].lower())
        if user is None:
            error = 'Invalid email and password combination'
        elif not check_password_hash(user.password, request.form['password']):
            error = 'Invalid email and password combination'
        else:
            flash('You are now logged in')
            session['user_id'] = user.user_id
            return redirect(url_for('accounts'))
    return render_template('sign_in.html', error=error)


@app.route('/signup', methods=['GET', 'POST'])
@sign_out_required
def sign_up():
    error = None
    if request.method == 'POST':
        if not request.form['username']:
            error = 'You have to enter a username'
        elif not request.form['email'] or \
                '@' not in request.form['email']:
            error = 'You have to enter a valid email address'
        elif db_get_where(userst, users.c.email == request.form['email'].lower()) is not None:
            error = 'The email is already taken'
        elif not request.form['password']:
            error = 'You have to enter a password'
        elif request.form['password'] != request.form['password2']:
            error = 'The two passwords do not match'
        elif db_get_where(userst, users.c.username == request.form['username']) is not None:
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

import os
import sys
import time
import logging
from hashlib import md5
from datetime import datetime
from flask import Flask, request, session, url_for, redirect, \
    render_template, abort, g, flash, _app_ctx_stack
from werkzeug import check_password_hash, generate_password_hash

from sqlalchemy import create_engine, select, MetaData, Table, Column, \
    Integer, String, ForeignKey


# Config
# ######################################

DATABASE = 'sqlite:///tradelog.db'
DEBUG = True if os.getenv('DEBUG', '0') == '1' else False
SERVER_NAME = '127.0.0.1:' + os.getenv('PORT', '5000')
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
    app.log.info('initialized database')


# Template filters
# ######################################

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


def db_exec(ins):
    return get_db().execute(ins)


def db_get_where(table, where):
    s = select([table]).where(where)
    result = db_exec(s)
    row = result.fetchone()
    result.close()
    return row


# Middlewares
# ######################################

@app.before_request
def before_request():
    g.user = None
    if 'user_id' in session:
        g.user = db_get_where(users, users.c.id == session['user_id'])


# Handlers
# ######################################

@app.errorhandler(404)
def page_not_found(error):
    return 'This page does not exist', 404


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


@app.route('/signin')
def sign_in():
    pass


@app.route('/signup')
def sign_up():
    pass


@app.route('/signout')
def sign_out():
    flash('You are now logged out')
    session.pop('user_id', None)
    return redirect(url_for('marketing'))


# Run
# ######################################

if __name__ == '__main__':
    app.logger.debug(app.url_map)
    app.run(debug=DEBUG)

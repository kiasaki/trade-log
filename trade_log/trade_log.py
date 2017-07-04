import os
import pytz
import decimal
from datetime import datetime
from hashlib import md5
from functools import wraps
from datetime import datetime
from collections import namedtuple
from flask import Flask, request, session, url_for, redirect, \
    render_template, abort, g, flash, _app_ctx_stack, abort
from werkzeug import check_password_hash, generate_password_hash

from sqlalchemy import create_engine, select, MetaData, Table, Column, \
    BigInteger, Integer, Text, DateTime, Boolean, ForeignKey


# Config
# ######################################

# SQLite
LOCAL_DATABASE_URL = 'sqlite:///trade_log.db'
# Postgres
# LOCAL_DATABASE_URL = 'postgres://trade_log:trade_log@localhost:5432/trade_log'

DATABASE = os.getenv('DATABASE_URL', LOCAL_DATABASE_URL)
DEBUG = True if os.getenv('DEBUG', '0') == '1' else False
SECRET_KEY = os.getenv('SECRET_KEY', 'keyboard cat')

NEW_YORK_TZ = pytz.timezone('America/New_York')

ORDER_TYPES = ('buy', 'sell', 'sell_short', 'buy_to_cover',)

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
    Column('cash', BigInteger, nullable=False),
)
accountst = accounts
accountsc = accounts.c

trades = Table(
    'trade', metadata,
    Column('trade_id', Integer, primary_key=True),
    Column('account_id', Integer, ForeignKey('account.account_id'), nullable=False),
    # Provided
    Column('symbol', Text, nullable=False),
    Column('target_entry', BigInteger, nullable=False),
    Column('target_profit', BigInteger, nullable=False),
    Column('target_stop', BigInteger, nullable=False),
    Column('entry_reason', Text, nullable=False),
    Column('exit_reason', Text, nullable=False),
    Column('analysis', Text, nullable=False),
    # Computed
    Column('first_order_date', DateTime, nullable=False),
    Column('last_order_date', DateTime, nullable=False),
    Column('commissions', BigInteger, nullable=False),
    Column('is_short', Boolean, nullable=False),
    Column('avg_buy_price', BigInteger, nullable=False),
    Column('avg_sell_price', BigInteger, nullable=False),
    Column('profit', BigInteger, nullable=False),
    Column('quantity', Integer, nullable=False),
    Column('quantity_outstanding', Integer, nullable=False),
    Column('orders_count', Integer, nullable=False),
)
tradest = trades
tradesc = trades.c

orders = Table(
    'order', metadata,
    Column('order_id', Integer, primary_key=True),
    Column('trade_id', Integer, ForeignKey('trade.trade_id'), nullable=False),
    Column('account_id', Integer, ForeignKey('account.account_id'), nullable=False),
    Column('date', DateTime, nullable=False),
    Column('type', Text, nullable=False),
    Column('quantity', BigInteger, nullable=False),
    Column('price', BigInteger, nullable=False),
    Column('commission', BigInteger, nullable=False),
)
orderst = orders
ordersc = orders.c


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

class Entity:
    def __init__(self, **kwargs):
        self.__dict__ = kwargs


def objectify(row):
    if row is None:
        return None
    obj = {}
    for (key, value) in row.items():
        obj[key] = value
    return Entity(**obj)


def parse_decimal_to_bigint(text):
    """Parses a decimal string to a bigint where the last five numbers
    cents, lower than 1"""
    try:
        return int(decimal.Decimal(text) * 100000)
    except decimal.InvalidOperation:
        return None


def parse_int(text):
    try:
        return int(text)
    except ValueError:
        return None


def parse_datetime(text):
    try:
        return NEW_YORK_TZ.localize(datetime.strptime(text, '%Y-%m-%d %H:%M'))
    except ValueError:
        return None


def format_number(bignum):
    """Format a $ bigint for display."""
    if bignum is None:
        return None
    return "{:,.2f}".format(bignum / 100000).replace(',', ' ')


def format_datetime(date):
    """Format a datetime for display."""
    if date == 'now':
        return NEW_YORK_TZ.localize(datetime.now()).strftime('%Y-%m-%d %H:%M')
    return date.strftime('%Y-%m-%d %H:%M')


def gravatar_url(email, size=80):
    """Return the gravatar image for the given email address."""
    return 'https://www.gravatar.com/avatar/%s?d=identicon&s=%d' % \
        (md5(email.strip().lower().encode('utf-8')).hexdigest(), size)


app.jinja_env.filters['format_number'] = format_number
app.jinja_env.filters['format_datetime'] = format_datetime
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
        cash = parse_decimal_to_bigint(request.form['cash'])
        if len(request.form['name']) == 0:
            flash('You have to enter a name', category='danger')
        elif cash is None:
            flash('Account cash entered is not a number', category='danger')
        else:
            ins = accountst.insert()
            result = db_exec(ins, user_id=g.user.user_id, name=request.form['name'], cash=cash)
            flash('Account created')
            return redirect(url_for('account', account_id=result.inserted_primary_key[0]))
    return render_template('accounts_create.html')


@app.route('/accounts/<int:account_id>')
@sign_in_required
@load_account
def account(account_id):
    g.trades = sorted(
        db_find_where(tradest, tradesc.account_id == account_id),
        key=lambda o: o.last_order_date,
        reverse=True,
    )
    return render_template('account.html')


@app.route('/accounts/<int:account_id>/trades/create', methods=['GET', 'POST'])
@sign_in_required
@load_account
def trades_create(account_id):
    g.trade = Entity(
        trade_id=None, account_id=account_id,
        target_entry=None, target_profit=None, target_stop=None
    )
    if request.method == 'POST':
        target_entry = parse_decimal_to_bigint(request.form['target_entry'])
        target_profit = parse_decimal_to_bigint(request.form['target_profit'])
        target_stop = parse_decimal_to_bigint(request.form['target_stop'])

        if len(request.form['entry_reason']) == 0:
            flash('You have to enter a reson for your entry', category='danger')
        elif len(request.form['symbol']) == 0:
            flash('You have to enter the symbol you are trading', category='danger')
        elif target_entry is None:
            flash('Target entry price entered is not a number', category='danger')
        elif target_profit is None:
            flash('Target profit price entered is not a number', category='danger')
        elif target_stop is None:
            flash('Target stop price entered is not a number', category='danger')
        else:
            ins = tradest.insert()
            result = db_exec(
                ins,
                account_id=g.account.account_id,
                symbol=request.form['symbol'],
                target_entry=target_entry,
                target_profit=target_profit,
                target_stop=target_stop,
                entry_reason=request.form['entry_reason'],
                exit_reason='',
                analysis='',

                first_order_date=NEW_YORK_TZ.localize(datetime.now()),
                last_order_date=NEW_YORK_TZ.localize(datetime.now()),
                commissions=0,
                is_short=False,
                avg_buy_price=0,
                avg_sell_price=0,
                profit=0,
                quantity=0,
                quantity_outstanding=0,
                orders_count=0,
            )
            flash('Trade created')
            return redirect(url_for(
                'trade',
                account_id=account_id,
                trade_id=result.inserted_primary_key[0],
            ))
    return render_template('trades_form.html')


@app.route('/accounts/<int:account_id>/trades/<int:trade_id>/edit', methods=['GET', 'POST'])
@sign_in_required
@load_account
def trades_edit(account_id, trade_id):
    g.trade = db_get_where(tradest, tradesc.trade_id == trade_id and tradesc.account_id == account_id)
    if not g.trade:
        return abort(404)
    if request.method == 'POST':
        target_entry = parse_decimal_to_bigint(request.form['target_entry'])
        target_profit = parse_decimal_to_bigint(request.form['target_profit'])
        target_stop = parse_decimal_to_bigint(request.form['target_stop'])

        if len(request.form['entry_reason']) == 0:
            flash('You have to enter a reson for your entry', category='danger')
        elif len(request.form['symbol']) == 0:
            flash('You have to enter the symbol you are trading', category='danger')
        elif target_entry is None:
            flash('Target entry price entered is not a number', category='danger')
        elif target_profit is None:
            flash('Target profit price entered is not a number', category='danger')
        elif target_stop is None:
            flash('Target stop price entered is not a number', category='danger')
        else:
            stmt = tradest.update().where(tradesc.trade_id == trade_id).values(
                symbol=request.form['symbol'],
                target_entry=target_entry,
                target_profit=target_profit,
                target_stop=target_stop,
                entry_reason=request.form['entry_reason'],
                exit_reason=request.form['exit_reason'],
                analysis=request.form['analysis'],
            )
            db_exec(stmt)
            flash('Trade updated')
            return redirect(url_for(
                'trade',
                account_id=account_id,
                trade_id=g.trade.trade_id,
            ))
    return render_template('trades_form.html')


def update_trade_computed_fields(trade):
    orders = sorted(db_find_where(orderst, ordersc.trade_id == trade.trade_id), key=lambda o: o.date)
    trade.first_order_date = NEW_YORK_TZ.localize(datetime.now())
    trade.last_order_date = NEW_YORK_TZ.localize(datetime.now())
    trade.orders_count = len(orders)

    buy_prices = []
    sell_prices = []
    trade.profit = 0
    trade.commissions = 0
    trade.quantity = 0
    trade.quantity_outstanding = 0

    for i, o in enumerate(orders):
        trade.commissions += o.commission
        if o.type == 'buy' or o.type == 'sell_short':
            trade.quantity += o.quantity
        if o.type == 'buy' or o.type == 'buy_to_cover':
            buy_prices.append(o.price)
            trade.quantity_outstanding += o.quantity
        else:
            sell_prices.append(o.price)
            trade.quantity_outstanding -= o.quantity

        if o.type == 'buy' or o.type == 'sell':
            trade.is_short = False
        else:
            trade.is_short = True

        if o.type == 'sell' or o.type == 'sell_short':
            trade.profit += o.quantity * o.price
        else:
            trade.profit -= o.quantity * o.price

        if i == 0:
            trade.first_order_date = o.date
        if i == len(orders)-1:
            trade.last_order_date = o.date

    outstanding_value = 0
    outstanding_value_quantity = trade.quantity_outstanding
    for o in orders:
        if outstanding_value_quantity > 0 and o.type == 'sell_short':
            outstanding_value += min(o.quantity, outstanding_value_quantity) * o.price
            outstanding_value_quantity -= min(o.quantity, outstanding_value_quantity)
        if outstanding_value_quantity > 0 and o.type == 'buy':
            outstanding_value += min(o.quantity, outstanding_value_quantity) * o.price
            outstanding_value_quantity += min(o.quantity, outstanding_value_quantity)

    trade.profit += outstanding_value

    trade.avg_buy_price = sum(buy_prices) / max(len(buy_prices), 1)
    trade.avg_sell_price = sum(sell_prices) / max(len(sell_prices), 1)

    stmt = tradest.update().where(tradesc.trade_id == trade.trade_id).values(
        first_order_date=trade.first_order_date,
        last_order_date=trade.last_order_date,
        commissions=trade.commissions,
        is_short=trade.is_short,
        avg_buy_price=trade.avg_buy_price,
        avg_sell_price=trade.avg_sell_price,
        profit=trade.profit,
        quantity=trade.quantity,
        quantity_outstanding=trade.quantity_outstanding,
        orders_count=len(orders),
    )
    db_exec(stmt)


@app.route('/accounts/<int:account_id>/trades/<int:trade_id>', methods=['GET', 'POST'])
@sign_in_required
@load_account
def trade(account_id, trade_id):
    g.trade = db_get_where(tradest, tradesc.trade_id == trade_id and tradesc.account_id == account_id)
    g.orders = sorted(db_find_where(orderst, ordersc.trade_id == trade_id), key=lambda o: o.date)
    print(g.orders)
    return render_template('trade.html')


@app.route('/accounts/<int:account_id>/trades/<int:trade_id>/create', methods=['GET', 'POST'])
@sign_in_required
@load_account
def orders_create(account_id, trade_id):
    g.trade = db_get_where(tradest, tradesc.trade_id == trade_id and tradesc.account_id == account_id)
    if not g.trade:
        return abort(404)
    g.order = Entity(
        order_id=None, account_id=account_id, trade_id=trade_id,
        price=None, commission=None,
    )
    if request.method == 'POST':
        date = parse_datetime(request.form['date'])
        quantity = parse_int(request.form['quantity'])
        price = parse_decimal_to_bigint(request.form['price'])
        commission = parse_decimal_to_bigint(request.form['commission'])

        if date is None:
            flash('A valid date is required', category='danger')
        elif request.form['type'] not in ORDER_TYPES:
            flash('No hax plz', category='danger')
        elif quantity is None:
            flash('Quantity entered is not a number', category='danger')
        elif price is None:
            flash('Price entered is not a number', category='danger')
        elif commission is None:
            flash('Commission entered is not a number', category='danger')
        else:
            ins = orderst.insert()
            result = db_exec(
                ins,
                trade_id=trade_id,
                account_id=account_id,
                date=date,
                type=request.form['type'],
                quantity=quantity,
                price=price,
                commission=commission,
            )
            update_trade_computed_fields(g.trade)
            flash('Order created')
            return redirect(url_for(
                'trade',
                account_id=account_id,
                trade_id=trade_id,
            ))
    return render_template('orders_form.html')


@app.route('/accounts/<int:account_id>/orders/<int:order_id>/edit', methods=['GET', 'POST'])
@sign_in_required
@load_account
def orders_edit(account_id, order_id):
    g.order = db_get_where(orderst, ordersc.order_id == order_id and orsersc.account_id == account_id)
    if not g.trade:
        return abort(404)
    g.trade = db_get_where(tradest, tradesc.trade_id == g.order.trade_id)
    if request.method == 'POST':
        date = parse_datetime(request.form['date'])
        quantity = parse_int(request.form['quantity'])
        price = parse_decimal_to_bigint(request.form['price'])
        commission = parse_decimal_to_bigint(request.form['commission'])

        if date is None:
            flash('A valid date is required', category='danger')
        elif request.form['type'] not in ORDER_TYPES:
            flash('No hax plz', category='danger')
        elif quantity is None:
            flash('Quantity entered is not a number', category='danger')
        elif price is None:
            flash('Price entered is not a number', category='danger')
        elif commission is None:
            flash('Commission entered is not a number', category='danger')
        else:
            stmt = orderst.update().where(orderc.order_id == g.order.order_id).values(
                date=date,
                type=request.form['type'],
                quantity=quantity,
                price=price,
                commission=commission,
            )
            db_exec(stmt)
            update_trade_computed_fields(g.trade)
            flash('Order updated')
            return redirect(url_for(
                'trade',
                account_id=account_id,
                trade_id=g.trade.trade_id,
            ))
    return render_template('orders_form.html')


@app.route('/accounts/<int:account_id>/orders/<int:order_id>/delete')
@sign_in_required
@load_account
def orders_delete(account_id, order_id):
    where = ordersc.order_id == order_id and ordersc.account_id == account_id
    order = db_get_where(orderst, where)
    trade = db_get_where(tradest, tradesc.trade_id == order.trade_id)
    db_exec(orderst.delete().where(where))
    update_trade_computed_fields(trade)
    flash('Order deleted.', category='success')
    return redirect(url_for('trade', account_id=account_id, trade_id=order.trade_id))


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

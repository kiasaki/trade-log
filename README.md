# trade log

_keep a log of your trades, retrospect, learn from mistakes, and track profits & losses_

## intro

If you're learning / practicing active stock trading you probably realize it's
a skill like any other. In order to get better you need to learn from your
mistakes and successes. `trade-log` aims to make it painless and fun to keep
track of every trade you make.

trade log provides you with:

- multiple trading accounts
- account profit and loss for the day/week/month/all time
- attach screenshots to logs
- write a detailed reasoning for initiating the trade and exiting it
- input multiple orders for a log including:
  - date / symbol / share amt. / price / commission
- write down initial stop loss / profit target
- trade log will calculate days held / $ P&L / % P&L / % commission

## developing

The application is built using `Flask` and `SQLAlchemy`.

```
make
# or
FLASK_APP=trade_log/trade_log.py flask run
```

## license

MIT.

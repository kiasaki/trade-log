run:
	FLASK_APP=trade_log/trade_log.py flask run

install:
	pip install $(filter-out $@,$(MAKECMDGOALS))
	pip freeze >requirements.txt

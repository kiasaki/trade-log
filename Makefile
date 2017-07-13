run:
	FLASK_DEBUG=1 FLASK_APP=trade_log/trade_log.py flask run -h 0.0.0.0

manage:
	FLASK_DEBUG=1 FLASK_APP=trade_log/trade_log.py flask $(filter-out $@,$(MAKECMDGOALS))

deps:
	pip install -r requirements.txt

install:
	pip install $(filter-out $@,$(MAKECMDGOALS))
	pip freeze >requirements.txt

.PHONY: run manage install initdb

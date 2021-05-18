lint: black isort pylint flake8

format:
	pipenv run black .
	pipenv run isort .

black:
	pipenv run black --check .

isort:
	pipenv run isort --check .

flake8:
	pipenv run flake8 .

pylint:
	pipenv run pylint aiotractive

.PHONY: black isort flake8 pylint lint format

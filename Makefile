lint: black isort pylint flake8

format:
	black .
	isort .

black:
	black --check .

isort:
	isort --check .

flake8:
	flake8 .

pylint:
	pylint aiotractive

dist:
	python setup.py sdist bdist_wheel
	twine check dist/*

.PHONY: black isort flake8 pylint lint format dist

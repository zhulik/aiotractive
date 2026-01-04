lint: ruff mypy

format:
	ruff format .

ruff:
	ruff check .
	ruff format .

mypy:
	mypy aiotractive

test:
	pytest tests --cov=aiotractive --cov-report=term-missing

dist:
	python setup.py sdist bdist_wheel
	twine check dist/*

.PHONY: ruff mypy lint format test dist

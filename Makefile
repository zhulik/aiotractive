lint: ruff

format:
	ruff format .

ruff:
	ruff check .
	ruff format .

dist:
	python setup.py sdist bdist_wheel
	twine check dist/*

.PHONY: ruff lint format dist

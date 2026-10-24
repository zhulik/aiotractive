lint: ruff ty

format:
	ruff format .

ruff:
	ruff check .
	ruff format .

ty:
	ty check aiotractive

test:
	pytest tests --cov=aiotractive --cov-report=term-missing

dist:
	uv build
	twine check dist/*

.PHONY: ruff ty lint format test dist

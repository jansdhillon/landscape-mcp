.PHONY: test check lint pack

test:
	uv run pytest tests/unit -v

check:
	uv run ruff check src tests
	uv run ruff format --check src tests

lint:
	uv run ruff check --fix src tests
	uv run ruff format src tests

pack:
	charmcraft pack

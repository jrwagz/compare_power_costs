
.PHONY: .venv
.venv:
	uv venv --python python3.11 .venv
	. .venv/bin/activate && \
		uv pip install -r requirements.txt -r requirements-dev.txt

.PHONY: run
run:
	./compare_power_costs.py ./

.PHONY: lint
lint:
	ruff check .
	black --check .
	isort --check .

.PHONY: format
format:
	ruff check --fix .
	black .
	isort .

.PHONY: ready
ready: format lint
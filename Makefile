UV := /root/.local/bin/uv
PY := $(UV) run python

.PHONY: sync test prepare dist upload upload-testpypi

sync:
	$(UV) sync --group dev --group bench
	$(UV) run maturin develop --release

test:
	$(UV) run pytest -q
	cargo test

prepare:
	$(PY) scripts/update_readme.py

dist:
	$(UV) run maturin build --release --compatibility off --out dist

upload:
	$(UV) run twine upload dist/*

upload-testpypi:
	$(UV) run twine upload --repository testpypi dist/*

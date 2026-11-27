PYTHON ?= python3
SKILL_DIR := skills/experiment-isolation
SKILL_SCRIPTS := $(SKILL_DIR)/scripts

.PHONY: test lint validate lab lab-demo lab-reset

test:
	$(PYTHON) -m pytest -q

lint:
	uvx ruff check engine $(SKILL_SCRIPTS) lab seed tests

validate:
	PYTHONPATH=$(SKILL_SCRIPTS) $(PYTHON) -m unittest discover -s tests/skill -v

lab:
	bash lab/run.sh

lab-demo:
	bash lab/run.sh demo

lab-reset:
	bash lab/run.sh reset

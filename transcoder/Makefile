ROOT           := $(dir $(abspath $(lastword $(MAKEFILE_LIST))))
VENV           := $(ROOT).venv
APP_REQS       := $(ROOT)app/requirements.txt

JACKFIELD_ROOT := $(ROOT)../../jackfield
JACKFIELD_PY   := $(JACKFIELD_ROOT)/src/integrations/python
JACKFIELD_DIST := $(JACKFIELD_ROOT)/target/wheels
MATURIN        := $(JACKFIELD_ROOT)/.venv/bin/maturin

PIP := $(VENV)/bin/pip

.PHONY: venv wheel dev release clean

venv: $(VENV)/bin/activate

$(VENV)/bin/activate:
	python3 -m venv $(VENV)
	$(PIP) install -q --upgrade pip

wheel: venv
	cd $(JACKFIELD_PY) && $(MATURIN) build --release

dev: wheel
	$(PIP) install -r $(APP_REQS)
	$(PIP) install --find-links $(JACKFIELD_DIST) jackfield

release: venv
	$(PIP) install -r $(APP_REQS) jackfield

clean:
	rm -rf $(VENV)

ROOT     := $(dir $(abspath $(lastword $(MAKEFILE_LIST))))
VENV     := $(ROOT).venv
APP_REQS := $(ROOT)app/requirements.txt

PIP := $(VENV)/bin/pip

.PHONY: venv dev release clean

venv: $(VENV)/bin/activate

$(VENV)/bin/activate:
	python3 -m venv $(VENV)
	$(PIP) install -q --upgrade pip

dev: venv
	$(PIP) install -r $(APP_REQS)

release: venv
	$(PIP) install -r $(APP_REQS)

clean:
	rm -rf $(VENV)

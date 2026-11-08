PY ?= python

.PHONY: spec check trace view clean

spec:
	$(PY) scripts/gen_spec_plan.py

check:
	$(PY) scripts/gen_spec_plan.py --check
	$(PY) scripts/lint_spec_trace.py

trace:
	$(PY) scripts/lint_spec_trace.py

view:
	$(PY) scripts/gen_planned_case_view.py

clean:
	rm -rf scripts/__pycache__ data/__pycache__

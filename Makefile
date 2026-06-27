.PHONY: test unit eval ci-install ci-test ci-eval help

help:
	@echo "PoE2LI QA commands"
	@echo "  make unit        - run pytest unit tests"
	@echo "  make eval        - run eval harness (needs running API)"
	@echo "  make ci-install  - install test deps"
	@echo "  make ci-test     - install deps then run unit tests"
	@echo "  make ci-eval     - install deps then run eval harness"

unit:
	cd backend && python -m pytest tests -q

eval:
	cd backend && python tests/eval_agent.py --json

ci-install:
	cd backend && pip install -r requirements.txt
	cd backend && pip install -r tests/requirements-test.txt

ci-test: ci-install
	cd backend && python -m pytest tests -q

ci-eval: ci-install
	cd backend && python tests/eval_agent.py --json

.PHONY: bootstrap score pilot flywheel demo verify audit redteam redteam-model goal handoffs tamper discovery readiness-fixtures dashboard blueprint pilot-scenarios vercel-check

bootstrap:
	git config core.hooksPath deploygrade/.githooks
	chmod +x deploygrade/.githooks/pre-commit
	@echo "DeployGrade hook installed."

score:
	python3 -m deploygrade.engine.score deploygrade/fixtures/readiness-input.json

pilot:
	python3 -m deploygrade.harness.pilot_gate deploygrade/fixtures/readiness-input.json

flywheel:
	python3 -m deploygrade.harness.flywheel deploygrade/fixtures/learning-observation.json

demo:
	python3 -m deploygrade.harness.demo

verify:
	python3 -m unittest discover -s deploygrade/tests -v

audit:
	python3 -m deploygrade.harness.audit

redteam:
	python3 -m deploygrade.harness.redteam_precommit
	python3 -m unittest deploygrade.tests.test_pilot deploygrade.tests.test_knowledge -v
	python3 -m deploygrade.harness.redteam_full

# Goal-mode lifecycle: the JSONL audit log is a first-class output.
goal handoffs:
	python3 -m deploygrade.engine.orchestrator dry-run

tamper:
	python3 -m deploygrade.harness.tamper_chain

discovery:
	python3 -m deploygrade.engine.discovery deploygrade/fixtures/discovery_repos/mature --environment staging

redteam-model:
	python3 -m deploygrade.harness.redteam_model_routing

readiness-fixtures:
	python3 -m deploygrade.harness.readiness_fixtures

dashboard:
	python3 -m http.server 4173 --directory deploygrade/sites/dashboard

vercel-check:
	python3 -m unittest deploygrade.tests.test_vercel -v

blueprint:
	python3 -m deploygrade.harness.blueprint_bare

pilot-scenarios:
	python3 -m unittest deploygrade.tests.test_pilot -v

flywheel-hero:
	python3 -c "from deploygrade.engine.flywheel import hero; print(hero())"

integration:
	python3 -m unittest deploygrade.tests.test_integration -v

fallbacks:
	python3 -m unittest deploygrade.tests.test_fallbacks -v

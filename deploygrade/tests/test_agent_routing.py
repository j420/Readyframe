import tomllib
import unittest
from pathlib import Path

from deploygrade.engine.agent_policy import MODEL_ID, validate_agent_policy
from deploygrade.hooks.session_start import load_customer_memory


class AgentRoutingTests(unittest.TestCase):
    def _agents(self):
        return {path.stem: tomllib.loads(path.read_text())["agent"] for path in Path("deploygrade/agents").glob("*.toml")}

    def test_ten_agent_contracts_use_explicit_sol_5_6_and_preserve_sandboxes(self):
        agents = self._agents()
        validate_agent_policy(agents)
        self.assertTrue(all(agent["model"] == MODEL_ID for agent in agents.values()))

    def test_legacy_model_fallback_is_rejected(self):
        agents = self._agents()
        agents["risk"] = {**agents["risk"], "model": "terra"}
        with self.assertRaisesRegex(ValueError, "sol-5.6 required"):
            validate_agent_policy(agents)

    def test_session_start_loads_customer_isolated_memory_contract(self):
        memory = load_customer_memory("deploygrade/knowledge/customer-memory.json")
        self.assertEqual(memory["memory_scope"], "customer-isolated")

"""OMO Native install tests use synthetic configs in temporary directories only."""

import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("pull_omo_native", ROOT / "pull.py")
assert SPEC is not None and SPEC.loader is not None
pull = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(pull)

# Agent names OMO Native 5.1.0 defines (omo-ai bin/lib/setup-opencode-models.js NATIVE_AGENT_NAMES).
NATIVE_AGENT_NAMES = {
    "explore",
    "librarian",
    "omo-native-code-reviewer",
    "omo-native-gate-reviewer",
    "omo-native-qa-executor",
    "plan-consultant",
    "plan-reviewer",
}
GATEWAY_URL = "https://example.invalid/v1"


def omo_template() -> dict:
    return pull.read_jsonc_object(ROOT / "omo.jsonc")


def model_strings(value) -> list[str]:
    """Every `model` value inside a config subtree."""
    if isinstance(value, dict):
        found = [value["model"]] if isinstance(value.get("model"), str) else []
        for child in value.values():
            found.extend(model_strings(child))
        return found
    if isinstance(value, list):
        return [model for child in value for model in model_strings(child)]
    return []


class NativeTemplateTests(unittest.TestCase):
    def test_native_block_uses_only_native_agent_names(self) -> None:
        native = omo_template()["[native]"]
        self.assertEqual(set(native["agents"]), NATIVE_AGENT_NAMES)

    def test_native_categories_match_opencode_routing(self) -> None:
        template = omo_template()
        native = template["[native]"]["categories"]
        opencode = template["[opencode]"]["categories"]
        # Every OpenCode category is routed identically in native.
        for name, entry in opencode.items():
            self.assertEqual(native.get(name), entry, name)
        # Native adds only architect, whose builtin chain needs a Claude login.
        self.assertEqual(set(native) - set(opencode), {"architect"})

    def test_native_agents_follow_their_opencode_counterparts(self) -> None:
        template = omo_template()
        native = template["[native]"]["agents"]
        opencode = template["[opencode]"]["agents"]
        for native_name, opencode_name in (("explore", "explore"),
                                           ("librarian", "librarian"),
                                           ("plan-consultant", "metis"),
                                           ("plan-reviewer", "momus")):
            self.assertEqual(native[native_name], opencode[opencode_name], native_name)

    def test_native_commit_attribution_matches_opencode(self) -> None:
        template = omo_template()
        self.assertEqual(template["[native]"]["git_master"], template["[opencode]"]["git_master"])

    def test_telemetry_is_disabled_for_every_harness(self) -> None:
        self.assertEqual(omo_template()["telemetry"], {"enabled": False})

    def test_native_models_use_the_gateway_provider(self) -> None:
        models = model_strings(omo_template()["[native]"])
        self.assertTrue(models)
        self.assertTrue(all(model.startswith("codex/") for model in models), models)


class NativeOAuthRenderTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.enterContext(patch.object(pull, "NO_BACKUP", True))

    def test_oauth_routes_each_harness_to_its_own_subscription_provider(self) -> None:
        pull.install_omo_config(ROOT, self.tmp, "oauth", oauth=True)
        installed = pull.read_jsonc_object(self.tmp / "omo.jsonc")
        native_models = model_strings(installed["[native]"])
        opencode_models = model_strings(installed["[opencode]"])
        self.assertTrue(all(m.startswith("chatgpt-subscription/") for m in native_models), native_models)
        self.assertTrue(all(m.startswith("openai/") for m in opencode_models), opencode_models)

    def test_oauth_render_changes_nothing_but_provider_prefixes(self) -> None:
        pull.install_omo_config(ROOT, self.tmp, "oauth", oauth=True)
        installed = (self.tmp / "omo.jsonc").read_text(encoding="utf-8")
        normalized = installed.replace('"chatgpt-subscription/', '"codex/').replace('"openai/', '"codex/')
        self.assertEqual(normalized, (ROOT / "omo.jsonc").read_text(encoding="utf-8"))


class NativeModelsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.enterContext(patch.object(pull, "NO_BACKUP", False))
        self.models = self.tmp / "models.json"

    def install(self, env: dict, oauth: bool = False) -> str:
        with patch.dict(os.environ, env, clear=True), \
                contextlib.redirect_stdout(io.StringIO()), \
                contextlib.redirect_stderr(io.StringIO()) as err:
            pull.install_omo_native_models(ROOT, self.tmp, "stamp", oauth=oauth)
        return err.getvalue()

    def test_gateway_provider_mirrors_opencode_codex_models(self) -> None:
        self.install({"CODEX_BASE_URL": GATEWAY_URL})
        provider = json.loads(self.models.read_text(encoding="utf-8"))["providers"]["codex"]
        # The engine sends baseUrl verbatim, so it is rendered; the key stays an env reference.
        self.assertEqual(provider["baseUrl"], GATEWAY_URL)
        self.assertEqual(provider["apiKey"], "${CODEX_API_TOKEN}")
        self.assertEqual(provider["api"], "openai-responses")
        opencode = pull.read_jsonc_object(ROOT / "opencode.jsonc")["provider"]["codex"]["models"]
        by_id = {model["id"]: model for model in provider["models"]}
        self.assertEqual(set(by_id), set(opencode))
        sol = by_id["gpt-6.1-sol"]
        self.assertEqual(sol["contextWindow"], opencode["gpt-6.1-sol"]["limit"]["input"])
        self.assertEqual(sol["maxTokens"], opencode["gpt-6.1-sol"]["limit"]["output"])
        self.assertEqual(sol["input"], ["text", "image"])
        self.assertEqual(sol["cost"], {"input": 2.0, "output": 10.0, "cacheRead": 0.1, "cacheWrite": 2.5})
        # xhigh and max are unsupported unless mapped, and the template relies on both.
        self.assertEqual(sol["thinkingLevelMap"]["xhigh"], "xhigh")
        self.assertEqual(sol["thinkingLevelMap"]["max"], "max")
        self.assertNotIn("max", by_id["gpt-5.4"]["thinkingLevelMap"])

    def test_unrelated_providers_survive_and_rerun_is_stable(self) -> None:
        _ = self.models.write_text(json.dumps({"providers": {
            "mine": {"baseUrl": "https://mine.invalid", "api": "openai-completions", "models": []},
            "codex": {"baseUrl": "https://stale.invalid"},
        }}), encoding="utf-8")
        self.install({"CODEX_BASE_URL": GATEWAY_URL})
        providers = json.loads(self.models.read_text(encoding="utf-8"))["providers"]
        self.assertEqual(providers["mine"]["baseUrl"], "https://mine.invalid")
        self.assertEqual(providers["codex"]["baseUrl"], GATEWAY_URL)
        self.assertEqual(len(list(self.tmp.glob("models.json.bak-*"))), 1)
        before = self.models.read_text(encoding="utf-8")
        self.install({"CODEX_BASE_URL": GATEWAY_URL})
        self.assertEqual(self.models.read_text(encoding="utf-8"), before)

    def test_missing_gateway_url_leaves_models_untouched(self) -> None:
        stderr = self.install({})
        self.assertFalse(self.models.exists())
        self.assertIn("CODEX_BASE_URL", stderr)

    def test_oauth_leaves_models_untouched(self) -> None:
        _ = self.models.write_text('{"providers": {}}', encoding="utf-8")
        self.install({"CODEX_BASE_URL": GATEWAY_URL}, oauth=True)
        self.assertEqual(self.models.read_text(encoding="utf-8"), '{"providers": {}}')

    def test_unreadable_models_file_is_not_overwritten(self) -> None:
        _ = self.models.write_text("{ invalid", encoding="utf-8")
        stderr = self.install({"CODEX_BASE_URL": GATEWAY_URL})
        self.assertEqual(self.models.read_text(encoding="utf-8"), "{ invalid")
        self.assertIn("models.json", stderr)


class NativeSettingsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.enterContext(patch.object(pull, "NO_BACKUP", True))
        self.settings = self.tmp / "settings.json"

    def configure(self) -> str:
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()) as err:
            pull.ensure_omo_native_settings(self.tmp, "stamp")
        return err.getvalue()

    def test_rules_extension_is_disabled_and_other_settings_survive(self) -> None:
        _ = self.settings.write_text(json.dumps({
            "defaultProvider": "someone",
            "defaultModel": "their-model",
            "disabledBuiltinExtensions": ["ask-user"],
        }), encoding="utf-8")
        self.configure()
        settings = json.loads(self.settings.read_text(encoding="utf-8"))
        self.assertEqual(settings["disabledBuiltinExtensions"], ["ask-user", "rules"])
        self.assertEqual(settings["defaultProvider"], "someone")
        self.assertEqual(settings["defaultModel"], "their-model")
        before = self.settings.read_text(encoding="utf-8")
        self.configure()
        self.assertEqual(self.settings.read_text(encoding="utf-8"), before)

    def test_missing_settings_file_is_created(self) -> None:
        self.configure()
        self.assertEqual(json.loads(self.settings.read_text(encoding="utf-8")),
                         {"disabledBuiltinExtensions": ["rules"]})

    def test_settings_jsonc_takes_precedence_and_is_left_for_the_user(self) -> None:
        # The engine prefers settings.jsonc; rewriting it would drop the user's comments.
        jsonc = self.tmp / "settings.jsonc"
        _ = jsonc.write_text('{\n  // mine\n}\n', encoding="utf-8")
        stderr = self.configure()
        self.assertEqual(jsonc.read_text(encoding="utf-8"), '{\n  // mine\n}\n')
        self.assertFalse(self.settings.exists())
        self.assertIn("settings.jsonc", stderr)

    def test_invalid_settings_file_is_not_overwritten(self) -> None:
        _ = self.settings.write_text("{ invalid", encoding="utf-8")
        stderr = self.configure()
        self.assertEqual(self.settings.read_text(encoding="utf-8"), "{ invalid")
        self.assertIn("settings.json", stderr)


class NativeAgentDirTests(unittest.TestCase):
    def test_agent_dir_follows_omo_override_order(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, patch.object(Path, "home", return_value=Path(tmp)):
            with patch.dict(os.environ, {}, clear=True):
                self.assertEqual(pull.get_omo_agent_dir(), Path(tmp) / ".omo" / "agent")
            with patch.dict(os.environ, {"PI_CODING_AGENT_DIR": "/pi",
                                         "SENPI_CODING_AGENT_DIR": "/senpi"}, clear=True):
                self.assertEqual(pull.get_omo_agent_dir(), Path("/senpi"))
            with patch.dict(os.environ, {"OMO_CODING_AGENT_DIR": "/omo",
                                         "SENPI_CODING_AGENT_DIR": "/senpi"}, clear=True):
                self.assertEqual(pull.get_omo_agent_dir(), Path("/omo"))


if __name__ == "__main__":
    unittest.main()

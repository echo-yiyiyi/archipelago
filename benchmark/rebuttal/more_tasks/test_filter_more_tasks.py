"""Offline checks for sequential filtering and resumable model runs."""
import contextlib
from dataclasses import asdict
import importlib.util
import io
import json
import os
from pathlib import Path
import tempfile
import types
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("filter_more_tasks", HERE / "filter_more_tasks.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class MoreTasksTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.args = types.SimpleNamespace(output_dir=self.root, opus_provider="anthropic")
        self.candidates = []
        for bucket, domains in module.core.QUOTAS.items():
            score = {"score_1": 1., "score_075_1": .8, "score_05_075": .6}[bucket]
            for domain, quota in domains.items():
                for index in range(quota):
                    self.candidates.append(module.core.Candidate(
                        f"{bucket}_{domain}_{index}", domain, 35, score, bucket))
        self.tasks = {candidate.task_id: {"prompt": "Original prompt: " + candidate.task_id}
                      for candidate in self.candidates}
        self.report = {"attempts": []}
        self.calls = []

    def result(self, name, candidate, score):
        return {"model": name, "score": score,
                "matches_gemini_bucket": score is not None and module.core.score_bucket(score) == candidate.score_bucket,
                "driver_log": "offline", "error": "offline failure" if score is None else None,
                "run_id": f"offline_{len(self.calls)}"}

    def passing(self, name, candidate, *_):
        self.calls.append((name, candidate.task_id))
        return self.result(name, candidate, candidate.gemini_score)

    def select(self, candidates=None, launcher=None):
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            return module.select_tasks(candidates or self.candidates, self.report, self.args,
                                       self.root / "runtime", {}, self.tasks, launch=launcher or self.passing)

    def test_gpt_gates_opus_and_stops_at_fifteen(self):
        rejected = [module.core.Candidate("gpt_reject", "law", 31, 1., "score_1"),
                    module.core.Candidate("opus_reject", "law", 32, 1., "score_1")]
        extra = module.core.Candidate("excess_law", "law", 99, 1., "score_1")
        def launch(name, candidate, *args):
            self.calls.append((name, candidate.task_id))
            score = .5 if candidate.task_id == "gpt_reject" or (
                candidate.task_id == "opus_reject" and name == "opus") else candidate.gemini_score
            return self.result(name, candidate, score)
        self.assertEqual(self.select(rejected + self.candidates + [extra], launch), 0)
        self.assertNotIn(("opus", "gpt_reject"), self.calls)
        self.assertIn(("opus", "opus_reject"), self.calls)
        self.assertFalse(any(task_id == "excess_law" for _, task_id in self.calls))
        for index, (name, task_id) in enumerate(self.calls):
            if name == "opus":
                self.assertEqual(self.calls[index - 1], ("gpt_5_6_sol", task_id))
        selected = module.core.read_json(self.root / "selected_15_tasks.json")
        self.assertEqual(len(selected), 15)
        self.assertEqual(self.report["quota_counts"], module.core.QUOTAS)
        self.assertEqual({row["difficulty"] for row in selected}, {"easy", "medium", "hard"})
        before = list(self.calls)
        self.assertEqual(self.select(rejected + self.candidates + [extra], launch), 0)
        self.assertEqual(self.calls, before)

    def test_resume_retries_opus_without_rerunning_successful_gpt(self):
        def fail_opus(name, candidate, *_):
            self.calls.append((name, candidate.task_id))
            return self.result(name, candidate, None if name == "opus" else candidate.gemini_score)
        self.assertEqual(self.select(launcher=fail_opus), 3)
        self.assertEqual(len(self.calls), 2)
        first = self.candidates[0].task_id
        self.report = module.core.read_json(self.root / "attempts.json")
        self.assertEqual(self.select(), 0)
        self.assertEqual(self.calls.count(("gpt_5_6_sol", first)), 1)
        self.assertEqual(self.calls.count(("opus", first)), 2)
        self.assertEqual(len(module.core.read_json(self.root / "selected_15_tasks.json")), 15)

    def test_gpt_failure_stops_before_opus(self):
        def fail(name, candidate, *_):
            self.calls.append((name, candidate.task_id))
            return self.result(name, candidate, None)
        self.assertEqual(self.select(launcher=fail), 3)
        self.assertEqual(self.calls, [("gpt_5_6_sol", self.candidates[0].task_id)])
        self.assertEqual(module.core.read_json(self.root / "selected_15_tasks.json"), [])

    def test_original_selection_always_excluded(self):
        self.assertEqual(len(module.excluded_tasks([module.BUNDLED_SELECTION])), 15)
        with self.assertRaisesRegex(ValueError, "separate"):
            module.main(["--prepare-only", "--output-dir", str(module.OLD_OUTPUT)])

    def test_fresh_checkout_needs_no_old_outputs_or_gemini_trajectories(self):
        output = self.root / "portable"
        with patch.object(module, "OLD_SELECTION", self.root / "missing-old-selection.json"), \
             patch.object(module, "task_dataset", return_value=None), \
             patch.object(module.core, "collect_candidates", side_effect=AssertionError("must use bundled references")), \
             contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(module.main(["--prepare-only", "--output-dir", str(output)]), 0)
        inventory = module.core.read_json(output / "candidates.json")
        ids = {row["task_id"] for rows in inventory["buckets"].values() for row in rows}
        self.assertEqual(len(ids), 203)
        self.assertFalse(ids & module.excluded_tasks([module.BUNDLED_SELECTION]))

    def test_runtime_routes_both_agents_and_judge_to_azure(self):
        gpt = {"model": "azure/responses/sol", "azure_key_vault": {"secret_name": "example"},
               "extra_args": {"api_base": "https://example.openai.azure.com/", "reasoning": {"effort": "xhigh"}}}
        opus = {"model": "azure_ai/claude-opus-5", "extra_args": {
            "api_base": "https://example.services.ai.azure.com/anthropic", "reasoning_effort": "max"}}
        runtime = module.prepare_runtime(self.root, {"gpt_5_6_sol": gpt, "opus": opus})
        self.assertTrue((runtime / "runner/final_snapshot.py").is_file())
        config = module.core.read_json(runtime / "opus.json")
        self.assertEqual(config["model"], "anthropic/claude-opus-5")
        self.assertEqual(config["extra_args"]["api_base"], opus["extra_args"]["api_base"])
        self.assertNotIn("azure_key_vault", module.core.read_json(runtime / "gpt_5_6_sol.json"))
        judge = module.core.read_json(runtime / "grading_settings.json")
        self.assertEqual(judge["llm_judge_model"], "azure/sol")
        self.assertEqual(judge["llm_judge_extra_args"]["reasoning_effort"], "xhigh")
        self.assertNotIn("reasoning", judge["llm_judge_extra_args"])

    def test_preflight_rejects_non_azure_opus_endpoint(self):
        config = self.root / "opus.json"
        module.core.write_json_atomic(config, {"model": "anthropic/claude-opus-5", "extra_args": {
            "api_base": "https://api.anthropic.com"}})
        with self.assertRaisesRegex(ValueError, "Azure HTTPS"):
            module.azure_config("opus", config)

    def test_official_claude_is_default_and_does_not_require_azure_endpoint(self):
        args = module.parse_args([])
        self.assertEqual(args.opus_provider, "anthropic")
        config, identity = module.anthropic_config(args.opus_config)
        self.assertEqual(config["model"], "anthropic/claude-opus-5")
        self.assertEqual(identity["api_base"], "https://api.anthropic.com")
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "offline-claude"}):
            self.assertEqual(module.credential(config, "ANTHROPIC_API_KEY"), "offline-claude")
        azure = module.parse_args(["--opus-provider", "azure"])
        self.assertEqual(azure.opus_config.name, "orchestrator_config_opus_azure.json")

    def test_default_gpt_uses_new_project_endpoint_without_key_vault(self):
        args = module.parse_args([])
        config, identity = module.azure_config("gpt_5_6_sol", args.gpt_config)
        self.assertEqual(config["model"], "openai/responses/gpt-5.6-sol")
        self.assertNotIn("azure_key_vault", config)
        self.assertEqual(identity["api_base"],
            "https://echoziyiyang-0462-resource.services.ai.azure.com/api/projects/echoziyiyang-0462/openai/v1/")
        with patch.dict(os.environ, {"AZURE_API_KEY": "offline-new-resource"}):
            self.assertEqual(module.credential(config, "AZURE_API_KEY"), "offline-new-resource")
        opus = module.anthropic_config(args.opus_config)[0]
        runtime = module.prepare_runtime(self.root, {"gpt_5_6_sol": config, "opus": opus})
        judge = module.core.read_json(runtime / "grading_settings.json")
        self.assertEqual(judge["llm_judge_model"], config["model"])
        self.assertEqual(judge["llm_judge_extra_args"]["api_base"], identity["api_base"])

    def test_new_project_endpoint_sdk_path_and_responses_bridge(self):
        try:
            import httpx
            from openai import OpenAI
            from litellm.main import responses_api_bridge_check
        except ImportError:
            self.skipTest("Requires runtime OpenAI/LiteLLM dependencies")
        config, identity = module.azure_config("gpt_5_6_sol", module.parse_args([]).gpt_config)
        info, model = responses_api_bridge_check(
            model=config["model"].removeprefix("openai/"), custom_llm_provider="openai")
        self.assertEqual(info["mode"], "responses")
        self.assertEqual(model, "gpt-5.6-sol")
        seen = []
        def respond(request):
            seen.append(request)
            return httpx.Response(200, json={"id": "resp_offline", "object": "response",
                "created_at": 0, "status": "completed", "model": model,
                "output": [{"id": "msg_offline", "type": "message", "status": "completed",
                    "role": "assistant", "content": [{"type": "output_text", "text": "OK", "annotations": []}]}]})
        with httpx.Client(transport=httpx.MockTransport(respond)) as http_client:
            client = OpenAI(api_key="offline-placeholder", base_url=identity["api_base"], http_client=http_client)
            self.assertEqual(client.responses.create(model=model, input="Reply OK").output_text, "OK")
        self.assertEqual(str(seen[0].url), identity["api_base"] + "responses")
        self.assertEqual(json.loads(seen[0].content)["model"], "gpt-5.6-sol")

    def test_launcher_isolated_paths_limits_and_secrets(self):
        captured = {}
        candidate = self.candidates[0]
        self.args.base_port = 19280
        self.args.runtime_cidr = "172.30.0.0/16"
        self.args.model_max_turns = 80
        self.args.environment_image = "env"
        self.args.proxy_image = "proxy"
        class Process:
            def __init__(inner, command, **kwargs):
                captured.update(command=command, **kwargs)
                run_id = command[command.index("--run-id") + 1]
                directory = self.root / "runs" / run_id
                module.core.write_json_atomic(directory / "tasks" / candidate.task_id / "trajectory.json",
                                              {"messages": [], "status": "completed"})
                module.core.write_json_atomic(directory / "tasks" / candidate.task_id / "grades.json",
                                              {"grading_run_status": "completed"})
                module.core.write_json_atomic(directory / "score_summary.json", {"tasks": [
                    {"task_id": candidate.task_id, "final_score": candidate.gemini_score}]})
            def wait(inner):
                return 0
        with patch.dict(os.environ, {"ATTACK_CONFIG_FILE": "bad", "HF_MAX_STEPS": "999"}), \
             patch.object(module.subprocess, "Popen", Process):
            result = module.launch_model("opus", candidate, self.args, self.root / "runtime",
                                         {"gpt_5_6_sol": "offline-gpt", "opus": "offline-opus"})
        self.assertEqual(result["score"], candidate.gemini_score)
        environment = captured["env"]
        self.assertEqual(environment["HF_MAX_STEPS"], "81")
        self.assertEqual(environment["ANTHROPIC_API_KEY"], "offline-opus")
        self.assertNotIn("AZURE_AI_API_KEY", environment)
        self.assertEqual(environment["AZURE_API_KEY"], "offline-gpt")
        self.assertEqual(environment["OPENAI_API_KEY"], "offline-gpt")
        self.assertNotIn("ATTACK_CONFIG_FILE", environment)
        self.assertIn(str(self.root / "runs"), captured["command"])


if __name__ == "__main__":
    unittest.main()

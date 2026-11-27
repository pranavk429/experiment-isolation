"""Offline contract tests for the experiment-isolation Agent Skill.

Run from the repo root:
    PYTHONPATH=skills/experiment-isolation/scripts python3 -m unittest discover -s tests/skill -v
"""

import json
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SKILL_DIR = ROOT / "skills" / "experiment-isolation"
SKILL_MD = SKILL_DIR / "SKILL.md"
REFERENCES = ("api.md", "safety.md", "troubleshooting.md")
TRIGGERS = (
    "run another experiment",
    "overlapping experiments",
    "mutual exclusion",
    "experiment collision",
    "audience overlap",
    "isolate experiments",
)
NAME_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
WORKFLOW_SUBCOMMANDS = (
    ("audit", ("--samples", "--threshold", "--out audit.json")),
    ("plan", ("--audit audit.json", "--out plan.json")),
    ("apply", ("--plan plan.json", "--approve", "--out apply.json")),
    ("verify", ("--plan plan.json", "--samples", "--out verify.json")),
    (
        "receipt",
        ("--audit audit.json", "--plan plan.json", "--apply apply.json", "--verify verify.json", "--out receipt.json"),
    ),
    ("rollback", ("--apply apply.json", "--out rollback.json")),
)


def parse_frontmatter(text):
    """Parse the small YAML subset used by SKILL.md and return (data, body)."""
    if not text.startswith("---\n"):
        raise AssertionError("SKILL.md must start with a YAML frontmatter delimiter")
    end = text.find("\n---\n", 4)
    if end == -1:
        raise AssertionError("SKILL.md frontmatter is not closed")
    raw = text[4:end]
    data = {}
    for line in raw.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if not re.match(r"^[A-Za-z0-9_-]+:\s*", line):
            raise AssertionError(f"unsupported frontmatter line: {line!r}")
        key, value = line.split(":", 1)
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            value = value[1:-1]
        data[key.strip()] = value
    return data, text[end + 5 :]


def body_section(body, start, end):
    """Return the text between two headings, failing clearly if absent."""
    left = body.find(start)
    if left == -1:
        raise AssertionError(f"missing section: {start}")
    right = body.find(end, left)
    if right == -1:
        raise AssertionError(f"missing section: {end}")
    return body[left:right]


class SkillContentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = SKILL_MD.read_text(encoding="utf-8")
        cls.frontmatter, cls.body = parse_frontmatter(cls.text)
        cls.audit_section = body_section(cls.body, "### 1. Audit", "### 2. Plan")
        cls.verify_section = body_section(cls.body, "### 4. Verify", "### 5. Receipt")

    def test_frontmatter_required_fields(self):
        for field in ("name", "description"):
            self.assertIn(field, self.frontmatter)
            self.assertTrue(self.frontmatter[field])

    def test_frontmatter_uses_only_supported_keys(self):
        allowed = {"allowed-tools", "description", "license", "metadata", "name"}
        self.assertTrue(set(self.frontmatter).issubset(allowed), set(self.frontmatter))
        self.assertNotIn("compatibility", self.frontmatter)
        self.assertIn(
            "https://github.com/pranavk429/experiment-isolation",
            self.frontmatter["metadata"],
        )

    def test_name_matches_parent_directory(self):
        name = self.frontmatter["name"]
        self.assertEqual(name, "experiment-isolation")
        self.assertEqual(name, SKILL_DIR.name)
        self.assertTrue(NAME_RE.match(name), name)
        self.assertLessEqual(len(name), 64)

    def test_description_length_and_trigger_phrases(self):
        description = self.frontmatter["description"]
        self.assertLessEqual(len(description), 1024)
        self.assertGreater(len(description), 100)
        lowered = description.lower()
        for phrase in TRIGGERS:
            self.assertIn(phrase, lowered)

    def test_body_line_budget(self):
        lines = self.body.splitlines()
        self.assertGreater(len(lines), 30)
        self.assertLess(len(lines), 500)

    def test_body_token_estimate(self):
        estimate = math.ceil(len(self.body) / 4)
        self.assertGreaterEqual(estimate, 400)
        self.assertLessEqual(estimate, 1700)

    def test_references_exist_and_are_linked(self):
        for name in REFERENCES:
            path = SKILL_DIR / "references" / name
            self.assertTrue(path.is_file(), path)
            self.assertIn(f"references/{name}", self.body)
            self.assertGreater(len(path.read_text(encoding="utf-8").splitlines()), 10)

    def test_workflow_invokes_all_engine_subcommands(self):
        for subcommand, required_flags in WORKFLOW_SUBCOMMANDS:
            pattern = rf"(?:python3 -m engine\.cli|scripts/run\.sh)\s+{subcommand}\b([^\n]*)"
            matches = re.findall(pattern, self.body)
            self.assertTrue(matches, f"missing command invocation for {subcommand}")
            combined = " ".join(matches)
            for flag in required_flags:
                self.assertIn(flag, combined)

    def test_audit_collision_exit_10_continues_to_plan(self):
        lowered = self.audit_section.lower()
        self.assertIn("exit 10", lowered)
        self.assertIn("collision", lowered)
        self.assertRegex(lowered, r"continue to `?plan`?")

    def test_audit_clear_or_none_stops(self):
        lowered = self.audit_section.lower()
        self.assertIn("clear", lowered)
        self.assertIn("none", lowered)
        self.assertIn("stop", lowered)

    def test_isolated_is_only_a_verify_verdict(self):
        self.assertNotIn("isolated", self.audit_section.lower())
        self.assertIn("isolated", self.verify_section.lower())
        self.assertIn("verify verdict", self.body.lower())
        self.assertIn("never an audit verdict", self.body.lower())

    def test_verify_documents_paired_cohort_and_sample_prefix(self):
        self.assertIn("iso_0001..iso_0500", self.verify_section)
        self.assertIn("--sample-prefix", self.verify_section)

    def test_rollback_uses_engine_command(self):
        pattern = r"(?:python3 -m engine\.cli|scripts/run\.sh)\s+rollback\s+--apply apply\.json\s+--out rollback\.json"
        self.assertRegex(self.body, pattern)
        safety = (SKILL_DIR / "references" / "safety.md").read_text(encoding="utf-8")
        self.assertRegex(safety, pattern)
        self.assertIn("requires_recreate", (self.body + safety).lower())

    def test_no_flagsmith_api_rollback_recipe(self):
        for path in SKILL_DIR.rglob("*.md"):
            for line in path.read_text(encoding="utf-8").splitlines():
                lowered = line.lower()
                if "flagsmith api" in lowered and any(
                    marker in lowered for marker in ("--input", "-x ", "rollout/")
                ):
                    self.fail(f"hand-written rollback recipe in {path}: {line}")

    def test_plan_is_read_only_not_offline(self):
        lowered = self.body.lower()
        self.assertIn("not offline", lowered)
        self.assertIn("read-only", lowered)
        safety = (SKILL_DIR / "references" / "safety.md").read_text(encoding="utf-8")
        self.assertIn("not offline", safety.lower())

    def test_pause_is_not_an_isolation_step(self):
        combined = self.body + (SKILL_DIR / "references" / "api.md").read_text(encoding="utf-8")
        lowered = combined.lower()
        self.assertIn("pause is not an isolation step", lowered)
        self.assertNotIn("pause/complete", lowered)

    def test_receipt_includes_apply_and_token_claim_is_honest(self):
        pattern = (
            r"(?:python3 -m engine\.cli|scripts/run\.sh)\s+receipt\s+--audit audit\.json\s+"
            r"--plan plan\.json\s+--apply apply\.json\s+--verify verify\.json\s+--out receipt\.json"
        )
        self.assertRegex(self.body, pattern)
        lowered = self.body.lower()
        for token in ("audit", "plan", "apply", "verify", "token counts"):
            self.assertIn(token, lowered)
        self.assertRegex(lowered, r"roughly 100-125 tokens")
        self.assertIn("do not claim under 100", lowered)

    def test_setup_is_portable_and_documents_requirements(self):
        for token in (
            "FLAGSMITH_API_URL",
            "FLAGSMITH_API_KEY_<host>_<port>",
            "FLAGSMITH_API_KEY",
            "FLAGSMITH_PROJECT",
            "FLAGSMITH_ENVIRONMENT",
            "FLAGSMITH_ENVIRONMENT_KEY",
            "FLAGSMITH_ENV_FILE",
            "lab/.env",
        ):
            self.assertIn(token, self.body)

    def test_pause_is_not_a_recovery_path(self):
        combined = (
            self.body
            + (SKILL_DIR / "references" / "safety.md").read_text(encoding="utf-8")
            + (SKILL_DIR / "references" / "troubleshooting.md").read_text(encoding="utf-8")
        )
        lowered = combined.lower()
        self.assertIn(
            "the only paths are pre-launch isolation or complete/delete + recreate",
            lowered,
        )
        self.assertRegex(lowered, r"ignore (?:any )?pause-to-isolate")
        self.assertNotIn("pause or recreate", lowered)

    def test_approval_token_is_not_a_secret(self):
        lowered = self.body.lower()
        self.assertRegex(lowered, r"never print (?:api keys or environment keys|api/env keys)")
        self.assertIn("approval token", lowered)
        self.assertIn("confirmation string", lowered)
        self.assertIn("safe to display", lowered)
        safety = (SKILL_DIR / "references" / "safety.md").read_text(encoding="utf-8")
        self.assertIn("safe to display", safety.lower())

    def test_references_have_no_running_filter_or_property_underscore(self):
        api = (SKILL_DIR / "references" / "api.md").read_text(encoding="utf-8")
        self.assertNotIn("status=running", api)
        self.assertNotIn("property_", api)
        self.assertIn("For N planned experiments", api)

    def test_old_skill_path_is_gone_and_new_paths_are_used(self):
        self.assertFalse((ROOT / "skill").exists())
        self.assertIn("scripts/", self.body)
        self.assertNotIn("skill/scripts", self.body)

    def test_safety_terms_are_explicit(self):
        lowered = self.body.lower()
        for phrase in (
            "read-only by default",
            "never modify running experiments",
            "approval token",
            "rollback",
            "synthetic",
        ):
            self.assertIn(phrase, lowered)

    def test_no_engine_logic_in_skill_text(self):
        for marker in ("def audit", "def plan", "import urllib", "import requests", "jaccard ="):
            self.assertNotIn(marker, self.body)

    def test_no_raw_payload_dump_instruction(self):
        lowered = self.body.lower()
        self.assertIn("never dump", lowered)
        self.assertNotIn("print the full json", lowered)


class ScriptTests(unittest.TestCase):
    def test_scripts_are_executable_with_shebangs(self):
        expected = {
            "run.sh": "#!/usr/bin/env bash",
            "check_env.sh": "#!/usr/bin/env bash",
            "token_count.py": "#!/usr/bin/env python3",
        }
        for name, shebang in expected.items():
            path = SKILL_DIR / "scripts" / name
            self.assertTrue(path.is_file(), path)
            self.assertTrue(os.access(path, os.X_OK), f"{path} is not executable")
            self.assertEqual(path.read_text(encoding="utf-8").splitlines()[0], shebang)

    def test_shell_scripts_parse(self):
        for name in ("run.sh", "check_env.sh"):
            result = subprocess.run(
                ["bash", "-n", str(SKILL_DIR / "scripts" / name)],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_wrapper_delegates_without_logic(self):
        text = (SKILL_DIR / "scripts" / "run.sh").read_text(encoding="utf-8")
        self.assertIn('exec python3 -m engine.cli "$@"', text)
        for forbidden in ("curl", "urllib", "requests", "jaccard", "sha256", "PERCENTAGE_SPLIT"):
            self.assertNotIn(forbidden, text)

    @staticmethod
    def _fake_engine(repo):
        engine = repo / "engine"
        engine.mkdir(parents=True)
        (engine / "__init__.py").write_text("", encoding="utf-8")
        (engine / "cli.py").write_text(
            "import sys\nprint('|'.join(sys.argv[1:]))\n", encoding="utf-8"
        )

    def test_wrapper_resolves_explicit_root_and_preserves_spaces(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "fake repo with spaces"
            self._fake_engine(repo)
            env = dict(os.environ)
            env["EXPERIMENT_ISOLATION_ROOT"] = str(repo)
            result = subprocess.run(
                [
                    str(SKILL_DIR / "scripts" / "run.sh"),
                    "audit",
                    "--env",
                    "a b",
                    "--out",
                    "c d.json",
                ],
                capture_output=True,
                text=True,
                env=env,
                cwd=tmp,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout.strip(), "audit|--env|a b|--out|c d.json")

    def test_wrapper_walks_up_from_installed_copy(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo with spaces"
            self._fake_engine(repo)
            installed = repo / "skills" / "experiment-isolation"
            shutil.copytree(SKILL_DIR, installed)
            shutil.rmtree(installed / "scripts" / "engine")
            env = dict(os.environ)
            env.pop("EXPERIMENT_ISOLATION_ROOT", None)
            result = subprocess.run(
                [str(installed / "scripts" / "run.sh"), "plan", "--audit", "a b.json"],
                capture_output=True,
                text=True,
                env=env,
                cwd=tmp,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout.strip(), "plan|--audit|a b.json")

    def test_wrapper_standalone_portability_without_env_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            temp_root = Path(tmp)
            temp_dest = temp_root / ".claude" / "skills" / "experiment-isolation"
            shutil.copytree(SKILL_DIR, temp_dest)

            caller_cwd = temp_root / "user-project"
            caller_cwd.mkdir()

            env = dict(os.environ)
            env.pop("EXPERIMENT_ISOLATION_ROOT", None)
            env.pop("PYTHONPATH", None)

            help_res = subprocess.run(
                ["bash", str(temp_dest / "scripts" / "run.sh"), "--help"],
                cwd=str(caller_cwd),
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(help_res.returncode, 0, help_res.stderr)

            (caller_cwd / "audit.json").write_text(
                json.dumps({"experiments": []}), encoding="utf-8"
            )
            plan_res = subprocess.run(
                [
                    "bash",
                    str(temp_dest / "scripts" / "run.sh"),
                    "plan",
                    "--audit",
                    "audit.json",
                    "--out",
                    "plan.json",
                ],
                cwd=str(caller_cwd),
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(plan_res.returncode, 0, plan_res.stderr)
            self.assertTrue((caller_cwd / "plan.json").is_file())
            self.assertFalse((temp_dest / "plan.json").exists())
            self.assertFalse((temp_dest / "scripts" / "plan.json").exists())

    def test_wrapper_fails_on_invalid_explicit_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            empty_root = Path(tmp) / "empty"
            empty_root.mkdir()
            env = dict(os.environ)
            env["EXPERIMENT_ISOLATION_ROOT"] = str(empty_root)
            result = subprocess.run(
                ["bash", str(SKILL_DIR / "scripts" / "run.sh"), "--help"],
                capture_output=True,
                text=True,
                env=env,
                check=False,
            )
            self.assertEqual(result.returncode, 20)
            self.assertIn("engine package not found", result.stderr)

    def _run_token_count(self, payload, encoder_source):
        tmp_dir = tempfile.mkdtemp()
        try:
            path = Path(tmp_dir) / "payload.json"
            path.write_text(payload, encoding="utf-8")
            stub = Path(tmp_dir) / "stub"
            stub.mkdir()
            (stub / "tiktoken.py").write_text(encoder_source, encoding="utf-8")
            env = dict(os.environ)
            env["PYTHONPATH"] = str(stub)
            result = subprocess.run(
                [sys.executable, str(SKILL_DIR / "scripts" / "token_count.py"), str(path)],
                capture_output=True,
                text=True,
                env=env,
                check=False,
            )
            return result, payload
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    def test_token_count_uses_installed_tokenizer(self):
        source = (
            "class _Encoding:\n"
            "    def encode(self, text):\n"
            "        return list(range(7))\n"
            "def get_encoding(name):\n"
            "    return _Encoding()\n"
        )
        result, _ = self._run_token_count('{"product":"experiment-isolation"}', source)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "7\n")

    def test_token_count_falls_back_to_chars_over_four(self):
        result, payload = self._run_token_count(
            '{"product":"experiment-isolation","pass":true}',
            "raise ImportError('offline test')\n",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, f"{math.ceil(len(payload) / 4)}\n")

    def test_token_count_rejects_invalid_input(self):
        with tempfile.TemporaryDirectory() as tmp:
            bad = Path(tmp) / "bad.json"
            bad.write_text("{not json", encoding="utf-8")
            result = subprocess.run(
                [sys.executable, str(SKILL_DIR / "scripts" / "token_count.py"), str(bad)],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(result.stdout, "")

    def test_token_count_source_has_no_api_logic(self):
        text = (SKILL_DIR / "scripts" / "token_count.py").read_text(encoding="utf-8")
        for forbidden in ("flagsmith", "urllib", "requests", "jaccard", "sha256"):
            self.assertNotIn(forbidden, text.lower())

    @staticmethod
    def _run_check_env(env_text):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / "fake home"
            (home / "local-env").mkdir(parents=True)
            env_file = home / "local-env" / "flagsmith.env"
            env_file.write_text(env_text, encoding="utf-8")
            bin_dir = home / "fakebin"
            bin_dir.mkdir()
            curl = bin_dir / "curl"
            curl.write_text("#!/usr/bin/env bash\nprintf '200'\n", encoding="utf-8")
            curl.chmod(0o755)
            cli_dir = home / ".cache" / "fstools" / "node_modules" / ".bin"
            cli_dir.mkdir(parents=True)
            cli = cli_dir / "flagsmith"
            cli.write_text(
                '#!/usr/bin/env bash\nif [[ "${1:-}" == "--version" ]]; then echo "flagsmith 9.9.9"; fi\n',
                encoding="utf-8",
            )
            cli.chmod(0o755)
            env = dict(os.environ)
            env["HOME"] = str(home)
            env["PATH"] = f"{bin_dir}:/usr/bin:/bin"
            env["FLAGSMITH_ENV_FILE"] = str(env_file)
            return subprocess.run(
                ["bash", str(SKILL_DIR / "scripts" / "check_env.sh")],
                capture_output=True,
                text=True,
                env=env,
                check=False,
            )

    def test_check_env_never_prints_secret_values(self):
        sentinel = "SENTINEL_SECRET_VALUE_42"
        result = self._run_check_env(
            "export FLAGSMITH_API_URL=http://127.0.0.1:59999\n"
            f"export FLAGSMITH_API_KEY_127_0_0_1_59999={sentinel}\n"
            "export FLAGSMITH_PROJECT=1\n"
            f"export FLAGSMITH_ENVIRONMENT=env-{sentinel}\n"
            f"export DEV_ENV_KEY=env-{sentinel}\n"
            f"export ADMIN_TOKEN={sentinel}\n"
        )
        combined = result.stdout + result.stderr
        self.assertEqual(result.returncode, 0, combined)
        self.assertIn("ok:", result.stdout)
        self.assertNotIn(sentinel, combined)

    def test_check_env_does_not_assume_research_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / "no env here"
            home.mkdir()
            env = dict(os.environ)
            env["HOME"] = str(home)
            env["PATH"] = "/usr/bin:/bin"
            for name in (
                "FLAGSMITH_ENV_FILE",
                "FLAGSMITH_API_URL",
                "FLAGSMITH_API_KEY",
                "FLAGSMITH_PROJECT",
                "FLAGSMITH_ENVIRONMENT",
                "FLAGSMITH_ENVIRONMENT_KEY",
                "DEV_ENV_KEY",
            ):
                env.pop(name, None)
            result = subprocess.run(
                ["bash", str(SKILL_DIR / "scripts" / "check_env.sh")],
                capture_output=True,
                text=True,
                env=env,
                cwd=tmp,
                check=False,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("FLAGSMITH_ENV_FILE", result.stderr)
            self.assertNotIn("flagsmith-local", result.stderr)

    def test_check_env_sanitizes_hyphenated_hostname(self):
        sentinel = "SENTINEL_HYPHEN_99"
        result = self._run_check_env(
            "export FLAGSMITH_API_URL=http://flagsmith-dev.internal:8010\n"
            f"export FLAGSMITH_API_KEY_flagsmith_dev_internal_8010={sentinel}\n"
            "export FLAGSMITH_PROJECT=1\n"
            "export DEV_ENV_KEY=env-token\n"
        )
        combined = result.stdout + result.stderr
        self.assertEqual(result.returncode, 0, combined)
        self.assertIn("ok: Flagsmith API credential present", result.stdout)
        self.assertNotIn(sentinel, combined)

        missing = self._run_check_env(
            "export FLAGSMITH_API_URL=http://flagsmith-dev.internal:8010\n"
            "export FLAGSMITH_PROJECT=1\n"
            "export DEV_ENV_KEY=env-token\n"
        )
        self.assertNotEqual(missing.returncode, 0)
        self.assertIn("FLAGSMITH_API_KEY_flagsmith_dev_internal_8010", missing.stderr)


class PackagingTests(unittest.TestCase):
    def test_installable_by_copying_skill_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            destination = Path(tmp) / ".claude" / "skills" / "experiment-isolation"
            shutil.copytree(SKILL_DIR, destination)
            text = (destination / "SKILL.md").read_text(encoding="utf-8")
            data, _ = parse_frontmatter(text)
            self.assertEqual(data["name"], destination.name)
            self.assertTrue((destination / "scripts" / "run.sh").is_file())
            self.assertTrue((destination / "scripts" / "engine" / "cli.py").is_file())

    def test_no_absolute_developer_paths_or_secret_assignments(self):
        for path in SKILL_DIR.rglob("*"):
            if not path.is_file() or path.suffix not in (".md", ".sh", ".py"):
                continue
            text = path.read_text(encoding="utf-8")
            self.assertNotIn("/Users/", text, path)
            self.assertNotRegex(
                text,
                r"(?m)^(?:export\s+)?(?:FLAGSMITH_API_KEY|ADMIN_TOKEN)\s*=\s*[A-Za-z0-9]",
            )

    def test_no_flagsmith_local_assumptions_in_docs_or_shell_scripts(self):
        targets = [SKILL_MD]
        targets.extend((SKILL_DIR / "references").glob("*.md"))
        targets.extend((SKILL_DIR / "scripts").glob("*.sh"))
        for path in targets:
            text = path.read_text(encoding="utf-8")
            self.assertNotIn("/Users/", text, path)
            self.assertNotIn("flagsmith-local", text, path)


if __name__ == "__main__":
    unittest.main()

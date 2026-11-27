"""Offline contract tests for the experiment-isolation Agent Skill.

Run from the repo root:
    python3 -m unittest discover -s tests/skill -v
"""

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
CLI_COMMANDS = (
    'python3 -m engine.cli audit --env "$DEV_ENV_KEY" --samples 500 --threshold 0.05 --out audit.json',
    "python3 -m engine.cli plan --audit audit.json --out plan.json",
    'python3 -m engine.cli apply --plan plan.json --approve "<approval-token>" --out apply.json',
    "python3 -m engine.cli verify --plan plan.json --samples 500 --workers 2 --out verify.json",
    "python3 -m engine.cli receipt --audit audit.json --plan plan.json --apply apply.json --verify verify.json --out receipt.json",
    "python3 -m engine.cli rollback --apply apply.json --out rollback.json",
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
            raise AssertionError("unsupported frontmatter line: %r" % line)
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
        raise AssertionError("missing section: %s" % start)
    right = body.find(end, left)
    if right == -1:
        raise AssertionError("missing section: %s" % end)
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
        # Conservative stdlib estimate, with headroom for the verdict and
        # rollback corrections. Measured tokenizer counts are reported.
        estimate = math.ceil(len(self.body) / 4)
        self.assertGreaterEqual(estimate, 600)
        self.assertLessEqual(estimate, 1700)

    def test_references_exist_and_are_linked(self):
        for name in REFERENCES:
            path = SKILL_DIR / "references" / name
            self.assertTrue(path.is_file(), path)
            self.assertIn("references/%s" % name, self.body)
            self.assertGreater(len(path.read_text(encoding="utf-8").splitlines()), 10)

    def test_exact_engine_cli_commands(self):
        for command in CLI_COMMANDS:
            self.assertIn(command, self.body)

    def test_audit_collision_exit_10_continues_to_plan(self):
        lowered = self.audit_section.lower()
        self.assertIn("exit 10", lowered)
        self.assertIn("collision", lowered)
        self.assertIn("continue to plan", lowered)

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

    def test_rollback_uses_engine_command(self):
        command = "python3 -m engine.cli rollback --apply apply.json --out rollback.json"
        self.assertIn(command, self.body)
        safety = (SKILL_DIR / "references" / "safety.md").read_text(encoding="utf-8")
        self.assertIn(command, safety)
        self.assertIn("requires_recreate", (self.body + safety).lower())

    def test_no_flagsmith_api_rollback_recipe(self):
        for path in SKILL_DIR.rglob("*.md"):
            for line in path.read_text(encoding="utf-8").splitlines():
                lowered = line.lower()
                if "flagsmith api" in lowered and any(
                    marker in lowered for marker in ("--input", "-x ", "rollout/")
                ):
                    self.fail("hand-written rollback recipe in %s: %s" % (path, line))

    def test_plan_is_read_only_not_offline(self):
        lowered = self.body.lower()
        self.assertIn("not offline", lowered)
        self.assertIn("read-only", lowered)
        safety = (SKILL_DIR / "references" / "safety.md").read_text(encoding="utf-8")
        self.assertIn("not offline", safety.lower())

    def test_pause_is_not_an_isolation_step(self):
        combined = self.body + (SKILL_DIR / "references" / "api.md").read_text(
            encoding="utf-8"
        )
        lowered = combined.lower()
        self.assertIn("pause is not an isolation step", lowered)
        self.assertNotIn("pause/complete", lowered)

    def test_receipt_includes_apply_and_token_claim_is_honest(self):
        command = (
            "python3 -m engine.cli receipt --audit audit.json --plan plan.json "
            "--apply apply.json --verify verify.json --out receipt.json"
        )
        self.assertIn(command, self.body)
        lowered = self.body.lower()
        self.assertIn("audit, plan, apply, and verify token counts", lowered)
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
            "source ~/flagsmith-local/flagsmith.env",
            "source lab/.env",
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
        self.assertIn("if a note suggests pausing, ignore it", lowered)
        self.assertNotIn("pause or recreate", lowered)

    def test_approval_token_is_not_a_secret(self):
        lowered = self.body.lower()
        self.assertIn("never print api keys or environment keys", lowered)
        self.assertIn("approval token is a short confirmation string", lowered)
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
        self.assertIn("skills/experiment-isolation/scripts", self.body)
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
            self.assertTrue(os.access(path, os.X_OK), "%s is not executable" % path)
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

    def test_wrapper_fails_safely_without_engine(self):
        with tempfile.TemporaryDirectory() as tmp:
            installed = Path(tmp) / "skills" / "experiment-isolation"
            shutil.copytree(SKILL_DIR, installed)
            env = dict(os.environ)
            env.pop("EXPERIMENT_ISOLATION_ROOT", None)
            result = subprocess.run(
                [str(installed / "scripts" / "run.sh"), "audit"],
                capture_output=True,
                text=True,
                env=env,
                cwd=tmp,
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
        self.assertEqual(result.stdout, "%d\n" % math.ceil(len(payload) / 4))

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

    def test_check_env_never_prints_secret_values(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / "fake home"
            (home / "flagsmith-local").mkdir(parents=True)
            sentinel = "SENTINEL_SECRET_VALUE_42"
            env_file = home / "flagsmith-local" / "flagsmith.env"
            env_file.write_text(
                "export FLAGSMITH_API_URL=http://127.0.0.1:59999\n"
                "export FLAGSMITH_API_KEY_127_0_0_1_59999=%s\n"
                "export FLAGSMITH_PROJECT=1\n"
                "export FLAGSMITH_ENVIRONMENT=env-%s\n"
                "export DEV_ENV_KEY=env-%s\n"
                "export ADMIN_TOKEN=%s\n" % (sentinel, sentinel, sentinel, sentinel),
                encoding="utf-8",
            )
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
            env["PATH"] = "%s:/usr/bin:/bin" % bin_dir
            env["FLAGSMITH_ENV_FILE"] = str(env_file)
            result = subprocess.run(
                ["bash", str(SKILL_DIR / "scripts" / "check_env.sh")],
                capture_output=True,
                text=True,
                env=env,
                check=False,
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
                check=False,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("FLAGSMITH_ENV_FILE", result.stderr)
            self.assertNotIn("flagsmith-local/flagsmith.env", result.stderr)


class PackagingTests(unittest.TestCase):
    def test_installable_by_copying_skill_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            destination = Path(tmp) / ".claude" / "skills" / "experiment-isolation"
            shutil.copytree(SKILL_DIR, destination)
            text = (destination / "SKILL.md").read_text(encoding="utf-8")
            data, _ = parse_frontmatter(text)
            self.assertEqual(data["name"], destination.name)
            self.assertTrue((destination / "scripts" / "run.sh").is_file())

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


if __name__ == "__main__":
    unittest.main()

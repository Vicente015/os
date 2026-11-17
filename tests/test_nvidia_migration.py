import hashlib
import os
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STABLE_RECIPE_SHA256 = "321352723b9387c80482aed3efa71a723420af19ec82653938e420635fa60df3"
MIGRATION_RECIPE = ROOT / "recipes" / "nvidia-migration.yml"
MIGRATION_WORKFLOW = ROOT / ".github" / "workflows" / "build-nvidia-migration.yml"
STABLE_WORKFLOW = ROOT / ".github" / "workflows" / "build.yml"
SERVICE_DROPIN = (
    ROOT
    / "files/nvidia-migration/usr/lib/systemd/system"
    / "bootc-fetch-apply-updates.service.d/10-stage-only.conf"
)
TIMER_DROPIN = (
    ROOT
    / "files/nvidia-migration/usr/lib/systemd/system"
    / "bootc-fetch-apply-updates.timer.d/10-daily.conf"
)
JUSTFILE = ROOT / "files/justfiles/50-update-compat.just"
HOST_UNIT_DIR = Path("/usr/lib/systemd/system")


def read(path):
    return path.read_text(encoding="utf-8")


class StableRecipeTest(unittest.TestCase):
    def test_stable_recipe_is_unchanged_baseline(self):
        digest = hashlib.sha256((ROOT / "recipes/nvidia.yml").read_bytes()).hexdigest()
        self.assertEqual(STABLE_RECIPE_SHA256, digest)

    def test_stable_recipe_keeps_original_base(self):
        text = read(ROOT / "recipes/nvidia.yml")
        self.assertIn("base-image: ghcr.io/ublue-os/silverblue-nvidia\n", text)
        self.assertNotIn("alt-tags", text)

    def test_stable_workflow_does_not_build_nvidia(self):
        text = read(STABLE_WORKFLOW)
        self.assertIn("- main.yml", text)
        self.assertNotIn("nvidia.yml", text)


class MigrationRecipeTest(unittest.TestCase):
    def setUp(self):
        self.text = read(MIGRATION_RECIPE)

    def test_name_and_input_tag(self):
        self.assertRegex(self.text, r"(?m)^name: os-nvidia$")
        self.assertRegex(self.text, r"(?m)^image-version: latest$")

    def test_open_base(self):
        self.assertRegex(
            self.text,
            r"(?m)^base-image: ghcr\.io/blue-build/base-images/fedora-silverblue-nvidia-open$",
        )

    def test_only_migration_alt_tag(self):
        self.assertRegex(self.text, r"(?m)^alt-tags: \[migration\]$")
        self.assertEqual(1, len(re.findall(r"(?m)^alt-tags:", self.text)))
        self.assertNotRegex(self.text, r"alt-tags:.*latest")

    def test_module_order(self):
        order = [
            "negativo17.org/repos/fedora-multimedia.repo",
            "from-file: base.yml",
            "source: nvidia-migration",
            "type: signing",
        ]
        positions = [self.text.find(item) for item in order]
        self.assertTrue(all(p >= 0 for p in positions), positions)
        self.assertEqual(sorted(positions), positions)

    def test_repo_is_https_only(self):
        self.assertNotIn("http://", self.text)
        self.assertNotIn("nogpgcheck", self.text.lower())

    def test_justfiles_module_between_base_and_signing(self):
        self.assertRegex(self.text, r"type: justfiles\n\s+include:\n\s+- 50-update-compat\.just")
        self.assertLess(self.text.find("source: nvidia-migration"), self.text.find("type: justfiles"))
        self.assertLess(self.text.find("type: justfiles"), self.text.find("type: signing"))

    def test_helper_check_after_justfiles_fails_closed(self):
        tail = self.text[self.text.find("type: justfiles"):self.text.find("type: signing")]
        self.assertIn("type: script", tail)
        self.assertIn("test -x /usr/bin/blujust", tail)
        self.assertIn("[ ! -e /usr/bin/ujust ] && [ ! -L /usr/bin/ujust ]", tail)
        self.assertIn("ln -s blujust /usr/bin/ujust", tail)
        self.assertIn("test -x /usr/bin/ujust", tail)
        self.assertIn("--show update-all", tail)
        self.assertNotIn("ln -sf", tail)
        self.assertNotIn("|| true", tail)

    def test_base_enroll_recipe_checked_not_redefined(self):
        tail = self.text[self.text.find("type: justfiles"):self.text.find("type: signing")]
        self.assertRegex(tail, r"(?m)^\s+(/usr/bin/)?ujust --show enroll-secure-boot-key$")
        self.assertNotIn("mokutil", self.text)
        self.assertNotIn("enroll-secure-boot-key", read(JUSTFILE))
        self.assertNotIn("mokutil", read(JUSTFILE))


def stub(path, name, log):
    path.joinpath(name).write_text(f'#!/bin/sh\necho "{name} $*" >> "{log}"\n')
    path.joinpath(name).chmod(0o755)


class UpdateAllJustfileTest(unittest.TestCase):
    def test_justfile_defines_only_update_all_with_ordered_commands(self):
        text = read(JUSTFILE)
        self.assertEqual(["update-all"], re.findall(r"(?m)^([a-z][\w-]*)\b.*:\s*$", text))
        self.assertLess(text.find("pkexec bootc upgrade"), text.find("flatpak update -y"))
        self.assertLess(text.find("flatpak update -y"), text.find("distrobox upgrade --all"))
        for banned in ("--apply", "reboot", "brew", "sudo", "alias"):
            self.assertNotIn(banned, text)

    @unittest.skipUnless(shutil.which("just"), "just not installed; image build runs --show update-all")
    def test_update_all_runs_commands_in_order_with_stubs(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            log = tmp / "log"
            for name in ("pkexec", "flatpak", "distrobox"):
                stub(tmp, name, log)
            tmp.joinpath("bootc").write_text(f'#!/bin/sh\necho "bootc $*" >> "{log}"\n')
            tmp.joinpath("bootc").chmod(0o755)
            tmp.joinpath("pkexec").write_text(f'#!/bin/sh\necho "pkexec $*" >> "{log}"\nexec "$@"\n')
            result = subprocess.run(
                ["just", "--justfile", str(JUSTFILE), "update-all"],
                capture_output=True, text=True,
                env={"PATH": f"{tmp}:/usr/bin:/bin", "HOME": str(tmp)},
            )
            self.assertEqual(0, result.returncode, result.stderr)
            self.assertEqual(
                ["pkexec bootc upgrade", "bootc upgrade", "flatpak update -y", "distrobox upgrade --all"],
                read(log).splitlines(),
            )

    @unittest.skipUnless(shutil.which("just"), "just not installed; image build runs --show update-all")
    def test_update_all_has_no_alias_conflict_with_builtin_update(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            base = tmp / "00-default.just"
            base.write_text("alias upgrade := update\n"
                            "update:\n    @echo builtin\n")
            main = tmp / "justfile"
            main.write_text(f'set allow-duplicate-recipes := true\nimport "{base}"\nimport "{JUSTFILE}"\n')
            for name, expected in (("update", "builtin"), ("upgrade", "builtin")):
                out = subprocess.run(["just", "--justfile", str(main), name],
                                     capture_output=True, text=True)
                self.assertEqual(expected, out.stdout.strip(), out.stderr)
            shown = subprocess.run(["just", "--justfile", str(main), "--show", "update-all"],
                                   capture_output=True, text=True)
            self.assertEqual(0, shown.returncode, shown.stderr)


class MigrationWorkflowTest(unittest.TestCase):
    def setUp(self):
        self.text = read(MIGRATION_WORKFLOW)

    def test_triggers_are_main_push_and_dispatch_only(self):
        self.assertIn("workflow_dispatch", self.text)
        self.assertNotIn("pull_request", self.text)
        self.assertNotIn("schedule", self.text)
        self.assertRegex(self.text, r"branches:\s*\n\s*- main")
        self.assertIn("recipes/nvidia-migration.yml", self.text)

    def test_main_branch_guard(self):
        self.assertIn("github.ref == 'refs/heads/main'", self.text)

    def test_cli_and_action_pins(self):
        self.assertIn("blue-build/github-action@v1.14.0", self.text)
        self.assertIn("cli_version: v0.9.42", self.text)
        self.assertIn("recipe: nvidia-migration.yml", self.text)
        self.assertIn("actions/checkout@v4", self.text)

    def test_serialized_publishing(self):
        self.assertRegex(self.text, r"group: nvidia-migration")
        self.assertRegex(self.text, r"cancel-in-progress: false")

    def test_permissions_and_no_bypass(self):
        for perm in ("contents: read", "packages: write", "id-token: write"):
            self.assertIn(perm, self.text)
        self.assertNotIn("docker push", self.text)
        self.assertNotIn("--nogpgcheck", self.text)


class UpdateDropinTest(unittest.TestCase):
    def test_service_resets_and_stages_only(self):
        text = read(SERVICE_DROPIN)
        self.assertEqual(
            "[Service]\nExecStart=\nExecStart=/usr/bin/bootc upgrade --quiet\n", text
        )
        self.assertNotIn("--apply", text)

    def test_timer_resets_and_runs_daily(self):
        text = read(TIMER_DROPIN)
        self.assertEqual(
            "[Timer]\nOnBootSec=\nOnUnitInactiveSec=\nOnCalendar=\n"
            "OnCalendar=*-*-* 04:00:00\nRandomizedDelaySec=0\nPersistent=true\n",
            text,
        )

    @unittest.skipUnless(
        shutil.which("systemd-analyze")
        and (HOST_UNIT_DIR / "bootc-fetch-apply-updates.service").exists(),
        "systemd-analyze or the bootc unit is not available",
    )
    def test_systemd_accepts_dropins(self):
        with tempfile.TemporaryDirectory() as tmp:
            unit_dir = Path(tmp)
            for suffix, dropin in (("service", SERVICE_DROPIN), ("timer", TIMER_DROPIN)):
                name = f"bootc-fetch-apply-updates.{suffix}"
                shutil.copy(HOST_UNIT_DIR / name, unit_dir / name)
                d = unit_dir / f"{name}.d"
                d.mkdir()
                shutil.copy(dropin, d / dropin.name)
            result = subprocess.run(
                ["systemd-analyze", "verify", str(unit_dir / "bootc-fetch-apply-updates.timer")],
                capture_output=True,
                text=True,
                env={**os.environ, "SYSTEMD_UNIT_PATH": f"{unit_dir}:"},
            )
            self.assertNotIn("Invalid", result.stderr, result.stderr)
            self.assertNotIn("Unknown key", result.stderr, result.stderr)


if __name__ == "__main__":
    unittest.main()

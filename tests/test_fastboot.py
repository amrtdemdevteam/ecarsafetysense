"""Host tests for fastboot.sh (no Raspberry Pi needed; paths redirected with FB_* variables)."""
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASH = shutil.which("bash")

BASE_CFG = "dtparam=audio=on\nauto_initramfs=1\n\n[all]\ngpio=23=op,dh\n"


@unittest.skipIf(BASH is None or os.name == "nt", "needs bash on a POSIX host")
class FastbootScriptTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        (self.tmp / "boot").mkdir()
        self.cfg = self.tmp / "boot" / "config.txt"
        self.cfg.write_text(BASE_CFG)
        self.cmdline = self.tmp / "cmdline"
        self.cmdline.write_text("console=tty1 root=PARTUUID=0e67f252-02 rootfstype=ext4 rootwait\n")
        self.env = dict(os.environ,
                        FB_CFG=str(self.cfg),
                        FB_STATE=str(self.tmp / "state"),
                        FB_HELPER=str(self.tmp / "helper"),
                        FB_DROPIN=str(self.tmp / "dropin" / "10-buzzrelease.conf"),
                        FB_CMDLINE=str(self.cmdline),
                        FB_CRYPTTAB=str(self.tmp / "crypttab"),
                        FB_SYSTEMCTL="true",
                        FB_MODEL="Raspberry Pi 4 Model B Rev 1.5")

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def run_fb(self, action, **extra):
        env = dict(self.env, **extra)
        return subprocess.run([BASH, str(ROOT / "fastboot.sh"), action], env=env,
                              capture_output=True, text=True, check=True)

    def test_pi4_apply_is_idempotent_and_revert_restores(self):
        self.run_fb("apply")
        self.run_fb("apply")
        text = self.cfg.read_text()
        self.assertIn("auto_initramfs=0", text)
        self.assertEqual(text.count("initial_turbo=30"), 1)
        self.assertEqual(text.count("dtoverlay=gpio-led,gpio=23,label=ssbuzz"), 1)
        self.assertTrue((self.tmp / "helper").is_file())
        self.assertTrue((self.tmp / "dropin" / "10-buzzrelease.conf").is_file())
        self.run_fb("revert")
        self.assertEqual(self.cfg.read_text(), BASE_CFG)
        self.assertFalse((self.tmp / "helper").exists())

    def test_pi5_skips_gpio_led(self):
        self.run_fb("apply", FB_MODEL="Raspberry Pi 5 Model B Rev 1.1")
        text = self.cfg.read_text()
        self.assertIn("initial_turbo=30", text)
        self.assertNotIn("gpio-led", text)

    def test_keeps_initramfs_when_root_needs_it(self):
        self.cmdline.write_text("root=/dev/mapper/cryptroot rootwait\n")
        self.run_fb("apply")
        self.assertIn("auto_initramfs=1", self.cfg.read_text())

    def test_keeps_initramfs_with_crypttab(self):
        (self.tmp / "crypttab").write_text("cryptroot UUID=abc none luks\n")
        self.run_fb("apply")
        self.assertIn("auto_initramfs=1", self.cfg.read_text())

    def test_upgrades_old_trial_block(self):
        old = BASE_CFG.replace("auto_initramfs=1", "auto_initramfs=0") + (
            "# >>> safety_sense fastboot (fastboot_trial.sh)\n[all]\ninitial_turbo=30\n"
            "dtoverlay=gpio-led,gpio=23,label=ssbuzz\n# <<< safety_sense fastboot\n")
        self.cfg.write_text(old)
        self.run_fb("apply")
        text = self.cfg.read_text()
        self.assertEqual(text.count(">>> safety_sense fastboot"), 1)
        self.assertIn("(fastboot.sh)", text)
        self.assertEqual(text.count("initial_turbo=30"), 1)


if __name__ == "__main__":
    unittest.main()

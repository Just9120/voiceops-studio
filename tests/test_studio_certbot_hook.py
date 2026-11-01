"""Exercise the real hook logic without running host nginx or systemctl."""
import os
from pathlib import Path
import shlex
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
HOOK = ROOT / 'deploy/studio/certbot-deploy-hook.sh'
LINEAGE = '/etc/letsencrypt/live/studio.cloud-nodes.net'


@unittest.skipUnless(os.name == "posix", "Requires POSIX /bin/sh; covered by Linux CI")
class CertificateDeployHookTests(unittest.TestCase):
    def test_scoped_reload_and_failures(self):
        source = HOOK.read_text(encoding="utf-8")
        subprocess.run(["/bin/sh", "-n"], input=source, text=True, check=True)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            log = root / "calls"
            for name, code in (("nginx", "NGINX_RC"), ("systemctl", "RELOAD_RC")):
                stub = root / name
                stub.write_text(
                    '#!/bin/sh\nprintf "%s:%s\\n" "' + name
                    + '" "$*" >> "$CALL_LOG"\nexit "${' + code + ':-0}"\n',
                    encoding="utf-8",
                )
                stub.chmod(0o700)
            self.assertEqual(source.count("/usr/sbin/nginx"), 1)
            self.assertEqual(source.count("/usr/bin/systemctl"), 1)
            fixture = source.replace("/usr/sbin/nginx", shlex.quote(str(root / "nginx")))
            fixture = fixture.replace("/usr/bin/systemctl", shlex.quote(str(root / "systemctl")))
            cases = [
                (None, 0, 0, 0, []),
                ("", 0, 0, 0, []),
                ("/etc/letsencrypt/live/life.cloud-nodes.net", 0, 0, 0, []),
                ("/etc/letsencrypt/live/studio.librechat.online", 0, 0, 0, []),
                (LINEAGE + "-other", 0, 0, 0, []),
                (LINEAGE, 0, 0, 0, ["nginx:-t", "systemctl:reload nginx"]),
                (LINEAGE, 9, 0, 9, ["nginx:-t"]),
                (LINEAGE, 0, 7, 7, ["nginx:-t", "systemctl:reload nginx"]),
            ]
            for lineage, nginx_rc, reload_rc, expected_rc, calls in cases:
                with self.subTest(lineage=lineage, nginx_rc=nginx_rc, reload_rc=reload_rc):
                    log.unlink(missing_ok=True)
                    env = {"PATH": "/usr/bin:/bin", "CALL_LOG": str(log),
                           "NGINX_RC": str(nginx_rc), "RELOAD_RC": str(reload_rc)}
                    if lineage is not None:
                        env["RENEWED_LINEAGE"] = lineage
                    result = subprocess.run(["/bin/sh", "-s"], input=fixture, text=True,
                                            capture_output=True, env=env)
                    self.assertEqual(result.returncode, expected_rc, result.stderr)
                    self.assertEqual(log.read_text().splitlines() if log.exists() else [], calls)


if __name__ == "__main__":
    unittest.main()

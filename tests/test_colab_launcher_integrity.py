import ast
import hashlib
from io import BytesIO
import json
from pathlib import Path
from types import SimpleNamespace
import urllib.request

import pytest


@pytest.mark.parametrize("name", ["elevenlabs_api_colab", "elevenlabs_realtime_colab"])
def test_launcher_verifies_download_before_replacing_or_executing_runtime(tmp_path, name):
    notebook = json.loads((Path("notebooks") / f"{name}.ipynb").read_text(encoding="utf-8"))
    source = "\n".join("".join(cell["source"]) for cell in notebook["cells"] if cell["cell_type"] == "code")
    tree = ast.parse(source)
    ref = next(ast.literal_eval(node.value) for node in tree.body if isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id == "GITHUB_REF" for target in node.targets))
    assert len(ref) == 40 and all(character in "0123456789abcdef" for character in ref)
    definition = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "download_verified")
    calls = []
    def download(url, *, timeout):
        calls.append((url, timeout))
        return BytesIO(b"reviewed synthetic runtime")
    namespace = {"hashlib": hashlib, "urllib": SimpleNamespace(request=SimpleNamespace(urlopen=download))}
    exec(compile(ast.Module(body=[definition], type_ignores=[]), "launcher-verifier", "exec"), namespace)
    path = tmp_path / "runtime.py"
    path.write_bytes(b"previous reviewed version")
    with pytest.raises(RuntimeError, match="reviewed release"):
        namespace["download_verified"]("https://example.test/runtime", path, "0" * 64)
    assert path.read_bytes() == b"previous reviewed version"
    namespace["download_verified"]("https://example.test/runtime", path, hashlib.sha256(b"reviewed synthetic runtime").hexdigest())
    assert path.read_bytes() == b"reviewed synthetic runtime"
    assert all(timeout == 30 for _, timeout in calls)


@pytest.mark.parametrize("version,corrupt", [("3.12", False), ("3.13", False), ("3.13", True)])
def test_batch_launcher_wires_only_verified_lock_and_runtime(monkeypatch, capsys, version, corrupt):
    notebook = json.loads(Path("notebooks/elevenlabs_api_colab.ipynb").read_text(encoding="utf-8"))
    source = "\n".join("".join(cell["source"]) for cell in notebook["cells"] if cell["cell_type"] == "code")
    tree = ast.parse(source)
    lock = f"requirements-colab-linux-x64-py{version}.lock"
    artifacts = {
        "elevenlabs_api.py": b"assert VOICEOPS_STT_POST('synthetic', data='fields') == 'locked transport'\nprint('BATCH READY')\n",
        "scripts/check_colab_dependency_install.py": (
            f"def colab_lock_name(): return {lock!r}\n"
            "def install_locked_colab_python(lock, directory):\n"
            "    assert lock.read_bytes() == b'synthetic pinned lock'\n"
            "    return directory / 'synthetic-interpreter'\n"
        ).encode(),
        lock: b"synthetic pinned lock",
        "colab_stt_transport.py": (
            b"def post_with_interpreter(interpreter, url, **kwargs):\n"
            b"    assert interpreter.name == 'synthetic-interpreter'\n"
            b"    assert url == 'synthetic' and kwargs == {'data': 'fields'}\n"
            b"    return 'locked transport'\n"
        ),
    }
    manifest = next(
        node for node in tree.body if isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id == "ARTIFACT_SHA256" for target in node.targets)
    )
    manifest.value = ast.parse(repr({
        name: hashlib.sha256(payload).hexdigest() for name, payload in artifacts.items()
    }), mode="eval").body
    fetched = []

    def fetch(url, *, timeout):
        assert timeout == 30
        name = url.split("/", 6)[-1]
        fetched.append(name)
        return BytesIO(b"corrupt" if corrupt and name == lock else artifacts[name])

    monkeypatch.setattr(urllib.request, "urlopen", fetch)
    code = compile(ast.fix_missing_locations(tree), "batch-launcher", "exec")
    if corrupt:
        with pytest.raises(RuntimeError, match="reviewed release"):
            exec(code, {})
        assert "BATCH READY" not in capsys.readouterr().out
        assert fetched == list(artifacts)[:3]
    else:
        exec(code, {})
        assert "BATCH READY" in capsys.readouterr().out
        assert fetched == list(artifacts)

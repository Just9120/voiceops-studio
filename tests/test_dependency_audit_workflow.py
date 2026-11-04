import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "dependency-audit.yml"
STUDIO_CI_WORKFLOW = ROOT / ".github" / "workflows" / "studio-ci.yml"
STUDIO = ROOT / "apps" / "studio"
STUDIO_API = ROOT / "apps" / "studio-api"


def test_dependency_audit_is_scheduled_and_manual_not_an_ordinary_ci_gate():
    workflow = WORKFLOW.read_text(encoding="utf-8")
    triggers = workflow.split("permissions:", 1)[0]

    assert "schedule:" in triggers
    assert "workflow_dispatch:" in triggers
    assert "pull_request:" not in triggers
    assert "push:" not in triggers
    assert "permissions:\n  contents: read" in workflow
    assert "timeout-minutes:" in workflow
    assert "cancel-in-progress: true" in workflow
    assert workflow.count("persist-credentials: false") == 2


def test_dependency_audit_run_name_identifies_exact_ref_and_revision():
    workflow = WORKFLOW.read_text(encoding="utf-8")

    assert "run-name: Dependency audit · ${{ github.ref_name }} · ${{ github.sha }}" in workflow


def test_dependency_audit_covers_exact_node_and_installed_python_graphs():
    workflow = WORKFLOW.read_text(encoding="utf-8")

    assert "npm ci --ignore-scripts --no-audit" in workflow
    assert "npm audit --audit-level=low" in workflow
    assert "python -m pip install pip-audit==2.10.1" in workflow
    assert 'python -m pip install --target "$RUNNER_TEMP/studio-python-audit" -r requirements-dev.txt -c constraints-dev.txt' in workflow
    assert 'python -m pip_audit --strict --path "$RUNNER_TEMP/studio-python-audit"' in workflow


def test_dependency_audit_cannot_mask_or_mutate_dependency_findings():
    workflow = WORKFLOW.read_text(encoding="utf-8")

    assert workflow.count("npm ci --ignore-scripts --no-audit") == 1
    assert workflow.count("npm audit --audit-level=low") == 1
    assert workflow.count("python -m pip_audit --strict") == 1
    assert "continue-on-error:" not in workflow
    assert "npm audit fix" not in workflow
    assert "--force" not in workflow
    assert "--omit" not in workflow
    assert "--production" not in workflow
    assert "--ignore-vuln" not in workflow
    assert "--no-deps" not in workflow
    assert "|| true" not in workflow
    assert "; true" not in workflow


def test_dependency_audit_summaries_preserve_job_failure_and_safe_evidence():
    workflow = WORKFLOW.read_text(encoding="utf-8")

    assert workflow.count("if: always()") == 2
    assert workflow.count('echo "- Revision: \\`${GITHUB_SHA}\\`"') == 2
    assert "id: node-install" in workflow
    assert "id: node-audit" in workflow
    assert "id: python-install" in workflow
    assert "id: python-audit" in workflow
    assert "${{ steps.node-install.outcome }}" in workflow
    assert "${{ steps.node-audit.outcome }}" in workflow
    assert "${{ steps.python-install.outcome }}" in workflow
    assert "${{ steps.python-audit.outcome }}" in workflow
    assert "GITHUB_STEP_SUMMARY" in workflow
    assert "continue-on-error:" not in workflow


def test_studio_lock_pins_the_compatible_postcss_override():
    package = json.loads((STUDIO / "package.json").read_text(encoding="utf-8"))
    lock = json.loads((STUDIO / "package-lock.json").read_text(encoding="utf-8"))
    postcss = lock["packages"]["node_modules/postcss"]

    assert package["overrides"]["postcss"] == "8.5.23"
    assert postcss["version"] == "8.5.23"
    assert postcss["resolved"] == "https://registry.npmjs.org/postcss/-/postcss-8.5.23.tgz"
    assert postcss["integrity"] == (
        "sha512-g50586zr4bZmwFiTlflMu8E0bDTb5I5gertgwAKmsdUlTQIhZtunzUlD1WSzwcVWPoAVpsrA6vlfCD7oXvRwgg=="
    )
    assert package["overrides"]["nanoid"] == "3.3.18"
    assert lock["packages"]["node_modules/nanoid"]["version"] == "3.3.18"


def test_studio_uses_the_supported_eslint_runtime_contract():
    package = json.loads((STUDIO / "package.json").read_text(encoding="utf-8"))
    lock = json.loads((STUDIO / "package-lock.json").read_text(encoding="utf-8"))
    packages = lock["packages"]

    assert package["devDependencies"]["eslint"] == "10.8.0"
    assert package["devDependencies"]["@eslint/js"] == "10.0.1"
    assert package["engines"]["node"] == "^20.19.0 || ^22.13.0 || >=24"
    assert packages["node_modules/eslint"]["version"] == "10.8.0"
    assert packages["node_modules/@eslint/js"]["version"] == "10.0.1"
    assert package["overrides"]["minimatch"] == "11.0.1"
    assert packages["node_modules/minimatch"]["version"] == "11.0.1"
    assert package["overrides"]["brace-expansion"] == "5.0.12"
    assert packages["node_modules/brace-expansion"]["version"] == "5.0.12"
    assert "node_modules/@eslint/eslintrc" not in packages


def test_patched_deepmerge_is_available_before_container_dependency_install():
    package = json.loads((STUDIO / "package.json").read_text(encoding="utf-8"))
    lock = json.loads((STUDIO / "package-lock.json").read_text(encoding="utf-8"))
    assert package["devDependencies"]["deepmerge"] == "file:vendor/deepmerge"
    assert package["overrides"]["deepmerge"] == "$deepmerge"
    assert lock["packages"]["node_modules/deepmerge"] == {"resolved": "vendor/deepmerge", "link": True}
    assert lock["packages"]["vendor/deepmerge"]["version"] == "4.3.1-voiceops.1"
    assert (STUDIO / "vendor/deepmerge/LICENSE").is_file()
    dockerfile = (STUDIO / "Dockerfile").read_text(encoding="utf-8")
    assert dockerfile.index("COPY vendor ./vendor") < dockerfile.index("RUN npm ci")


def test_studio_api_pins_the_current_fixed_cryptography_release():
    requirements = (STUDIO_API / "requirements.txt").read_text(encoding="utf-8")
    api_constraints = (STUDIO_API / "constraints.txt").read_text(encoding="utf-8")
    dev_constraints = (ROOT / "constraints-dev.txt").read_text(encoding="utf-8")

    assert "cryptography==50.0.0" in requirements.splitlines()
    assert "cryptography==50.0.0" in api_constraints.splitlines()
    assert "cryptography==50.0.0" in dev_constraints.splitlines()


def test_studio_build_tool_override_uses_the_supported_filelist_graph():
    package = json.loads((STUDIO / "package.json").read_text(encoding="utf-8"))
    lock = json.loads((STUDIO / "package-lock.json").read_text(encoding="utf-8"))
    packages = lock["packages"]
    filelist = packages["node_modules/filelist"]

    assert package["overrides"]["filelist"] == "2.0.2"
    assert filelist["version"] == "2.0.2"
    assert filelist["dependencies"]["minimatch"] == "^10.2.1"
    assert "node_modules/filelist/node_modules/minimatch" not in packages
    assert "node_modules/filelist/node_modules/brace-expansion" not in packages


def test_studio_enforces_its_node_runtime_floor_in_ci_and_image_builds():
    package = json.loads((STUDIO / "package.json").read_text(encoding="utf-8"))
    npmrc = (STUDIO / ".npmrc").read_text(encoding="utf-8").splitlines()
    studio_ci = STUDIO_CI_WORKFLOW.read_text(encoding="utf-8")
    dependency_audit = WORKFLOW.read_text(encoding="utf-8")
    dockerfile = (STUDIO / "Dockerfile").read_text(encoding="utf-8")

    assert package["engines"]["node"] == "^20.19.0 || ^22.13.0 || >=24"
    assert npmrc == ["engine-strict=true"]
    assert studio_ci.count("node-version: '22'") == 2
    assert dependency_audit.count("node-version: '22'") == 1
    assert (
        "FROM node:22-alpine@sha256:"
        "16e22a550f3863206a3f701448c45f7912c6896a62de43add43bb9c86130c3e2 AS build"
        in dockerfile
    )
    assert (
        "FROM nginx:1.28.3-alpine@sha256:"
        "a8b39bd9cf0f83869a2162827a0caf6137ddf759d50a171451b335cecc87d236"
        in dockerfile
    )

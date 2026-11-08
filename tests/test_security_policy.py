from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
POLICY = (ROOT / "SECURITY.md").read_text(encoding="utf-8")
PROJECT_SPEC = (ROOT / "docs/project-spec.md").read_text(encoding="utf-8")
VALIDATION_RUNBOOK = (ROOT / "docs/runbooks/validation.md").read_text(encoding="utf-8")


def test_security_policy_covers_both_product_contours_and_current_status() -> None:
    assert "Google Colab batch workflow" in POLICY
    assert "Studio PWA remains in active development" in POLICY
    assert "primary CI/CD/runtime records" in POLICY
    assert "does not maintain a second version snapshot" in POLICY
    assert "bounded browser capabilities" in POLICY
    assert "Existing bounded LIVE" in POLICY
    assert "do not generalize" in POLICY
    assert "unresolved Studio security decision" not in POLICY


def test_security_policy_routes_private_reports_and_authoritative_details() -> None:
    assert "private vulnerability reporting" in POLICY
    assert "Do not publish vulnerability details" in POLICY
    for path in (
        "docs/project-spec.md",
        "docs/architecture.md",
        "docs/studio-processing-contract.md",
        "docs/ci-cd-rules.md",
        "docs/runbooks/studio-platform-ops.md",
        "docs/runbooks/validation.md",
        "docs/delivery-plan.md",
    ):
        assert path in POLICY
        assert (ROOT / path).is_file()


def test_project_spec_owns_durable_colab_security_constraints() -> None:
    for marker in (
        "error.message",
        "elevenlabs_api_",
        "Parallel notebooks or tabs",
        "GITHUB_REF",
        "selected-folder workflow that defaults to dry-run",
        "standard_check",
        "Timestamped backups",
        "source filename/source mode",
        "selected-folder scan counters",
        "checker version",
    ):
        assert marker in PROJECT_SPEC

    assert "Baseline repository and Studio CI must remain secretless" in VALIDATION_RUNBOOK

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
STUDIO = ROOT / "apps/studio"


def test_browser_e2e_uses_real_browser_api_and_isolated_service_state() -> None:
    package = json.loads((STUDIO / "package.json").read_text(encoding="utf-8"))
    vite = (STUDIO / "vite.config.ts").read_text(encoding="utf-8")
    playwright = (STUDIO / "playwright.config.ts").read_text(encoding="utf-8")
    workflow = (ROOT / ".github/workflows/studio-ci.yml").read_text(
        encoding="utf-8"
    )

    assert package["scripts"]["test:e2e"] == "playwright test"
    assert package["devDependencies"]["@playwright/test"] == "1.61.1"
    assert package["overrides"]["fast-uri"] == "3.1.9"
    assert "'/api': 'http://127.0.0.1:8000'" in vite
    assert "python -m uvicorn studio_api.main:app" in playwright
    assert "cwd: '../..'" in playwright
    assert "browserName: 'chromium'" in playwright

    assert "browser-e2e:" in workflow
    assert "POSTGRES_DB: studio_browser_e2e" in workflow
    assert "image: redis:7-alpine" in workflow
    assert "STUDIO_ENVIRONMENT: test" in workflow
    assert "STUDIO_APP_ORIGIN: http://127.0.0.1:4173" in workflow
    assert "STUDIO_COOKIE_NAME: studio_e2e_session" in workflow
    assert "alembic -c apps/studio-api/alembic.ini upgrade head" in workflow
    assert "python tests/support/studio_browser_e2e_seed.py" in workflow
    assert "workflow_call:" in workflow
    from test_ci_validation import ci
    assert ci.select(["tests/test_studio_browser_e2e_contract.py"]) == (True, True)
    assert "id: playwright-cache" in workflow
    assert "if: steps.playwright-cache.outputs.cache-hit != 'true'" in workflow
    assert "npx playwright install --with-deps chromium" in workflow
    assert "npm run test:e2e" in workflow
    assert (
        "uses: actions/upload-artifact@"
        "043fb46d1a93c77aae656e7c1c64a875d1fc6a0a"
        in workflow
    )
    assert "path: apps/studio/test-results" in workflow
    assert "if-no-files-found: warn" in workflow


def test_browser_e2e_seed_guards_before_database_initialization() -> None:
    seed = (ROOT / "tests/support/studio_browser_e2e_seed.py").read_text(
        encoding="utf-8"
    )
    seed_body = seed.split("def seed() -> None:", 1)[1]

    assert 'E2E_DATABASE_NAME = "studio_browser_e2e"' in seed
    assert 'settings.environment != "test"' in seed
    assert 'settings.database_host not in {"127.0.0.1", "localhost"}' in seed
    assert seed_body.index("_require_isolated_database()") < seed_body.index(
        "from studio_api.db import SessionLocal"
    )
    assert "db.query(User.id).first() is not None" in seed
    assert "requires an empty database" in seed
    assert "status=JobSourceStatus.queued" in seed
    assert "TranscriptionJobOutput(" in seed
    assert "status=OutputReconciliationStatus.resolved" in seed
    assert "TranscriptionOutputReconciliation(" in seed
    assert 'title="Browser E2E uncertain provider job"' in seed
    assert "TranscriptionJobSourceAttempt(" in seed
    assert (
        "SourceAttemptRetryDisposition.provider_outcome_uncertain"
        in seed
    )
    assert 'failure_code="provider_timeout"' in seed
    assert 'title="Browser E2E retry-safe provider job"' in seed
    assert "SourceAttemptRetryDisposition.retry_safe" in seed
    assert 'failure_code="provider_rate_limited"' in seed
    assert 'title="Browser E2E reconciliation required job"' in seed
    assert (
        "SourceAttemptRetryDisposition.output_reconciliation_required"
        in seed
    )
    assert (
        "status=OutputReconciliationStatus.reconciliation_required"
        in seed
    )
    assert 'reconciliation_token="or_browser_e2e_pending"' in seed
    assert 'title="Browser E2E queued cancellation job"' in seed
    assert "status=JobStatus.queued" in seed
    assert "attempt_count=0" in seed
    assert 'title="Browser E2E processing cancellation job"' in seed
    assert "status=JobStatus.processing" in seed
    assert 'lease_owner_id="browser-e2e-worker"' in seed
    assert "stage=SourceAttemptStage.provider_request_started" in seed
    assert "retry_disposition=SourceAttemptRetryDisposition.undetermined" in seed
    assert "write_diagnostic_event(" in seed
    assert '"JOB_CREATED"' in seed
    assert '"OUTPUT_PERSISTED"' in seed
    assert '"JOB_COMPLETED"' in seed

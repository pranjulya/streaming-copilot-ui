import os
import shutil
import subprocess
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(
    not os.getenv("TEST_DATABASE_URL"), reason="Set TEST_DATABASE_URL for real Postgres"
)

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT = REPO_ROOT / "scripts" / "rehearse_restore.sh"


def _tool(name: str) -> str | None:
    found = shutil.which(name)
    if found:
        return found
    brew = Path(f"/opt/homebrew/opt/postgresql@16/bin/{name}")
    return str(brew) if brew.exists() else None


@pytest.mark.integration
def test_restore_rehearsal_script_is_present_and_executable() -> None:
    assert SCRIPT.exists()
    assert os.access(SCRIPT, os.X_OK), "rehearsal script must be executable"
    content = SCRIPT.read_text()
    assert "pg_dump" in content and "CREATE DATABASE" in content
    assert "DROP DATABASE IF EXISTS" in content, "rehearsal must clean up its scratch db"


@pytest.mark.integration
def test_restore_rehearsal_round_trips_the_test_database() -> None:
    """Expensive: dumps the whole test database, restores it, compares counts."""
    if os.getenv("REHEARSE_RESTORE") != "1":
        pytest.skip("set REHEARSE_RESTORE=1 to run the full dump/restore round trip")
    if _tool("pg_dump") is None:
        pytest.skip("pg_dump is not available")
    url = os.environ["TEST_DATABASE_URL"].replace("postgresql+asyncpg://", "postgresql://")
    result = subprocess.run(
        [str(SCRIPT), url, "copilot_restore_rehearsal_test"],
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "restore rehearsal passed" in result.stdout

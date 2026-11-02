import os
import sys
import tempfile
from pathlib import Path

# Must run before any `app.*` import (settings are read at import time).
os.environ["TERMINAL_NO_DOTENV"] = "1"
os.environ["TERMINAL_TRINITY_AUTO"] = "0"
os.environ["TERMINAL_ECON_AUTO"] = "0"
os.environ.pop("FRED_API_KEY", None)
os.environ.pop("ESTAT_APP_ID", None)
os.environ["TERMINAL_PROVIDER"] = "sim"
os.environ["TERMINAL_DATA_DIR"] = tempfile.mkdtemp(prefix="terminal-test-")
os.environ["SIM_TICK_SEC"] = "0.2"
os.environ.pop("TERMINAL_EXCEL_DIRS", None)
os.environ.pop("TERMINAL_EXCEL_WRITE", None)

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest  # noqa: E402


@pytest.fixture(autouse=True)
def _no_calendar_pointer():
    """Each test uses its own coverage root; forget where the earnings calendar was used last, so a fresh root does
    not inherit the previous test's calendar through the migration."""
    (Path(os.environ["TERMINAL_DATA_DIR"]) / "earnings" / "location.json").unlink(missing_ok=True)
    yield

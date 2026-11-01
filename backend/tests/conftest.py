import os
import sys
import tempfile
from pathlib import Path

# Must run before any `app.*` import (settings are read at import time).
os.environ["TERMINAL_PROVIDER"] = "sim"
os.environ["TERMINAL_DATA_DIR"] = tempfile.mkdtemp(prefix="terminal-test-")
os.environ["SIM_TICK_SEC"] = "0.2"
os.environ.pop("TERMINAL_EXCEL_DIRS", None)
os.environ.pop("TERMINAL_EXCEL_WRITE", None)

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

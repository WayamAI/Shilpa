import os
import sys
import tempfile
from pathlib import Path

# Isolate every test run in its own database and blob directory, before shilpa is imported.
_tmp = Path(tempfile.mkdtemp(prefix="shilpa-test-"))
os.environ["SHILPA_VAR_DIR"] = str(_tmp)
os.environ["DATABASE_URL"] = f"sqlite:///{(_tmp / 'test.db').as_posix()}"
os.environ["AZURE_OPENAI_ENDPOINT"] = ""
os.environ["AZURE_OPENAI_DEPLOYMENT"] = ""
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

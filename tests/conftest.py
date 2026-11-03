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
# Tests never reach a model service: the provider and its key come from here, not the developer's .env
# (fakes install through llm.use_client or by patching llm._client; the Ollama tests set their own settings).
os.environ["SHILPA_LLM_PROVIDER"] = "azure"
os.environ["SHILPA_LLM"] = "off"  # the kill switch tests expect it off; fakes bypass it
os.environ["OLLAMA_API_KEY"] = ""
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import importlib
import json
import subprocess
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"
sys.path.insert(0, str(TOOLS))


def test_director_initializes_without_anthropic_key(monkeypatch, tmp_path):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    director = importlib.import_module("director")

    instance = director.DirectorAgent(str(tmp_path))

    assert instance.ceo_dir == tmp_path


def test_analyst_reports_optional_youtube_dependency(monkeypatch):
    analyst = importlib.import_module("analyst")
    real_import = __import__

    def missing_youtube(name, *args, **kwargs):
        if name == "yt_dlp":
            raise ImportError("not installed")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr("builtins.__import__", missing_youtube)

    with pytest.raises(RuntimeError, match="requirements-youtube.txt"):
        analyst.ContentExtractor._load_yt_dlp()


def test_openclaw_response_is_parsed(monkeypatch):
    api = importlib.import_module("api")
    response = {
        "result": {"payloads": [{"text": "working response"}]},
    }

    monkeypatch.setattr(
        api.subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            args[0], 0, stdout=json.dumps(response), stderr=""
        ),
    )

    assert api.call_claude("system", "user") == "working response"

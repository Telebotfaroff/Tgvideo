import json

import pytest

from app.main import load_manifest


def test_loads_manifest(tmp_path):
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps({"items": [
        {"id": "one", "url": "https://cdn.example.test/video.mp4", "title": "Video"}
    ]}), encoding="utf-8")
    items = load_manifest(path)
    assert len(items) == 1
    assert items[0]["id"] == "one"


def test_rejects_duplicate_ids(tmp_path):
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps({"items": [
        {"id": "same", "url": "https://cdn.example.test/a.mp4"},
        {"id": "same", "url": "https://cdn.example.test/b.mp4"}
    ]}), encoding="utf-8")
    with pytest.raises(ValueError, match="Duplicate"):
        load_manifest(path)


def test_rejects_invalid_scheme(tmp_path):
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps({"items": [
        {"id": "bad", "url": "file:///tmp/video.mp4"}
    ]}), encoding="utf-8")
    with pytest.raises(ValueError, match="HTTP"):
        load_manifest(path)


def test_requires_items_array(tmp_path):
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps({"items": []}), encoding="utf-8")
    assert load_manifest(path) == []

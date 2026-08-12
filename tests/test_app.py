"""Smoke test for the web UI's generation pipeline (mock provider)."""

import app


def test_run_pipeline_mock():
    result = app._run_pipeline({
        "brand": "Luca Menasveta",
        "provider": "mock",
        "prospects": [
            {"first_name": "Priya", "company": "Ramp", "role": "VP Sales"},
            {"company": ""},  # blank company is dropped
        ],
    })

    assert result["summary"] == {"ok": 1, "failed": 0}
    card = result["assets"][0]
    assert card["company"] == "Ramp"
    assert card["subject"]
    assert card["thumbnail"].startswith("data:image/png;base64,")
    assert "Priya" in card["spoken"]


def test_run_pipeline_needs_a_prospect():
    result = app._run_pipeline({"provider": "mock", "prospects": []})
    assert "error" in result

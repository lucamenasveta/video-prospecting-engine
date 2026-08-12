"""Tests for the CSV loader and the offline mock provider."""

import video_prospector as vp


# --- CSV loader -----------------------------------------------------------


def _write_csv(tmp_path, text):
    path = tmp_path / "prospects.csv"
    path.write_text(text, encoding="utf-8")
    return path


def test_load_prospects_basic(tmp_path):
    csv_path = _write_csv(
        tmp_path,
        "first_name,company,role,industry,website\n"
        "Priya,Ramp,VP Sales,fintech,ramp.com\n",
    )
    prospects = vp.load_prospects(csv_path)

    assert len(prospects) == 1
    p = prospects[0]
    assert isinstance(p, vp.Prospect)
    assert (p.first_name, p.company, p.role) == ("Priya", "Ramp", "VP Sales")


def test_load_prospects_skips_rows_without_company(tmp_path):
    csv_path = _write_csv(
        tmp_path,
        "first_name,company\n"
        "Priya,Ramp\n"
        "Nobody,\n",  # no company -> skipped
    )
    prospects = vp.load_prospects(csv_path)
    assert [p.company for p in prospects] == ["Ramp"]


def test_load_prospects_normalizes_headers_and_whitespace(tmp_path):
    # Uppercase headers and padded values should still parse.
    csv_path = _write_csv(
        tmp_path,
        "First_Name,COMPANY\n"
        "  Marcus ,  Notion  \n",
    )
    p = vp.load_prospects(csv_path)[0]
    assert p.first_name == "Marcus"
    assert p.company == "Notion"


def test_load_prospects_missing_first_name_defaults(tmp_path):
    csv_path = _write_csv(tmp_path, "company\nDeel\n")
    p = vp.load_prospects(csv_path)[0]
    assert p.first_name == "there"


# --- mock provider --------------------------------------------------------


def test_generate_mock_shape():
    result = vp.generate_mock(vp.Prospect(first_name="Priya", company="Ramp", role="VP Sales"))

    assert set(result) == {"signal", "signal_source", "subject", "stages"}
    assert set(result["stages"]) == {"hook", "bridge", "value", "cta"}
    # Personalization: the hook names the prospect, the subject names the company.
    assert "Priya" in result["stages"]["hook"]
    assert "Ramp" in result["subject"]


def test_generate_mock_is_deterministic():
    p = vp.Prospect(first_name="Priya", company="Ramp")
    assert vp.generate_mock(p) == vp.generate_mock(p)


def test_generate_mock_signal_is_not_a_real_citation():
    # The offline signal must be clearly labeled as fake, never a real source.
    result = vp.generate_mock(vp.Prospect(first_name="Priya", company="Ramp"))
    assert "mock" in result["signal_source"].lower()


def test_slugify():
    assert vp.slugify("Acme, Inc.") == "acme-inc"
    assert vp.slugify("") == "prospect"

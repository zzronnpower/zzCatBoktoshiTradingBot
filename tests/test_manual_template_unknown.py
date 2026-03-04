from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_manual_template_has_unknown_positions_management_section():
    html = (ROOT / "app" / "templates" / "manual.html").read_text(encoding="utf-8")
    assert "CLOSE UNKNOWN POSITION" in html
    assert "id=\"unknown-close-position\"" in html
    assert "Close Unknown Position" in html
    assert "Close All Unknown Positions" in html
    assert "id=\"positions-unknown\"" in html
    assert "/api/manual/close-unknown-position" in html
    assert "/api/manual/close-all-unknown-positions" in html

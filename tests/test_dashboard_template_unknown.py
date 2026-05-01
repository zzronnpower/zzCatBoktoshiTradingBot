from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_dashboard_template_renders_unknown_positions_section():
    html = (ROOT / "app" / "templates" / "index.html").read_text(encoding="utf-8")
    assert "Unknown Position" in html
    assert "id=\"positions-unknown\"" in html
    assert "positions.unknown_positions" in html

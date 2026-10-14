import base64
from unittest.mock import patch
import pytest
from core import auth


def test_qr_component_empty():
    with patch("streamlit.image") as mock_img:
        auth.qr_component("")
        auth.qr_component(None)
        mock_img.assert_not_called()


def test_qr_component_svg_raw():
    raw_svg = '<svg viewBox="0 0 200 200"><rect/></svg>'
    with patch("streamlit.image") as mock_img:
        auth.qr_component(raw_svg)
        mock_img.assert_called_once()
        src, kwargs = mock_img.call_args[0][0], mock_img.call_args[1]
        assert src.startswith("data:image/svg+xml;base64,")
        assert kwargs.get("width") == 220
        decoded = base64.b64decode(src.split(",", 1)[1]).decode("utf-8")
        assert 'xmlns="http://www.w3.org/2000/svg"' in decoded
        assert "<rect/>" in decoded


def test_qr_component_gotrue_data_uri():
    gotrue_qr = 'data:image/svg+xml;utf-8,<svg xmlns="http://www.w3.org/2000/svg" width="256" height="256" viewBox="0 0 256 256"><path d="M0 0"/></svg>'
    with patch("streamlit.image") as mock_img:
        auth.qr_component(gotrue_qr)
        mock_img.assert_called_once()
        src, kwargs = mock_img.call_args[0][0], mock_img.call_args[1]
        assert src.startswith("data:image/svg+xml;base64,")
        assert kwargs.get("width") == 220
        decoded = base64.b64decode(src.split(",", 1)[1]).decode("utf-8")
        assert 'viewBox="0 0 256 256"' in decoded
        assert "<path" in decoded


def test_qr_component_fallback_png():
    png_data = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
    with patch("streamlit.image") as mock_img:
        auth.qr_component(png_data)
        mock_img.assert_called_once_with(png_data, width=220)

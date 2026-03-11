"""Tests for CLI functions — Ollama install/ensure helpers."""

from __future__ import annotations

from unittest.mock import MagicMock, patch


class TestCheckOllama:
    """Tests for _check_ollama connectivity check."""

    @patch("urllib.request.urlopen")
    def test_returns_true_when_running(self, mock_urlopen: MagicMock) -> None:
        mock_urlopen.return_value.__enter__ = MagicMock()
        mock_urlopen.return_value.__exit__ = MagicMock(return_value=False)
        from agenttop.cli import _check_ollama
        assert _check_ollama() is True

    @patch("urllib.request.urlopen", side_effect=ConnectionError("refused"))
    def test_returns_false_when_not_running(self, _: MagicMock) -> None:
        from agenttop.cli import _check_ollama
        assert _check_ollama() is False

    @patch("urllib.request.urlopen", side_effect=TimeoutError("timeout"))
    def test_returns_false_on_timeout(self, _: MagicMock) -> None:
        from agenttop.cli import _check_ollama
        assert _check_ollama() is False


class TestInstallOllama:
    """Tests for _install_ollama."""

    @patch("shutil.which", return_value="/usr/local/bin/ollama")
    def test_already_installed(self, _: MagicMock) -> None:
        from agenttop.cli import _install_ollama
        result = _install_ollama()
        assert result == "/usr/local/bin/ollama"

    @patch("shutil.which", return_value=None)
    @patch("platform.system", return_value="Windows")
    def test_unsupported_platform(self, _sys: MagicMock, _which: MagicMock) -> None:
        from agenttop.cli import _install_ollama
        result = _install_ollama()
        assert result is None

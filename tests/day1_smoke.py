import pytest
from unittest.mock import MagicMock, patch


def test_import_cli():
    from lustre_agent.cli import app
    assert app is not None


def test_get_llm_has_invoke():
    from lustre_agent.llm import get_llm
    llm = get_llm()
    assert hasattr(llm, "invoke")


def test_hello_command_with_mock(monkeypatch):
    from typer.testing import CliRunner
    import lustre_agent.cli as cli_module

    fake_response = MagicMock()
    fake_response.content = "Hello! I'm your AI assistant."

    fake_llm = MagicMock()
    fake_llm.invoke.return_value = fake_response

    monkeypatch.setattr(cli_module, "get_llm", lambda: fake_llm)

    runner = CliRunner()
    result = runner.invoke(cli_module.app, ["hello"])

    assert result.exit_code == 0
    assert "Hello" in result.output
    fake_llm.invoke.assert_called_once_with("Say hi in one sentence")

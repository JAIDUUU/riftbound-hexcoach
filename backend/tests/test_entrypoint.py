import pytest

from backend.cli import main


def test_entrypoint_runs_and_identifies_the_app(capsys: pytest.CaptureFixture[str]) -> None:
    exit_code = main([])

    assert exit_code == 0
    assert "hexcoach" in capsys.readouterr().out.lower()

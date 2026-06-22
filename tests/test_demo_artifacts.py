from pathlib import Path


def test_demo_docs_and_scripts_exist() -> None:
    assert Path("docs/demo_playbook.md").is_file()
    assert Path("docs/operator_manual.md").is_file()
    assert Path("scripts/demo_p1_flow.sh").is_file()
    assert Path("scripts/seed_demo_data.py").is_file()


def test_demo_docs_preserve_non_production_boundary() -> None:
    playbook = Path("docs/demo_playbook.md").read_text(encoding="utf-8")
    manual = Path("docs/operator_manual.md").read_text(encoding="utf-8")

    assert "not a production" in playbook
    assert "not for real money" in manual


def test_demo_script_is_executable() -> None:
    assert Path("scripts/demo_p1_flow.sh").stat().st_mode & 0o111

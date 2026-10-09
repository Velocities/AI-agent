from ai_agent.cli.monitoring_cmd import main
from ai_agent.conversations.db import open_stores_at

USER = "11111111-1111-4111-8111-111111111111"


def test_grant_is_idempotent_and_revoke_removes_the_row(tmp_path) -> None:
    _store, _access, _repo, admins = open_stores_at(f"sqlite:///{tmp_path / 'db.sqlite3'}")
    record, created = admins.grant(f"  {USER}  ")
    assert created is True
    assert record.user_id == USER
    again, created_again = admins.grant(USER)
    assert created_again is False
    assert again.created_at == record.created_at
    assert [row.user_id for row in admins.list_admins()] == [USER]
    assert admins.revoke(USER) is True
    assert admins.contains(USER) is False
    assert admins.revoke(USER) is False


def test_cli_grant_list_and_revoke(tmp_path, monkeypatch) -> None:
    url = f"sqlite:///{tmp_path / 'cli.sqlite3'}"
    monkeypatch.setattr(
        "ai_agent.cli.monitoring_cmd.database_url_for_admin_cli",
        lambda _settings, *, service_db: url,
    )
    assert main(["grant", USER]) == 0
    assert main(["grant", USER]) == 0
    assert main(["list"]) == 0
    assert main(["revoke", USER]) == 0
    assert main(["revoke", USER]) == 1
    assert main(["grant", "   "]) == 1
    _store, _access, _repo, admins = open_stores_at(url)
    assert admins.list_admins() == []

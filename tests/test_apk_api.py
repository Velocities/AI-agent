import os
from datetime import datetime, timezone

from fastapi.testclient import TestClient

from ai_agent.api.app import create_app
from ai_agent.api.auth import AuthenticatedUser
from ai_agent.apk.listing import format_modified
from ai_agent.config import Settings
from ai_agent.conversations.db import open_stores_at

USER = "11111111-1111-4111-8111-111111111111"
OTHER = "22222222-2222-4222-8222-222222222222"


class _Verifier:
    def verify(self, token: str) -> AuthenticatedUser:
        return AuthenticatedUser(user_id=token)


def _auth(user_id: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {user_id}"}


def _client(tmp_path, directory, *, grant: str | None, enabled: bool = True) -> TestClient:
    _store, _access, _repo, admins = open_stores_at(f"sqlite:///{tmp_path / 'db.sqlite3'}")
    if grant:
        admins.grant(grant)
    settings = Settings(
        supabase_url="https://proj.supabase.co",
        supabase_anon_key="publishable",
        apk_downloads_enabled=enabled,
        apk_publish_dir=str(directory),
    )
    return TestClient(
        create_app(settings, _Verifier(), monitoring_admin_store=admins)
    )


def test_admin_can_list_and_download_apks(tmp_path) -> None:
    directory = tmp_path / "apks"
    directory.mkdir()
    apk = directory / "app-debug.apk"
    apk.write_bytes(b"apk-bytes")
    (directory / "notes.txt").write_text("not-an-apk")
    when = datetime(2026, 10, 8, 21, 6, 33, tzinfo=timezone.utc)
    os.utime(apk, (when.timestamp(), when.timestamp()))
    modified = format_modified(datetime.fromtimestamp(apk.stat().st_mtime, tz=timezone.utc))

    with _client(tmp_path, directory, grant=USER) as client:
        page = client.get("/api/apk/", headers=_auth(USER))
        bare = client.get("/api/apk", headers=_auth(USER))
        download = client.get("/api/apk/app-debug.apk", headers=_auth(USER))

    assert page.status_code == 200
    assert bare.status_code == 200
    assert bare.text == page.text
    assert "text/html" in page.headers["content-type"]
    assert "Index of APK builds" in page.text
    assert "Last modified" in page.text
    assert modified in page.text
    assert 'href="/api/apk/app-debug.apk"' in page.text
    assert "notes.txt" not in page.text
    assert download.status_code == 200
    assert download.content == b"apk-bytes"
    assert download.headers["content-type"].startswith(
        "application/vnd.android.package-archive"
    )


def test_non_admin_apk_page_is_forbidden(tmp_path) -> None:
    directory = tmp_path / "apks"
    directory.mkdir()
    (directory / "app-debug.apk").write_bytes(b"apk-bytes")

    with _client(tmp_path, directory, grant=USER) as client:
        page = client.get("/api/apk/", headers=_auth(OTHER))
        download = client.get("/api/apk/app-debug.apk", headers=_auth(OTHER))

    assert page.status_code == 403
    assert page.json()["detail"] == "Unauthorized"
    assert download.status_code == 403
    assert download.json()["detail"] == "Unauthorized"
    assert b"apk-bytes" not in page.content
    assert b"apk-bytes" not in download.content


def test_apk_page_stays_off_until_the_deployment_enables_it(tmp_path) -> None:
    directory = tmp_path / "apks"
    directory.mkdir()
    (directory / "app-debug.apk").write_bytes(b"apk-bytes")

    with _client(tmp_path, directory, grant=USER, enabled=False) as client:
        page = client.get("/api/apk/", headers=_auth(USER))

    assert page.status_code == 404
    assert "not enabled" in page.text
    assert b"apk-bytes" not in page.content


def test_apk_download_rejects_names_outside_the_publish_directory(tmp_path) -> None:
    directory = tmp_path / "apks"
    directory.mkdir()
    outside = tmp_path / "secret.apk"
    outside.write_bytes(b"secret")
    (directory / "linked.apk").symlink_to(outside)

    with _client(tmp_path, directory, grant=USER) as client:
        listed = client.get("/api/apk/", headers=_auth(USER))
        escaped = client.get("/api/apk/linked.apk", headers=_auth(USER))
        dotted = client.get("/api/apk/..%2Fsecret.apk", headers=_auth(USER))

    assert "linked.apk" not in listed.text
    assert "secret" not in listed.text
    assert escaped.status_code == 404
    assert dotted.status_code == 404
    assert b"secret" not in escaped.content

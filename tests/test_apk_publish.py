from datetime import datetime, timezone

from ai_agent.apk.publish import STORAGE_WARNING_COUNT, locate_debug_apk, publish_apk
from ai_agent.cli.app import main as app_main


def test_publish_keeps_older_apks_and_warns_at_ten(tmp_path) -> None:
    dest = tmp_path / "apks"
    dest.mkdir()
    for index in range(STORAGE_WARNING_COUNT - 1):
        (dest / f"old-{index}.apk").write_bytes(b"old")
    source = tmp_path / "app-debug.apk"
    source.write_bytes(b"new")

    result = publish_apk(
        source,
        dest,
        now=datetime(2026, 10, 8, 21, 6, 33, tzinfo=timezone.utc),
    )

    assert result.warning is True
    assert result.count == STORAGE_WARNING_COUNT
    assert result.path.name == "app-debug-20261008-210633.apk"
    assert result.path.read_bytes() == b"new"
    assert (dest / "old-0.apk").read_bytes() == b"old"


def test_publish_does_not_warn_below_ten(tmp_path) -> None:
    dest = tmp_path / "apks"
    source = tmp_path / "app-debug.apk"
    source.write_bytes(b"new")

    result = publish_apk(source, dest)

    assert result.warning is False
    assert result.count == 1
    assert result.path.is_file()


def test_apk_publish_command_copies_the_gradle_debug_apk(tmp_path, monkeypatch, capsys) -> None:
    gradle_apk = tmp_path / "clients/android/app/build/outputs/apk/debug/app-debug.apk"
    gradle_apk.parent.mkdir(parents=True)
    gradle_apk.write_bytes(b"from-gradle")
    dest = tmp_path / "published"
    dest.mkdir()
    (dest / "already-there.apk").write_bytes(b"keep")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("APK_PUBLISH_DIR", str(dest))

    assert app_main(["apk", "publish"]) == 0

    published = [path for path in dest.glob("*.apk") if path.name != "already-there.apk"]
    assert len(published) == 1
    assert published[0].read_bytes() == b"from-gradle"
    assert "Published" in capsys.readouterr().out
    assert locate_debug_apk(tmp_path) == gradle_apk


def test_apk_publish_command_warns_when_the_directory_reaches_ten(tmp_path, monkeypatch, capsys) -> None:
    dest = tmp_path / "published"
    dest.mkdir()
    for index in range(STORAGE_WARNING_COUNT - 1):
        (dest / f"old-{index}.apk").write_bytes(b"old")
    source = tmp_path / "app-debug.apk"
    source.write_bytes(b"new")
    monkeypatch.setenv("APK_PUBLISH_DIR", str(dest))

    assert app_main(["apk", "publish", "--apk", str(source)]) == 0

    err = capsys.readouterr().err
    assert "Warning:" in err
    assert str(STORAGE_WARNING_COUNT) in err
    assert len(list(dest.glob("*.apk"))) == STORAGE_WARNING_COUNT


def test_apk_publish_command_reports_a_missing_build(tmp_path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("APK_PUBLISH_DIR", str(tmp_path / "published"))

    assert app_main(["apk", "publish"]) == 1
    assert "assembleDebug" in capsys.readouterr().err

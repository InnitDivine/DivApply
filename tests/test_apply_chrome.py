from __future__ import annotations

from divapply.apply import chrome


def test_setup_worker_profile_creates_blank_marked_chrome_profile(tmp_path, monkeypatch) -> None:
    worker_root = tmp_path / "chrome-workers"
    monkeypatch.setattr(chrome.config, "CHROME_WORKER_DIR", worker_root)
    monkeypatch.setattr(
        chrome.config,
        "get_chrome_user_data",
        lambda: (_ for _ in ()).throw(AssertionError("host Chrome profile was inspected")),
    )

    profile = chrome.setup_worker_profile(0, "chrome")

    assert profile == worker_root / "worker-0"
    assert (profile / chrome.PROFILE_MARKER_NAME).read_text(encoding="utf-8").strip() == "2"
    assert not (profile / "Default").exists()


def test_setup_worker_profile_refuses_unmarked_legacy_chrome_profile(tmp_path, monkeypatch) -> None:
    worker_root = tmp_path / "chrome-workers"
    profile = worker_root / "worker-0"
    (profile / "Default").mkdir(parents=True)
    sensitive = profile / "Default" / "Cookies"
    sensitive.write_text("legacy-cookie-data", encoding="utf-8")
    monkeypatch.setattr(chrome.config, "CHROME_WORKER_DIR", worker_root)

    try:
        chrome.setup_worker_profile(0, "chrome")
    except RuntimeError as exc:
        message = str(exc).lower()
        assert "legacy" in message
        assert "browser-login" in message
    else:
        raise AssertionError("unmarked legacy Chrome profile was accepted")

    assert sensitive.read_text(encoding="utf-8") == "legacy-cookie-data"
    assert not (profile / chrome.PROFILE_MARKER_NAME).exists()


def test_setup_worker_profile_reuses_only_marked_chrome_profile(tmp_path, monkeypatch) -> None:
    worker_root = tmp_path / "chrome-workers"
    profile = worker_root / "worker-3"
    (profile / "Default").mkdir(parents=True)
    marker = profile / ".divapply-profile-v2"
    marker.write_text("2\n", encoding="utf-8")
    monkeypatch.setattr(chrome.config, "CHROME_WORKER_DIR", worker_root)

    assert chrome.setup_worker_profile(3, "chrome") == profile


def test_setup_worker_profile_does_not_clone_another_worker(tmp_path, monkeypatch) -> None:
    worker_root = tmp_path / "chrome-workers"
    worker_0 = worker_root / "worker-0"
    (worker_0 / "Default").mkdir(parents=True)
    (worker_0 / ".divapply-profile-v2").write_text("2\n", encoding="utf-8")
    (worker_0 / "Default" / "Cookies").write_text("worker-0-cookie", encoding="utf-8")
    monkeypatch.setattr(chrome.config, "CHROME_WORKER_DIR", worker_root)

    worker_1 = chrome.setup_worker_profile(1, "chrome")

    assert (worker_1 / chrome.PROFILE_MARKER_NAME).exists()
    assert not (worker_1 / "Default").exists()


def test_launch_chrome_refuses_occupied_port_without_killing_process(monkeypatch) -> None:
    monkeypatch.setattr(chrome, "_port_is_available", lambda port: False, raising=False)
    monkeypatch.setattr(
        chrome,
        "_kill_process_tree",
        lambda pid: (_ for _ in ()).throw(AssertionError("unowned process was killed")),
    )
    monkeypatch.setattr(
        chrome,
        "setup_worker_profile",
        lambda worker_id: (_ for _ in ()).throw(AssertionError("profile setup should not start")),
    )

    try:
        chrome.launch_chrome(0, port=9222)
    except RuntimeError as exc:
        assert "refusing to terminate" in str(exc).lower()
    else:
        raise AssertionError("occupied CDP port was accepted")


def test_kill_all_chrome_only_terminates_tracked_processes(monkeypatch) -> None:
    assert not hasattr(chrome, "_kill_on_port")
    killed: list[int] = []

    class Proc:
        pid = 4242

        def poll(self):
            return None

    monkeypatch.setattr(chrome, "_chrome_procs", {2: Proc()})
    monkeypatch.setattr(chrome, "_kill_process_tree", killed.append)

    chrome.kill_all_chrome()

    assert killed == [4242]
    assert chrome._chrome_procs == {}

from tools.confirm_upstream_pages import decide


def test_pages_success_passes():
    assert decide(
        status="completed",
        conclusion="success",
        current_sha="a",
    ).action == "pass"


def test_in_progress_waits():
    assert decide(
        status="in_progress",
        conclusion="",
        current_sha="a",
    ).action == "wait"


def test_cancelled_same_session_new_sha_follows():
    result = decide(
        status="completed",
        conclusion="cancelled",
        current_sha="a",
        latest_sha="b",
        same_session_ok=True,
        supersedes=0,
    )
    assert result.action == "follow"


def test_cancelled_same_sha_fails():
    result = decide(
        status="completed",
        conclusion="cancelled",
        current_sha="a",
        latest_sha="a",
        same_session_ok=True,
    )
    assert result.action == "fail"


def test_cancelled_session_drift_fails():
    result = decide(
        status="completed",
        conclusion="cancelled",
        current_sha="a",
        latest_sha="b",
        same_session_ok=False,
    )
    assert result.action == "fail"


def test_real_pages_failure_fails():
    result = decide(
        status="completed",
        conclusion="failure",
        current_sha="a",
    )
    assert result.action == "fail"


def test_supersede_limit_fails():
    result = decide(
        status="completed",
        conclusion="cancelled",
        current_sha="a",
        latest_sha="b",
        same_session_ok=True,
        supersedes=8,
        max_supersedes=8,
    )
    assert result.action == "fail"

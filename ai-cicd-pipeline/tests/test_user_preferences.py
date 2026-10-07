from app.services.user_preferences import get_user_preferences, update_user_preferences


def test_default_preferences():
    prefs = get_user_preferences({})
    assert prefs["default_branch"] == "main"
    assert prefs["auto_pr_enabled"] is True


def test_update_preferences():
    session: dict = {}
    updated = update_user_preferences(
        session,
        {
            "default_branch": "develop",
            "default_repo_url": "https://github.com/org/app.git",
            "default_repo_name": "org/app",
            "auto_pr_enabled": False,
        },
    )
    assert updated["default_branch"] == "develop"
    assert updated["auto_pr_enabled"] is False
    assert session["user_preferences"]["default_repo_name"] == "org/app"

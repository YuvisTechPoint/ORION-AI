"""Cross-stack navigation catalog tests."""

from app.services.navigation import stack_catalog


def test_stack_catalog_includes_all_stacks() -> None:
    nav = stack_catalog()
    ids = {s["id"] for s in nav["stacks"]}
    assert ids == {"hub", "canonical", "orion", "platform"}
    assert nav["active_stack"] == "orion"
    assert nav["orion"]["api_base"].startswith("http")


def test_stack_urls_are_absolute() -> None:
    nav = stack_catalog()
    for stack in nav["stacks"]:
        if stack.get("ui"):
            assert str(stack["ui"]).startswith("http")
        if stack.get("health"):
            assert str(stack["health"]).startswith("http")

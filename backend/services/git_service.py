from __future__ import annotations


class GitService:
    """Lightweight git context holder used by AutoPRService.

    Branch/file commit operations are executed through the GitHub REST API.
    This service currently tracks repository clone metadata for future local git workflows.
    """

    def __init__(self, clone_url: str) -> None:
        self.clone_url = clone_url

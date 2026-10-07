from pydantic import BaseModel, ConfigDict, Field


class GitHubCommit(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str
    message: str = ""
    author: dict = Field(default_factory=dict)
    added: list[str] = Field(default_factory=list)
    modified: list[str] = Field(default_factory=list)
    removed: list[str] = Field(default_factory=list)


class GitHubRepository(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: int | None = None
    full_name: str
    clone_url: str
    default_branch: str = "main"


class GitHubPusher(BaseModel):
    model_config = ConfigDict(extra="allow")

    name: str = Field(default="")
    email: str = ""


class GitHubPushPayload(BaseModel):
    model_config = ConfigDict(extra="allow")

    ref: str
    after: str
    before: str = ""
    repository: GitHubRepository
    pusher: GitHubPusher = Field(default_factory=GitHubPusher)
    head_commit: GitHubCommit | None = None
    commits: list[GitHubCommit] = Field(default_factory=list)

    @property
    def branch(self) -> str:
        prefix = "refs/heads/"
        return self.ref[len(prefix) :] if self.ref.startswith(prefix) else self.ref.split("/")[-1]

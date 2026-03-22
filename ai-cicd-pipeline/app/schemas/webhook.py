from pydantic import BaseModel, ConfigDict, Field


class GitHubCommit(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str
    message: str = ""


class GitHubRepository(BaseModel):
    model_config = ConfigDict(extra="allow")

    full_name: str
    clone_url: str


class GitHubPusher(BaseModel):
    model_config = ConfigDict(extra="allow")

    name: str = Field(default="")


class GitHubPushPayload(BaseModel):
    model_config = ConfigDict(extra="allow")

    ref: str
    after: str
    commits: list[GitHubCommit] = Field(default_factory=list)
    repository: GitHubRepository
    pusher: GitHubPusher = Field(default_factory=GitHubPusher)

    @property
    def branch(self) -> str:
        return self.ref.split("/")[-1]

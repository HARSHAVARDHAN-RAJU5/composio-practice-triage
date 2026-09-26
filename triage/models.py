"""Shared data shapes."""
from typing import List, Optional

from pydantic import AliasPath, BaseModel, ConfigDict, Field, field_validator


class RepoRef(BaseModel):
    owner: str
    repo: str
    number: Optional[int] = None  # set when the target is a single issue

    @property
    def full_name(self) -> str:
        return f"{self.owner}/{self.repo}"


class Issue(BaseModel):
    """An issue as GitHub's REST API returns it; raises ValidationError on a bad shape."""

    model_config = ConfigDict(populate_by_name=True)

    number: int
    title: str = ""
    body: str = ""
    labels: List[str] = []
    author: str = Field("unknown", validation_alias=AliasPath("user", "login"))
    state: str = "unknown"
    url: str = Field("", validation_alias="html_url")
    repo: str  # owner/repo

    @field_validator("title", "body", "state", "url", mode="before")
    @classmethod
    def _none_to_empty(cls, v):
        return "" if v is None else v

    @field_validator("body")
    @classmethod
    def _strip_body(cls, v: str) -> str:
        return v.strip()

    @field_validator("labels", mode="before")
    @classmethod
    def _label_names(cls, v):
        # GitHub sends label objects; accept plain names too
        return [label.get("name") if isinstance(label, dict) else label for label in v or []]

    @classmethod
    def from_github(cls, data: dict, repo: RepoRef) -> "Issue":
        return cls.model_validate({**data, "repo": repo.full_name})

"""Shared data shapes."""
from typing import List, Literal, Optional

from pydantic import AliasPath, BaseModel, ConfigDict, Field, field_validator

Category = Literal["bug", "feature", "question", "unclear"]


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
    comments: int = 0  # comment count; 0 means we can skip looking for our own earlier reply
    repo: str  # owner/repo

    @property
    def ref(self) -> "RepoRef":
        owner, name = self.repo.split("/", 1)
        return RepoRef(owner=owner, repo=name, number=self.number)

    @field_validator("title", "body", "state", "url", mode="before")
    @classmethod
    def _none_to_empty(cls, v):
        return "" if v is None else v

    @field_validator("comments", mode="before")
    @classmethod
    def _none_to_zero(cls, v):
        return v or 0

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


class Evidence(BaseModel):
    """Yes/no facts about the issue text. Our code turns these into the confidence score."""

    # every issue (strict wording: Gemini says "yes" to loose questions almost always)
    actionable: bool = Field(
        description="Could a maintainer start working on this without asking the author anything first? "
        "False if any key detail is missing."
    )
    single_topic: bool = Field(
        description="Does the issue raise exactly one problem, request or question? "
        "False if it mentions two or more separate things, even briefly."
    )
    fits_another_category: bool = Field(description="Could the issue reasonably belong to a different category?")
    # bug
    has_repro_steps: bool = Field(description="Does it say how or when the problem happens?")
    has_error_or_logs: bool = Field(description="Does it include an error message, stack trace or log?")
    has_expected_vs_actual: bool = Field(description="Does it say what should happen and what happens instead?")
    has_environment: bool = Field(description="Does it give a version, OS, browser or device?")
    # feature
    describes_behaviour: bool = Field(description="Does it say concretely what the new behaviour should be?")
    explains_use_case: bool = Field(description="Does it say why the feature is needed?")
    # question
    specific_question: bool = Field(description="Does it ask one specific, answerable question?")
    shows_effort: bool = Field(description="Does it say what the author already tried or read?")


class Classification(BaseModel):
    """What Gemini must return. Also sent to Gemini as the JSON schema, so descriptions are prompts."""

    category: Category = Field(
        description="bug: something is broken. feature: a request for new behaviour. "
        "question: asking how to do something. unclear: not enough information to tell."
    )
    evidence: Evidence
    # Gemini's own estimate: logged for comparison only, never used for decisions (it is ~1.0 almost always)
    model_confidence: float = Field(ge=0, le=1, description="How sure you are of the category, 0.0 to 1.0.")
    reason: str = Field(description="One short sentence explaining the category.")
    reply: str = Field(description="The public reply to post on the issue, 20 to 150 words.")


class ScorePart(BaseModel):
    label: str
    delta: float


class Confidence(BaseModel):
    """Computed confidence and every part that went into it."""

    score: float
    parts: List[ScorePart]

    def explain(self) -> str:
        return " ".join(f"{'+' if p.delta >= 0 else '-'} {p.label} {abs(p.delta):.2f}" for p in self.parts).lstrip("+ ")


class RuleResult(BaseModel):
    rule: str  # "R1".."R7", "SECURITY", "OUTPUT"
    passed: bool
    detail: str

import pytest

from triage.tools.urls import InvalidTarget, parse_target


@pytest.mark.parametrize(
    "text, owner, repo, number",
    [
        ("octocat/Hello-World", "octocat", "Hello-World", None),
        ("octocat/Hello-World#12", "octocat", "Hello-World", 12),
        ("https://github.com/octocat/Hello-World", "octocat", "Hello-World", None),
        ("https://github.com/octocat/Hello-World/", "octocat", "Hello-World", None),
        ("https://www.github.com/octocat/Hello-World.git", "octocat", "Hello-World", None),
        ("https://github.com/octocat/Hello-World/issues/7", "octocat", "Hello-World", 7),
        ("  octocat/my.repo_1  ", "octocat", "my.repo_1", None),
    ],
)
def test_valid_targets(text, owner, repo, number):
    ref = parse_target(text)
    assert (ref.owner, ref.repo, ref.number) == (owner, repo, number)


@pytest.mark.parametrize(
    "text",
    [
        "",
        "octocat",
        "https://gitlab.com/octocat/Hello-World",
        "https://github.com/octocat/Hello-World/pull/3",
        "https://github.com/octocat/Hello-World/issues/0",
        "https://github.com/octocat/Hello-World/issues/abc",
        "https://github.com/-bad/repo",
        "octocat/..",
        "https://evil.com/github.com/octocat/Hello-World",
    ],
)
def test_invalid_targets(text):
    with pytest.raises(InvalidTarget):
        parse_target(text)

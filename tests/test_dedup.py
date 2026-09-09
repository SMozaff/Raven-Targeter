from raven_targeter.core.deduplicator import deduplicate
from raven_targeter.models import CandidateEndpoint, Discovery


def test_code_evidence_merges_into_repository_by_identity():
    repo = Discovery(title="u/r", url="https://github.com/u/r", repo_identity="github.com/u/r", source_type="repository")
    code = Discovery(
        title="u/r — app.py", url="https://github.com/u/r/blob/main/app.py",
        repo_identity="github.com/u/r", source_type="code",
        evidence=["implementation"],
        candidate_endpoints=[CandidateEndpoint(url="https://api.example.com/v1", evidence="code", kind="api-base")],
    )
    merged, removed = deduplicate([repo, code])
    assert removed == 1
    assert len(merged) == 1
    assert merged[0].source_type == "repository"
    assert merged[0].candidate_endpoints[0].url == "https://api.example.com/v1"

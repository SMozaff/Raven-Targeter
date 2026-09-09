import json
from raven_targeter.models import CandidateEndpoint, Discovery
from raven_targeter.services.export_service import export_json


def test_versioned_export_contains_candidate_endpoints(tmp_path):
    d = Discovery(
        title="u/r", url="https://github.com/u/r",
        candidate_endpoints=[CandidateEndpoint(url="https://api.example.com/v1", kind="api-base", evidence="README")],
    )
    p = export_json([d], tmp_path / "out.json")
    payload = json.loads(p.read_text())
    assert payload["schema"] == "raven-discovery-export-v1"
    assert payload["discoveries"][0]["source_url"] == "https://github.com/u/r"
    assert payload["discoveries"][0]["candidate_endpoints"][0]["url"] == "https://api.example.com/v1"

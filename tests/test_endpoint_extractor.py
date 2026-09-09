from raven_targeter.core.endpoint_extractor import extract_candidate_endpoints


def test_extracts_api_endpoints_and_skips_github_and_private_ip():
    text = """
    API_BASE_URL=https://api.example.com/v1
    docs https://api.example.com/v1/models
    repo https://github.com/u/r
    local http://127.0.0.1:8000/v1
    """
    eps = extract_candidate_endpoints(text, source_file="README")
    urls = {e.url for e in eps}
    assert "https://api.example.com/v1" in urls
    assert "https://api.example.com/v1/models" in urls
    assert not any("github.com" in u for u in urls)
    assert not any("127.0.0.1" in u for u in urls)

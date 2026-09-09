from raven_targeter.config.credential_store import SecureCredentialStore


class FakeKeyring:
    def __init__(self):
        self.data = {}

    def get_password(self, service_name, username):
        return self.data.get((service_name, username))

    def set_password(self, service_name, username, password):
        self.data[(service_name, username)] = password

    def delete_password(self, service_name, username):
        self.data.pop((service_name, username), None)


def test_credentials_round_trip_without_plaintext_config():
    backend = FakeKeyring()
    store = SecureCredentialStore(backend)
    store.set_github_token("github-secret")
    store.set_search_api_key("search-secret")
    assert store.get_github_token() == "github-secret"
    assert store.get_search_api_key() == "search-secret"
    store.clear_github_token()
    store.clear_search_api_key()
    assert store.get_github_token() is None
    assert store.get_search_api_key() is None

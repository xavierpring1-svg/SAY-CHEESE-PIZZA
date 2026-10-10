import io
import json
import urllib.error
import urllib.parse
import urllib.request

import pytest

from jarvis import knowledge


class Response(io.BytesIO):
    def __init__(self, content, url=knowledge.API_URL, headers=None):
        super().__init__(content)
        self.url = url
        self.headers = headers if headers is not None else {
            "Content-Length": str(len(content)), "Content-Type": "application/json; charset=utf-8",
        }

    def geturl(self):
        return self.url


def serve(monkeypatch, *data):
    responses = iter(data)
    requests = []

    def opened(request, timeout):
        requests.append(request)
        assert timeout == knowledge.TIMEOUT
        return Response(json.dumps(next(responses)).encode())

    monkeypatch.setattr(knowledge, "_open", opened)
    return requests


def page(title="Café", extract="A café serves drinks and food.", **kwargs):
    return {"query": {"pages": [{"title": title, "extract": extract, **kwargs}]}}


def test_exact_topic_is_grounded_and_cited_without_searching(monkeypatch):
    requests = serve(monkeypatch, page())
    answer = knowledge.lookup(" Café ")
    assert answer == "Café. A café serves drinks and food.\nSource: https://en.wikipedia.org/wiki/Caf%C3%A9"
    assert len(requests) == 1
    params = urllib.parse.parse_qs(urllib.parse.urlsplit(requests[0].full_url).query)
    assert params["titles"] == ["Café"]
    assert params["explaintext"] == ["1"]
    assert requests[0].get_header("Accept") == "application/json"
    assert requests[0].get_header("User-agent") == knowledge.USER_AGENT


def test_unmatched_topic_uses_labelled_search_result(monkeypatch):
    requests = serve(
        monkeypatch, page(missing=True),
        {"query": {"search": [{"title": "Albert Einstein"}]}},
        page("Albert Einstein", "Albert Einstein was a physicist."),
    )
    answer = knowledge.lookup("Einstein physicist biography")
    assert answer.startswith("Closest encyclopedia match: Albert Einstein. Albert Einstein was")
    assert answer.endswith("https://en.wikipedia.org/wiki/Albert_Einstein")
    assert len(requests) == 3


def test_query_metacharacters_are_encoded_and_remain_a_single_topic(monkeypatch):
    requests = serve(monkeypatch, page("A literal topic"))
    knowledge.lookup("Café | 東京 & action=delete")
    params = urllib.parse.parse_qs(urllib.parse.urlsplit(requests[0].full_url).query)
    assert params["action"] == ["query"]
    assert params["titles"] == ["\x1fCafé | 東京 & action=delete"]


def test_source_url_is_constructed_from_title_and_never_remote_link(monkeypatch):
    serve(monkeypatch, page("Two words / 東京", fullurl="https://evil.test/private"))
    answer = knowledge.lookup("Two words")
    assert answer.endswith("https://en.wikipedia.org/wiki/Two_words_%2F_%E6%9D%B1%E4%BA%AC")
    assert "evil.test" not in answer


@pytest.mark.parametrize("title", [None, "", "\x00\x1b", "x" * 301])
def test_invalid_article_title_cannot_become_a_source(monkeypatch, title):
    serve(monkeypatch, page(title))
    with pytest.raises(RuntimeError, match="incomplete"):
        knowledge.lookup("science")


def test_ambiguous_topic_asks_for_specific_meaning(monkeypatch):
    requests = serve(monkeypatch, page("Mercury", "Unhelpful choices", pageprops={"disambiguation": ""}))
    answer = knowledge.lookup("Mercury")
    assert "several meanings" in answer and "which one" in answer
    assert "Unhelpful choices" not in answer
    assert "https://en.wikipedia.org/wiki/Mercury" in answer
    assert len(requests) == 1


def test_no_search_result_does_not_invent_information(monkeypatch):
    serve(monkeypatch, page(missing=True), {"query": {"search": []}})
    assert "couldn't find an encyclopedia article" in knowledge.lookup("a completely unknown subject")


def test_missing_fallback_article_is_reported(monkeypatch):
    serve(monkeypatch, page(missing=True), {"query": {"search": [{"title": "Old article"}]}}, page(missing=True))
    assert "couldn't find a readable encyclopedia article" in knowledge.lookup("old topic")


def test_article_with_no_extract_still_provides_source(monkeypatch):
    serve(monkeypatch, page(extract=""))
    answer = knowledge.lookup("Café")
    assert "no short encyclopedia summary" in answer
    assert "Source: https://en.wikipedia.org/wiki/Caf%C3%A9" in answer


def test_text_is_bounded_and_nonprinting_characters_are_removed(monkeypatch):
    serve(monkeypatch, page("A topic", "An article\x00\x1b\n\t" + "word " * 1000))
    answer = knowledge.lookup("A topic")
    assert "\x00" not in answer and "\x1b" not in answer and "\t" not in answer
    assert "…\nSource: " in answer
    assert len(answer) < knowledge.SUMMARY_MAX_CHARS + 100


@pytest.mark.parametrize("query", [None, "", "  ", "a\nb", "topic\tvalue", "x" * 301, "bad\0", "\ud800"])
def test_invalid_query_never_requests_network(monkeypatch, query):
    monkeypatch.setattr(knowledge, "_open", lambda *args, **kwargs: pytest.fail("network called"))
    with pytest.raises(ValueError):
        knowledge.lookup(query)


@pytest.mark.parametrize("url", [
    "http://en.wikipedia.org/wiki/Test", "https://en.wikipedia.org.evil.test/wiki/Test",
    "https://user:secret@en.wikipedia.org/wiki/Test", "https://en.wikipedia.org:444/wiki/Test",
    "https://localhost/wiki/Test", "https://127.0.0.1/wiki/Test", "file:///tmp/private",
    "https://fr.wikipedia.org/wiki/Test", "https://en.wikipedia.org:invalid/",
])
def test_redirects_cannot_access_unapproved_destinations(url):
    request = urllib.request.Request(knowledge.API_URL)
    with pytest.raises(RuntimeError, match="unexpected server"):
        knowledge._WikipediaRedirects().redirect_request(request, None, 302, "Moved", {}, url)


def test_https_redirect_within_wikipedia_is_allowed():
    request = urllib.request.Request(knowledge.API_URL)
    redirected = knowledge._WikipediaRedirects().redirect_request(
        request, None, 302, "Moved", {}, "https://en.wikipedia.org:443/w/api.php?redirected=1",
    )
    assert redirected.full_url.startswith("https://en.wikipedia.org:443/")


def test_final_response_domain_is_rechecked(monkeypatch):
    monkeypatch.setattr(knowledge, "_open", lambda *args, **kwargs: Response(b"{}", "https://evil.test"))
    with pytest.raises(RuntimeError, match="unexpected server"):
        knowledge.lookup("science")


@pytest.mark.parametrize("body,headers", [
    (b"{}", {"Content-Length": str(knowledge.JSON_MAX_BYTES + 1), "Content-Type": "application/json"}),
    (b"x" * (knowledge.JSON_MAX_BYTES + 1), {"Content-Type": "application/json"}),
    (b"{}", {"Content-Length": "not a number", "Content-Type": "application/json"}),
    (b"{}", {"Content-Length": "-1", "Content-Type": "application/json"}),
    (b"<html>proxy error</html>", {"Content-Type": "text/html"}),
    (b"invalid json", {"Content-Type": "application/json"}),
    (b"\xff", {"Content-Type": "application/json"}),
    (b"[]", {"Content-Type": "application/json"}),
    (b'{"error":{"info":"wrong query"}}', {"Content-Type": "application/json"}),
])
def test_invalid_or_oversized_responses_are_rejected(monkeypatch, body, headers):
    monkeypatch.setattr(knowledge, "_open", lambda *args, **kwargs: Response(body, headers=headers))
    with pytest.raises(RuntimeError):
        knowledge.lookup("science")


@pytest.mark.parametrize("data", [{}, {"query": {}}, {"query": {"pages": []}}, {"query": {"pages": [None]}}])
def test_incomplete_responses_do_not_become_made_up_answers(monkeypatch, data):
    serve(monkeypatch, data)
    with pytest.raises(RuntimeError, match="incomplete"):
        knowledge.lookup("science")


@pytest.mark.parametrize("error", [urllib.error.URLError("blocked"), TimeoutError("slow"), OSError("offline")])
def test_connection_failures_offer_honest_retry_guidance(monkeypatch, error):
    def blocked(*args, **kwargs):
        raise error

    monkeypatch.setattr(knowledge, "_open", blocked)
    with pytest.raises(RuntimeError, match="couldn't reach Wikipedia"):
        knowledge.lookup("science")

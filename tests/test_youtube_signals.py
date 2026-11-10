"""Video counters and comments through a FAKE transport: hidden counters stay None (never 0), no dislike field, no commenter identity, disabled comments give None."""
from ingestion.youtube import api
from ingestion.youtube.api import YouTubeApiError

KEY = "SECRET-KEY-VALUE"


def fake(*responses):
    queue = list(responses)

    def get(url, params, headers):
        r = queue.pop(0)
        if isinstance(r, Exception):
            raise r
        return r
    return get


def test_statistics_keep_a_hidden_counter_as_none_and_have_no_dislikes():
    g = fake({"items": [{"id": "AAAAAAAAAAA", "snippet": {"publishedAt": "2025-03-28T10:00:00Z"}, "statistics": {"viewCount": "1200", "likeCount": "40", "commentCount": "7"}},
                        {"id": "BBBBBBBBBBB", "snippet": {"publishedAt": "2020-01-02T00:00:00Z"}, "statistics": {"viewCount": "50"}}]})
    out = api.video_statistics(["AAAAAAAAAAA", "BBBBBBBBBBB"], api_key=KEY, get=g)
    assert out["AAAAAAAAAAA"] == {"views": 1200, "likes": 40, "comments": 7, "published": "2025-03-28"}
    assert out["BBBBBBBBBBB"]["likes"] is None and out["BBBBBBBBBBB"]["comments"] is None          # hidden or disabled is not zero
    assert not any("dislike" in k for v in out.values() for k in v)


def test_comments_carry_text_and_likes_only():
    item = {"snippet": {"totalReplyCount": 2, "topLevelComment": {"snippet": {"textDisplay": "which version is this?", "likeCount": 5, "publishedAt": "2025-04-01T00:00:00Z",
                                                                             "authorDisplayName": "Someone", "authorChannelId": {"value": "UC123"}}}}}
    out = api.top_comments("AAAAAAAAAAA", api_key=KEY, get=fake({"items": [item]}))
    assert out == [{"text": "which version is this?", "likes": 5, "published": "2025-04-01", "replies": 2}]


def test_disabled_comments_return_none_and_other_errors_still_raise():
    assert api.top_comments("AAAAAAAAAAA", api_key=KEY, get=fake(YouTubeApiError("HTTP 403: commentsDisabled"))) is None
    try:
        api.top_comments("AAAAAAAAAAA", api_key=KEY, get=fake(YouTubeApiError("HTTP 500: backend")))
    except YouTubeApiError:
        return
    raise AssertionError("a server error must not be reported as 'comments disabled'")

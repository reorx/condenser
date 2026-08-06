"""Behavior tests for the X reader — the adapter between probe-config and xbird.

The X API is never touched: ``resolve_credentials`` and ``TwitterClient`` are
replaced by fakes that hand back real ``xbird.types`` models, so the assertions
about the pushed payload are made against the library's genuine serialization
rather than a hand-written imitation of it.
"""

import pytest
from xbird.types import (
    CurrentUser,
    CurrentUserSuccess,
    OperationFailure,
    TweetAuthor,
    TweetData,
    TweetsPageFailure,
    TweetsPageSuccess,
    TwitterUser,
    UserLookupSuccess,
    UsersPageFailure,
    UsersPageSuccess,
)

from condenser_probe import xsource

HOME = {'channel_id': 'foryou', 'kind': 'home', 'handle': None, 'n': 50}
FOLLOWING = {'channel_id': 'following', 'kind': 'following', 'handle': None, 'n': 50}
USER = {'channel_id': 'novoreorx', 'kind': 'user', 'handle': 'novoreorx', 'n': 10}


def tweet(tweet_id, **kwargs):
    return TweetData(id=str(tweet_id), text=f't{tweet_id}', author=TweetAuthor(username='a', name='A'), **kwargs)


def user(user_id, username):
    return TwitterUser(id=str(user_id), username=username, name=username.title())


class FakeClient:
    """Stands in for xbird's TwitterClient: canned results, recorded calls."""

    def __init__(self, **results):
        self.results = results
        self.calls = []
        self.closed = False

    def _answer(self, name, *args, **kwargs):
        self.calls.append((name, args, kwargs))
        answer = self.results.get(name)
        if isinstance(answer, list):  # one canned result per successive call
            return answer.pop(0)
        return answer

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.closed = True

    def get_home_timeline(self, count):
        return self._answer('get_home_timeline', count)

    def get_home_latest_timeline(self, count):
        return self._answer('get_home_latest_timeline', count)

    def get_user_id_by_username(self, username):
        return self._answer('get_user_id_by_username', username)

    def get_user_tweets_paged(self, user_id, limit):
        return self._answer('get_user_tweets_paged', user_id, limit)

    def get_current_user(self):
        return self._answer('get_current_user')

    def get_following(self, user_id, count, cursor):
        return self._answer('get_following', user_id, count, cursor)


@pytest.fixture
def fake(monkeypatch):
    """Install a FakeClient and pretend credentials resolved; yields a setter."""
    holder = {}

    monkeypatch.setattr(xsource, 'resolve_credentials', lambda: object())
    monkeypatch.setattr(xsource, 'TwitterClient', lambda cookies, **kwargs: holder['client'])
    monkeypatch.setattr(xsource.time, 'sleep', lambda seconds: None)

    def install(**results):
        holder['client'] = FakeClient(**results)
        return holder['client']

    return install


# --- feeds --------------------------------------------------------------------


def test_each_feed_kind_reads_its_own_timeline(fake):
    """The three feeds are three different X endpoints; For You and Following
    share one (HomeTimeline vs HomeLatestTimeline) and must not be swapped."""
    client = fake(get_home_timeline=TweetsPageSuccess(tweets=[tweet(1)]))
    assert [t['id'] for t in xsource.fetch_feed(HOME)] == ['1']
    assert client.calls == [('get_home_timeline', (50,), {})]

    client = fake(get_home_latest_timeline=TweetsPageSuccess(tweets=[tweet(2)]))
    xsource.fetch_feed(FOLLOWING)
    assert client.calls == [('get_home_latest_timeline', (50,), {})]


def test_an_account_feed_resolves_its_handle_first(fake):
    """probe-config carries the handle (that is the subscription key), but the
    timeline endpoint takes a numeric user id."""
    client = fake(
        get_user_id_by_username=UserLookupSuccess(user_id='42', username='novoreorx', name='Reorx'),
        get_user_tweets_paged=TweetsPageSuccess(tweets=[tweet(3)]),
    )
    assert [t['id'] for t in xsource.fetch_feed(USER)] == ['3']
    assert client.calls == [
        ('get_user_id_by_username', ('novoreorx',), {}),
        ('get_user_tweets_paged', ('42', 10), {}),
    ]


def test_a_feed_without_a_count_falls_back_to_a_default(fake):
    client = fake(get_home_timeline=TweetsPageSuccess(tweets=[]))
    xsource.fetch_feed({'channel_id': 'foryou', 'kind': 'home'})
    assert client.calls == [('get_home_timeline', (xsource.DEFAULT_COUNT,), {})]


def test_unusable_feeds_are_rejected(fake):
    fake()
    with pytest.raises(xsource.XSourceError, match='unknown feed kind'):
        xsource.fetch_feed({'channel_id': 'x', 'kind': 'lists'})
    with pytest.raises(xsource.XSourceError, match='without a handle'):
        xsource.fetch_feed({'kind': 'user', 'n': 10})


# --- errors are values in xbird, and must become failures here ------------------


def test_a_failed_fetch_raises_instead_of_reading_as_an_empty_feed(fake):
    """xbird returns remote failures as values. Passing one through as ``[]``
    would report the round as OK and hide a dead X session for good."""
    fake(get_home_timeline=TweetsPageFailure(error='HTTP 401'))
    with pytest.raises(xsource.XSourceError, match='HTTP 401'):
        xsource.fetch_feed(HOME)


def test_a_failed_handle_lookup_never_reaches_the_timeline_call(fake):
    client = fake(get_user_id_by_username=OperationFailure(error='User not found'))
    with pytest.raises(xsource.XSourceError, match='User not found'):
        xsource.fetch_feed(USER)
    assert [name for name, _, _ in client.calls] == ['get_user_id_by_username']


def test_missing_credentials_are_reported_as_a_source_failure(monkeypatch):
    monkeypatch.setattr(xsource, 'resolve_credentials', lambda: None)
    with pytest.raises(xsource.XSourceError, match='no X credentials'):
        xsource.fetch_feed(HOME)


def test_the_client_is_closed_even_when_the_feed_fails(fake):
    """It owns an httpx connection pool and `watch` runs for days."""
    client = fake(get_home_timeline=TweetsPageSuccess(tweets=[]))
    xsource.fetch_feed(HOME)
    assert client.closed

    client = fake(get_home_timeline=TweetsPageFailure(error='boom'))
    with pytest.raises(xsource.XSourceError):
        xsource.fetch_feed(HOME)
    assert client.closed


# --- the wire shape is a contract with the server -------------------------------


def test_tweets_are_serialized_the_way_the_server_parses_them(fake):
    """``condenser.x.parse_tweet`` reads these camelCase keys and archives the
    whole entry as ``raw``; the seen cache keys off ``id``. So this shape is the
    contract, not an implementation detail of whoever fetched the tweet."""
    quoted = tweet(9, created_at='Wed Jul 30 10:00:00 +0000 2026')
    payload = tweet(
        7,
        created_at='Wed Jul 30 12:00:00 +0000 2026',
        author_id='42',
        like_count=3,
        quoted_tweet=quoted,
    )
    fake(get_home_timeline=TweetsPageSuccess(tweets=[payload]))

    (entry,) = xsource.fetch_feed(HOME)
    assert entry['id'] == '7'  # a string: snowflake ids exceed JS's safe range
    assert entry['createdAt'] == 'Wed Jul 30 12:00:00 +0000 2026'
    assert entry['author'] == {'username': 'a', 'name': 'A'}
    assert entry['authorId'] == '42'
    assert entry['likeCount'] == 3
    assert entry['quotedTweet']['id'] == '9'
    assert 'media' not in entry  # absent, not null — matches the CLI's --json


# --- the follow list ------------------------------------------------------------


def test_the_follow_list_is_crawled_across_pages(fake):
    """One page caps well below a real follow list, so this pages to the end and
    deduplicates — the same account can repeat across cursor pages."""
    client = fake(
        get_current_user=CurrentUserSuccess(user=CurrentUser(id='1', username='me', name='Me')),
        get_following=[
            UsersPageSuccess(users=[user(10, 'alice'), user(11, 'bob')], next_cursor='c1'),
            UsersPageSuccess(users=[user(11, 'bob'), user(12, 'carol')], next_cursor=None),
        ],
    )
    users = xsource.fetch_following_users()

    assert [u['username'] for u in users] == ['alice', 'bob', 'carol']
    assert [kwargs or args for name, args, kwargs in client.calls if name == 'get_following'] == [
        ('1', xsource.FOLLOWING_PAGE_SIZE, None),
        ('1', xsource.FOLLOWING_PAGE_SIZE, 'c1'),
    ]


def test_a_repeated_cursor_ends_the_crawl(fake):
    """X hands back the cursor it was given once the list is exhausted; without
    this the loop would spin until the page cap."""
    fake(
        get_current_user=CurrentUserSuccess(user=CurrentUser(id='1', username='me', name='Me')),
        get_following=[
            UsersPageSuccess(users=[user(10, 'alice')], next_cursor='c1'),
            UsersPageSuccess(users=[user(11, 'bob')], next_cursor='c1'),
            UsersPageSuccess(users=[user(12, 'carol')], next_cursor='c2'),
        ],
    )
    assert [u['username'] for u in xsource.fetch_following_users()] == ['alice', 'bob']


def test_a_partial_follow_crawl_is_never_returned(fake):
    """The server *replaces* the list wholesale and drops Following tweets whose
    author is missing from it — so half a list is worse than none at all: it
    would silently discard the missing accounts' tweets as advertising."""
    fake(
        get_current_user=CurrentUserSuccess(user=CurrentUser(id='1', username='me', name='Me')),
        get_following=[
            UsersPageSuccess(users=[user(10, 'alice')], next_cursor='c1'),
            UsersPageFailure(error='HTTP 429'),
        ],
    )
    with pytest.raises(xsource.XSourceError, match='HTTP 429'):
        xsource.fetch_following_users()


def test_the_crawl_stops_at_its_page_cap(fake):
    """A cursor chain that never ends must not page forever."""
    fake(
        get_current_user=CurrentUserSuccess(user=CurrentUser(id='1', username='me', name='Me')),
        get_following=[UsersPageSuccess(users=[user(n, f'u{n}')], next_cursor=f'c{n}') for n in range(100)],
    )
    assert len(xsource.fetch_following_users(max_pages=3)) == 3


def test_followed_accounts_carry_what_the_server_keys_them_by(fake):
    """``condenser.x.parse_following_users`` needs username + id + name."""
    fake(
        get_current_user=CurrentUserSuccess(user=CurrentUser(id='1', username='me', name='Me')),
        get_following=[UsersPageSuccess(users=[user(10, 'alice')], next_cursor=None)],
    )
    (entry,) = xsource.fetch_following_users()
    assert entry['id'] == '10' and entry['username'] == 'alice' and entry['name'] == 'Alice'


# --- check --------------------------------------------------------------------


def test_check_auth_reports_the_logged_in_account(fake):
    fake(get_current_user=CurrentUserSuccess(user=CurrentUser(id='1', username='novoreorx', name='Reorx')))
    assert xsource.check_auth() == '@novoreorx (Reorx)'


def test_check_auth_fails_loudly_on_a_dead_session(fake):
    fake(get_current_user=OperationFailure(error='HTTP 401'))
    with pytest.raises(xsource.XSourceError, match='HTTP 401'):
        xsource.check_auth()

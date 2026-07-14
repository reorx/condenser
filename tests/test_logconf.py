"""Behavior tests for JSON log output (CONDENSER_LOG_FORMAT=json).

Production requirement (deploy workspace rule): container stdout logs must be
one JSON object per line so `grep` hits whole entries and `jq` can filter by
field. The switch is the CONDENSER_LOG_FORMAT env var: unset/"pretty" keeps the
existing human-readable uvicorn-style lines, "json" swaps every formatter
(uvicorn server, uvicorn access, named app loggers) for JSON.
"""

import json
import logging

import pytest

from condenser import logconf


def make_record(name='condenser.ingest', msg='hello %s', args=('world',), exc_info=None):
    return logging.LogRecord(
        name=name,
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg=msg,
        args=args,
        exc_info=exc_info,
    )


def parse_single_json_line(text):
    """The whole point: one entry == one line of valid JSON."""
    assert '\n' not in text
    return json.loads(text)


class TestJSONFormatter:
    def test_entry_is_single_line_json_with_core_fields(self):
        out = logconf.JSONFormatter().format(make_record())
        entry = parse_single_json_line(out)
        assert entry['level'] == 'INFO'
        assert entry['logger'] == 'condenser.ingest'
        assert entry['msg'] == 'hello world'
        assert entry['time']

    def test_exception_is_embedded_in_the_same_line(self):
        try:
            raise ValueError('boom')
        except ValueError:
            import sys

            record = make_record(msg='failed', args=(), exc_info=sys.exc_info())
        entry = parse_single_json_line(logconf.JSONFormatter().format(record))
        assert 'ValueError: boom' in entry['exc']

    def test_non_ascii_survives_unescaped(self):
        out = logconf.JSONFormatter().format(make_record(msg='频道 %s', args=('新闻',)))
        assert parse_single_json_line(out)['msg'] == '频道 新闻'


class TestAccessJSONFormatter:
    def test_uvicorn_access_args_become_structured_fields(self):
        # uvicorn.access records carry (client_addr, method, full_path, http_version, status_code)
        record = make_record(
            name='uvicorn.access',
            msg='%s - "%s %s HTTP/%s" %d',
            args=('172.24.0.1:47820', 'GET', '/api/timeline', '1.1', 200),
        )
        entry = parse_single_json_line(logconf.AccessJSONFormatter().format(record))
        assert entry['client_addr'] == '172.24.0.1:47820'
        assert entry['method'] == 'GET'
        assert entry['path'] == '/api/timeline'
        assert entry['status'] == 200
        assert entry['logger'] == 'uvicorn.access'


class TestConfigureLogging:
    @pytest.fixture(autouse=True)
    def restore_logging(self):
        yield
        # put the default (pretty) config back so other tests see the status quo
        logconf.configure_logging()

    def _handler_formatters(self):
        root_fmt = logging.getLogger().handlers[0].formatter
        access_fmt = logging.getLogger('uvicorn.access').handlers[0].formatter
        return root_fmt, access_fmt

    def test_json_mode_installs_json_formatters_everywhere(self, monkeypatch):
        monkeypatch.setenv('CONDENSER_LOG_FORMAT', 'json')
        logconf.configure_logging()
        root_fmt, access_fmt = self._handler_formatters()
        assert isinstance(root_fmt, logconf.JSONFormatter)
        assert isinstance(access_fmt, logconf.AccessJSONFormatter)

    def test_default_stays_pretty(self, monkeypatch):
        monkeypatch.delenv('CONDENSER_LOG_FORMAT', raising=False)
        logconf.configure_logging()
        root_fmt, access_fmt = self._handler_formatters()
        assert not isinstance(root_fmt, logconf.JSONFormatter)
        assert not isinstance(access_fmt, logconf.AccessJSONFormatter)

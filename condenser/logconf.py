"""Logging config that puts timestamps on every line (app, uvicorn, telethon).

``logging.basicConfig`` only touches the root logger, so uvicorn's own loggers
(``uvicorn`` / ``uvicorn.access`` — they ship their own handlers + formatters and
``propagate=False``) keep printing timestamp-less ``INFO:     ...`` lines. We instead
apply a full ``dictConfig`` modeled on uvicorn's default, adding ``asctime`` to all
three formatters. Importing this module after uvicorn has configured its own logging
(which is the case for both ``uvicorn ...`` CLI and ``python -m condenser``) lets ours
win, since ``dictConfig`` reconfigures the already-registered uvicorn loggers.

``CONDENSER_LOG_FORMAT=json`` swaps every formatter for one-JSON-object-per-line
output (production containers need this so grep hits whole entries and jq can
filter by field); unset/anything else keeps the pretty human-readable lines.
"""

import json
import logging.config
import os

_DATEFMT = '%Y-%m-%d %H:%M:%S'


class JSONFormatter(logging.Formatter):
    """One log entry per line as a JSON object: time/level/logger/msg (+exc)."""

    def format(self, record: logging.LogRecord) -> str:
        entry = self.entry(record)
        if record.exc_info:
            entry['exc'] = self.formatException(record.exc_info)
        return json.dumps(entry, ensure_ascii=False)

    def entry(self, record: logging.LogRecord) -> dict:
        return {
            'time': self.formatTime(record, _DATEFMT),
            'level': record.levelname,
            'logger': record.name,
            'msg': record.getMessage(),
        }


class AccessJSONFormatter(JSONFormatter):
    """uvicorn.access records carry (client_addr, method, full_path, http_version,
    status_code) in ``args``; expose them as structured fields."""

    def entry(self, record: logging.LogRecord) -> dict:
        entry = super().entry(record)
        client_addr, method, path, http_version, status = record.args
        entry.update(
            {
                'client_addr': client_addr,
                'method': method,
                'path': path,
                'http_version': http_version,
                'status': status,
            }
        )
        return entry


_JSON_FORMATTERS = {
    'default': {'()': JSONFormatter},
    'access': {'()': AccessJSONFormatter},
    'named': {'()': JSONFormatter},
}

LOGGING_CONFIG = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        # uvicorn server logs (startup/shutdown/errors): no logger name, like uvicorn's default.
        'default': {
            '()': 'uvicorn.logging.DefaultFormatter',
            'fmt': '%(asctime)s %(levelprefix)s %(message)s',
            'datefmt': _DATEFMT,
        },
        # uvicorn access logs.
        'access': {
            '()': 'uvicorn.logging.AccessFormatter',
            'fmt': '%(asctime)s %(levelprefix)s %(client_addr)s - "%(request_line)s" %(status_code)s',
            'datefmt': _DATEFMT,
        },
        # everything else (condenser.*, telethon.*): include the logger name.
        'named': {
            '()': 'uvicorn.logging.DefaultFormatter',
            'fmt': '%(asctime)s %(levelprefix)s %(name)s: %(message)s',
            'datefmt': _DATEFMT,
        },
    },
    'handlers': {
        'default': {'formatter': 'default', 'class': 'logging.StreamHandler', 'stream': 'ext://sys.stderr'},
        'access': {'formatter': 'access', 'class': 'logging.StreamHandler', 'stream': 'ext://sys.stdout'},
        'named': {'formatter': 'named', 'class': 'logging.StreamHandler', 'stream': 'ext://sys.stderr'},
    },
    'loggers': {
        'uvicorn': {'handlers': ['default'], 'level': 'INFO', 'propagate': False},
        'uvicorn.error': {'level': 'INFO'},
        'uvicorn.access': {'handlers': ['access'], 'level': 'INFO', 'propagate': False},
    },
    'root': {'handlers': ['named'], 'level': 'INFO'},
}


def configure_logging() -> None:
    config = LOGGING_CONFIG
    if os.getenv('CONDENSER_LOG_FORMAT') == 'json':
        config = {**LOGGING_CONFIG, 'formatters': _JSON_FORMATTERS}
    logging.config.dictConfig(config)

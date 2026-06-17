"""Logging config that puts timestamps on every line (app, uvicorn, telethon).

``logging.basicConfig`` only touches the root logger, so uvicorn's own loggers
(``uvicorn`` / ``uvicorn.access`` — they ship their own handlers + formatters and
``propagate=False``) keep printing timestamp-less ``INFO:     ...`` lines. We instead
apply a full ``dictConfig`` modeled on uvicorn's default, adding ``asctime`` to all
three formatters. Importing this module after uvicorn has configured its own logging
(which is the case for both ``uvicorn ...`` CLI and ``python -m condenser``) lets ours
win, since ``dictConfig`` reconfigures the already-registered uvicorn loggers.
"""

import logging.config

_DATEFMT = '%Y-%m-%d %H:%M:%S'

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
    logging.config.dictConfig(LOGGING_CONFIG)

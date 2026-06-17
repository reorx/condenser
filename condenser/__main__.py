"""`python -m condenser` / `condenser` entry point."""

import os

import uvicorn


def main() -> None:
    uvicorn.run(
        'condenser.app:create_app',
        factory=True,
        host=os.getenv('CONDENSER_HOST', '0.0.0.0'),
        port=int(os.getenv('CONDENSER_PORT', '8792')),
    )


if __name__ == '__main__':
    main()

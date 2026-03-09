"""Emet — Investigative Journalism Agentic Framework.

Built on the Kintsugi self-repairing harness architecture, adapted for
investigative journalism workflows on the FollowTheMoney data ecosystem.

Target platforms: OpenAleph, Aleph Pro (API), OpenSanctions/yente.
"""

import sys

if sys.version_info < (3, 11):
    raise RuntimeError(
        f"Emet requires Python 3.11+. You have Python {sys.version}. "
        f"Install a newer version: https://www.python.org/downloads/"
    )

# Load .env file into os.environ so all code paths (os.getenv, pydantic
# Settings, federation config) see the same values. Without this, keys
# in .env are invisible to os.getenv() on Windows and in environments
# that don't auto-source .env files.
from pathlib import Path as _Path
import os as _os

def _load_dotenv() -> None:
    """Minimal .env loader — no external dependency required."""
    for env_path in [_Path(".env"), _Path(__file__).parent.parent / ".env"]:
        if env_path.exists():
            for line in env_path.read_text().splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, value = line.partition("=")
                key = key.strip()
                value = value.strip().strip("'\"")
                if key and key not in _os.environ:
                    _os.environ[key] = value
            break

_load_dotenv()

__version__ = "0.1.0"

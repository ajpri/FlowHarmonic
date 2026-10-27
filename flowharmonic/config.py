"""Read local, administrator-owned configuration. Never rewrite it at startup."""
import os
from urllib.parse import urlsplit
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10
    import tomli as tomllib


def load_config():
    path = Path(os.environ.get("FLOWHARMONIC_CONFIG", "/etc/flowharmonic/config.toml"))
    data = tomllib.loads(path.read_text()) if path.exists() else {}
    unknown = set(data) - {"name", "host", "port", "snapcast_url", "snapcast_stream_port"}
    if unknown:
        raise ValueError(f"Unknown settings: {', '.join(sorted(unknown))}")
    config = {"name": "FlowHarmonic", "host": "0.0.0.0", "port": 8080, "snapcast_url": "tcp://127.0.0.1:1705", **data}
    if not isinstance(config["name"], str) or not 1 <= len(config["name"].strip()) <= 80:
        raise ValueError("name must contain 1–80 characters")
    if not isinstance(config["host"], str) or not config["host"]:
        raise ValueError("host must be a nonempty address")
    if type(config["port"]) is not int or not 1 <= config["port"] <= 65535:
        raise ValueError("port must be between 1 and 65535")
    if type(config.get('snapcast_stream_port',1704)) is not int or not 1 <= config.get('snapcast_stream_port',1704) <= 65535:
        raise ValueError('snapcast_stream_port must be between 1 and 65535')
    if not isinstance(config['snapcast_url'], str):
        raise ValueError('snapcast_url must be a URL')
    url = urlsplit(config['snapcast_url'])
    if (url.scheme not in ('tcp', 'http', 'https') or not url.hostname or url.username or
            url.password or url.fragment or url.query or
            (url.scheme == 'tcp' and url.path not in ('', '/'))):
        raise ValueError('snapcast_url must be tcp://host:port or http(s)://host:port/jsonrpc, without credentials')
    if url.port is not None and not 1 <= url.port <= 65535:
        raise ValueError('snapcast_url port must be between 1 and 65535')
    return config


def data_directory():
    return Path(os.environ.get("FLOWHARMONIC_DATA_DIR", "/var/lib/flowharmonic"))

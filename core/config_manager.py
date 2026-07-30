"""
Centralized configuration manager with persistence and validation.
"""
import json
import os
from typing import Any, Dict, List, Optional

DEFAULT_CONFIG: Dict[str, Any] = {
    "recipient_list_file": "",
    "links_file": "",
    "sender_name": "Support Team",
    "subject": "Hello %FIRSTNAME%",
    "message_body": "",
    "message_body_file": "",
    "message_body_type": "html",
    "smtp_servers": [],
    "use_sock": False,
    "socks5_proxies": [],
    "proxy_rotation": "round_robin",      # round_robin | random | weighted
    "smtp_rotation": "weighted",          # round_robin | weighted | random
    "num_threads": 50,
    "max_retries": 3,
    "max_errors_before_stop": 100,
    "connection_timeout": 15,
    "max_reuse": 200,
    "max_age": 600,
    "max_conns_per_server": 10,
    "html2pdf": False,
    "html2pdf_file": "",
    "html2pdf_attachment_name": "document.pdf",
    "wkhtmltopdf_path": "",
    "verify_email": False,
    "test_email": "",
    "use_exchange": False,
    "exchange": {
        "owas": [],
        "sending_delay": 0.05,
    },
    "num_emails_to_send": 0,
}

CONFIG_FILE = "config.json"


class ConfigManager:
    def __init__(self, path: str = CONFIG_FILE):
        self._path = path
        self._config: Dict[str, Any] = {}
        self._reset_to_defaults()
        self.load()

    def _reset_to_defaults(self):
        import copy
        self._config = copy.deepcopy(DEFAULT_CONFIG)

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def load(self, path: Optional[str] = None) -> bool:
        path = path or self._path
        if not os.path.exists(path):
            return False
        try:
            with open(path, "r", encoding="utf-8") as f:
                loaded = json.load(f)
            self._deep_update(self._config, loaded)
            self._path = path
            return True
        except Exception:
            return False

    def save(self, path: Optional[str] = None) -> bool:
        path = path or self._path
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(self._config, f, indent=2, ensure_ascii=False)
            return True
        except Exception:
            return False

    # ------------------------------------------------------------------
    # Accessors
    # ------------------------------------------------------------------

    def get(self, key: str, default: Any = None) -> Any:
        return self._config.get(key, default)

    def set(self, key: str, value: Any):
        self._config[key] = value

    def get_all(self) -> Dict[str, Any]:
        import copy
        return copy.deepcopy(self._config)

    def update(self, data: Dict[str, Any]):
        self._deep_update(self._config, data)

    # ------------------------------------------------------------------
    # SMTP helpers
    # ------------------------------------------------------------------

    def get_smtp_servers(self) -> List[Dict[str, Any]]:
        return self._config.get("smtp_servers", [])

    def set_smtp_servers(self, servers: List[Dict[str, Any]]):
        self._config["smtp_servers"] = servers

    def add_smtp_server(self, server: Dict[str, Any]):
        servers = self.get_smtp_servers()
        servers.append(server)
        self.set_smtp_servers(servers)

    def remove_smtp_server(self, index: int):
        servers = self.get_smtp_servers()
        if 0 <= index < len(servers):
            servers.pop(index)
            self.set_smtp_servers(servers)

    # ------------------------------------------------------------------
    # Proxy helpers
    # ------------------------------------------------------------------

    def get_proxies(self) -> List[Dict[str, Any]]:
        return self._config.get("socks5_proxies", [])

    def set_proxies(self, proxies: List[Dict[str, Any]]):
        self._config["socks5_proxies"] = proxies

    def add_proxy(self, proxy: Dict[str, Any]):
        proxies = self.get_proxies()
        proxies.append(proxy)
        self.set_proxies(proxies)

    def remove_proxy(self, index: int):
        proxies = self.get_proxies()
        if 0 <= index < len(proxies):
            proxies.pop(index)
            self.set_proxies(proxies)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    @staticmethod
    def _deep_update(base: dict, override: dict):
        for k, v in override.items():
            if k in base and isinstance(base[k], dict) and isinstance(v, dict):
                ConfigManager._deep_update(base[k], v)
            else:
                base[k] = v

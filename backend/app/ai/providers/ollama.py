"""Local Ollama provider.

Talks to a model server bound to a private address (default ``127.0.0.1:11434``).
No external service is contacted: the model, the weights and the prompts all stay
inside the deployment.  A base URL that is not loopback is rejected unless the
operator explicitly allows it, so a typo cannot silently ship customer facts to a
third party.
"""

from __future__ import annotations

import ipaddress
import json
import time
import urllib.error
import urllib.parse
import urllib.request

from .base import Generation, ProviderError, ProviderUnavailable


_LOOPBACK_NAMES = {"localhost", "127.0.0.1", "::1", "0.0.0.0", "host.docker.internal"}


def _is_private_host(host: str) -> bool:
    if host in _LOOPBACK_NAMES:
        return True
    try:
        address = ipaddress.ip_address(host)
    except ValueError:

        return "." not in host
    return address.is_loopback or address.is_private


class OllamaProvider:
    name = "ollama"

    def __init__(self, *, base_url: str, model: str, allow_remote: bool = False):
        parsed = urllib.parse.urlparse(base_url)
        if parsed.scheme not in {"http", "https"}:
            raise ValueError("AEZA_AI_BASE_URL must be an http(s) URL")
        host = parsed.hostname or ""
        if not allow_remote and not _is_private_host(host):
            raise ValueError(
                f"AEZA_AI_BASE_URL host {host!r} is not local; set AEZA_AI_ALLOW_REMOTE=1 to override"
            )
        self.base_url = base_url.rstrip("/")
        self.model = model

    def _post(self, path: str, payload: dict, timeout: float) -> dict:
        request = urllib.request.Request(
            f"{self.base_url}{path}",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            raise ProviderError(f"модель вернула HTTP {exc.code}") from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise ProviderUnavailable("локальная модель недоступна") from exc
        except json.JSONDecodeError as exc:
            raise ProviderError("модель вернула неразбираемый ответ") from exc

    def generate(
        self,
        *,
        system: str,
        user: str,
        json_schema: dict | None = None,
        num_ctx: int,
        max_tokens: int,
        temperature: float,
        timeout: float,
    ) -> Generation:
        MAX_USER_CHARS = 2500
        if len(user) > MAX_USER_CHARS:
            import logging
            logging.getLogger("ai.prompt").warning(
                "PROMPT_TRUNCATED user %d -> %d chars", len(user), MAX_USER_CHARS
            )
            user = user[:MAX_USER_CHARS] + "\n[…контекст сокращён…]"
        payload: dict = {
            "model": self.model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "stream": False,
            "think": False,
            "options": {"temperature": temperature, "num_ctx": num_ctx, "num_predict": max_tokens},
        }
        if json_schema is not None:
            payload["format"] = json_schema

        started = time.perf_counter()
        body = self._post("/api/chat", payload, timeout)
        latency_ms = int((time.perf_counter() - started) * 1000)

        message = body.get("message") or {}
        text = message.get("content")
        if not isinstance(text, str) or not text.strip():
            raise ProviderError("модель вернула пустой ответ")
        return Generation(
            text=text,
            model=str(body.get("model") or self.model),
            provider=self.name,
            latency_ms=latency_ms,
            prompt_tokens=body.get("prompt_eval_count"),
            completion_tokens=body.get("eval_count"),
        )

    def health(self, *, timeout: float) -> bool:
        try:
            with urllib.request.urlopen(f"{self.base_url}/api/tags", timeout=timeout):
                return True
        except Exception:
            return False

"""Shared LLM chat helper.

One backend:
  - omniroute            — routes through a local OmniRoute gateway
    (https://omniroute.online, an open-source multi-provider AI router you
    run yourself, typically at http://localhost:20128) via its
    OpenAI-compatible /v1/chat/completions endpoint. Lets scoring +
    tailoring use OmniRoute's free-tier provider pool / auto-fallback.

Both scoring.py and tailor.py call chat() so there's one place that knows
how to reach the configured backend in search.yaml's `llm:` block.
Every failure here returns None rather than raising — callers already treat
"no LLM available" as a soft fallback (keyword score / skip tailoring).
"""
import os
import requests


def available(llm_cfg: dict) -> bool:
    """Whether the configured LLM backend looks usable before we even try."""
    return True


def chat(prompt: str, max_tokens: int, llm_cfg: dict) -> str | None:
    """Return the assistant's reply text, or None if unavailable/failed."""
    return _chat_omniroute(prompt, max_tokens, llm_cfg)


def _chat_omniroute(prompt: str, max_tokens: int, llm_cfg: dict) -> str | None:
    base_url = (
        llm_cfg.get("omniroute_base_url")
        or os.getenv("OMNIROUTE_BASE_URL")
        or "http://localhost:20128/v1"
    ).rstrip("/")
    api_key = os.getenv("OMNIROUTE_API_KEY", "")
    # "auto" lets OmniRoute's 9-factor scoring pick the best live provider —
    # see the /coding, /cheap, /smart aliases too if you want to pin a lane.
    model = llm_cfg.get("omniroute_model", "auto")
    try:
        resp = requests.post(
            f"{base_url}/chat/completions",
            headers={
                "Content-Type": "application/json",
                **({"Authorization": f"Bearer {api_key}"} if api_key else {}),
            },
            json={
                "model": model,
                "max_tokens": max_tokens,
                "messages": [{"role": "user", "content": prompt}],
            },
            timeout=60,
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]
    except Exception:
        return None

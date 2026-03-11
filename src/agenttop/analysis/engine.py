"""Multi-provider LLM client using litellm."""

from __future__ import annotations

import os
import urllib.request

from agenttop.config import LLMConfig


def _is_ollama(config: LLMConfig) -> bool:
    """Check if the provider is Ollama."""
    return config.provider.lower() == "ollama"


_PROVIDER_KEY_FALLBACKS: dict[str, list[str]] = {
    "anthropic": ["ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN"],
    "openai": ["OPENAI_API_KEY"],
    "openrouter": ["OPENROUTER_API_KEY"],
}


def _resolve_config(config: LLMConfig) -> tuple[str, str | None]:
    """Resolve API key and base URL from config values or env vars.

    Tries the configured api_key_env first, then falls back to standard
    env var names for the provider so it "just works" for users who
    already have API keys set.
    """
    api_key = config.api_key or os.environ.get(config.api_key_env, "")

    if not api_key:
        provider = config.provider.lower()
        for env_var in _PROVIDER_KEY_FALLBACKS.get(provider, []):
            api_key = os.environ.get(env_var, "")
            if api_key:
                break

    base_url = config.base_url or os.environ.get(config.base_url_env, "") or None
    return api_key, base_url


def get_completion(
    prompt: str,
    config: LLMConfig,
    system: str = "You are a developer productivity analyst.",
    max_tokens: int = 1024,
) -> str:
    """Get a completion from the configured LLM provider via litellm.

    Returns the response text, or an error message if the call fails.
    """
    try:
        # Workaround: tiktoken on Python 3.14 raises
        # "Duplicate encoding name" because plugin modules are
        # discovered twice.  Patch _find_constructors to silently
        # overwrite duplicates instead of raising.
        try:
            import tiktoken.registry as _tr

            _orig_find = _tr._find_constructors

            def _tolerant_find() -> None:
                import importlib as _imp

                with _tr._lock:
                    if _tr.ENCODING_CONSTRUCTORS is not None:
                        return
                    _tr.ENCODING_CONSTRUCTORS = {}
                    try:
                        for mod_name in _tr._available_plugin_modules():
                            mod = _imp.import_module(mod_name)
                            constructors = getattr(mod, "ENCODING_CONSTRUCTORS", {})
                            for enc_name, constructor in constructors.items():
                                _tr.ENCODING_CONSTRUCTORS[enc_name] = constructor
                    except Exception:
                        _tr.ENCODING_CONSTRUCTORS = None
                        raise

            _tr._find_constructors = _tolerant_find
        except Exception:
            pass

        import litellm

        api_key, base_url = _resolve_config(config)

        # Ollama needs a non-empty api_key for litellm and its own base_url
        if _is_ollama(config):
            api_key = api_key or "ollama"
            base_url = base_url or "http://localhost:11434"

        kwargs: dict = {
            "model": config.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
            "max_tokens": max_tokens,
            "timeout": 60,
        }
        if api_key:
            kwargs["api_key"] = api_key
        if base_url:
            kwargs["api_base"] = base_url

        response = litellm.completion(**kwargs)
        return response.choices[0].message.content or ""
    except ImportError:
        return "[error] litellm not installed. Run: pip install litellm"
    except Exception as e:
        # Provide actionable error messages based on error type
        err_type = type(e).__name__
        err_str = str(e)
        if "AuthenticationError" in err_type or "401" in err_str:
            return f"[error] API key invalid or expired. Check {config.api_key_env}."
        if "RateLimitError" in err_type or "429" in err_str:
            return "[error] Rate limited by LLM provider. Wait a moment and retry."
        if "APIConnectionError" in err_type or "Connection" in err_type:
            return "[error] Could not reach LLM provider. Check your network."
        if "Timeout" in err_type:
            return "[error] LLM request timed out. Try again or use a smaller model."
        return f"[error] LLM call failed ({err_type}): {e}"


def is_llm_configured(config: LLMConfig) -> bool:
    """Check if an LLM is available (Ollama needs no API key)."""
    if _is_ollama(config):
        return True
    api_key, _ = _resolve_config(config)
    return bool(api_key)


def check_llm_available(config: LLMConfig) -> str:
    """Quick connectivity check. Returns error message or empty string if OK."""
    if _is_ollama(config):
        base_url = config.base_url or os.environ.get(config.base_url_env, "") or "http://localhost:11434"
        try:
            req = urllib.request.Request(base_url, method="GET")
            with urllib.request.urlopen(req, timeout=2):
                return ""
        except Exception:
            return (
                "Ollama is not running. To enable AI-powered analysis:\n\n"
                "  brew install ollama\n"
                "  ollama pull llama3.2\n"
                "  ollama serve\n\n"
                "Then refresh this view."
            )
    # For cloud providers, just check if key is set
    api_key, _ = _resolve_config(config)
    if not api_key:
        return f"No API key configured. Set {config.api_key_env} or add it to ~/.agenttop/config.toml"
    return ""

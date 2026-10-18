"""Compare chat-model reload cost with a short, reversible Ollama keep-alive."""

import httpx

from app.core.config import Settings


def main() -> None:
    settings = Settings()
    base_url = settings.ollama_base_url.rstrip("/")
    with httpx.Client(timeout=settings.ollama_timeout_seconds) as client:
        for keep_alive in (0, 0, 300, 300, 0):
            response = client.post(f"{base_url}/api/chat", json={
                "model": settings.ollama_model,
                "messages": [{"role": "user", "content": "Define a bathroom tap in one short sentence."}],
                "stream": False,
                "think": False,
                "keep_alive": keep_alive,
                "options": {"num_predict": 48},
            })
            response.raise_for_status()
            result = response.json()
            loaded = client.get(f"{base_url}/api/ps")
            loaded.raise_for_status()
            models = loaded.json().get("models", [])
            resident = next((model for model in models if model.get("name") == settings.ollama_model), None)
            print({
                "keep_alive_seconds": keep_alive,
                "total_ms": round(result.get("total_duration", 0) / 1_000_000, 1),
                "load_ms": round(result.get("load_duration", 0) / 1_000_000, 1),
                "output_tokens": result.get("eval_count"),
                "resident_bytes": resident.get("size") if resident else 0,
                "resident_vram_bytes": resident.get("size_vram") if resident else 0,
            }, flush=True)


if __name__ == "__main__":
    main()

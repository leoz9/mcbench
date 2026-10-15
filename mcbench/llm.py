"""Model-agnostic chat client for any OpenAI-compatible /chat/completions endpoint
(OpenAI, DeepSeek, Qwen/DashScope, Kimi, GLM, Doubao, OpenRouter, vLLM, Ollama...)."""
import json
import os
import urllib.request


class OpenAICompatChat:
    def __init__(self, model, base_url, api_key_env="OPENAI_API_KEY", temperature=0.0, timeout=120, extra=None):
        self.model, self.base_url = model, base_url.rstrip("/")
        self.api_key = os.environ.get(api_key_env, "")
        self.temperature, self.timeout, self.extra = temperature, timeout, extra or {}
        if not self.api_key:
            raise RuntimeError(f"missing API key env var {api_key_env} for model {model}")

    def chat(self, messages, tools):
        body = {"model": self.model, "messages": messages, "tools": tools,
                "temperature": self.temperature, **self.extra}
        req = urllib.request.Request(self.base_url + "/chat/completions", data=json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json",
                                              "Authorization": f"Bearer {self.api_key}"}, method="POST")
        with urllib.request.urlopen(req, timeout=self.timeout) as r:
            data = json.loads(r.read())
        msg = data["choices"][0]["message"]
        return {"role": "assistant", "content": msg.get("content"), "tool_calls": msg.get("tool_calls") or []}, data.get("usage")

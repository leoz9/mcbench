"""Model-agnostic chat client for any OpenAI-compatible /chat/completions endpoint
(OpenAI, DeepSeek, Qwen/DashScope, Kimi, GLM, Doubao, OpenRouter, vLLM, Ollama...)."""
import json
import os
import urllib.error
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
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                data = json.loads(r.read())
        except urllib.error.HTTPError as e:
            raise RuntimeError(f"HTTP {e.code}: {e.read().decode('utf-8', 'replace')[:300]}") from None
        msg = data["choices"][0]["message"]
        return {"role": "assistant", "content": msg.get("content"), "tool_calls": msg.get("tool_calls") or []}, data.get("usage")


class AnthropicCompatChat:
    """Anthropic Messages API (/v1/messages) adapter; converts to/from the OpenAI-style
    messages the harness uses. Works with any Anthropic-compatible gateway."""

    def __init__(self, model, base_url, api_key_env="ANTHROPIC_API_KEY", temperature=0.0, timeout=120,
                 extra=None, max_tokens=2048):
        self.model, self.base_url = model, base_url.rstrip("/")
        self.api_key = os.environ.get(api_key_env, "")
        self.temperature, self.timeout, self.extra, self.max_tokens = temperature, timeout, extra or {}, max_tokens
        if not self.api_key:
            raise RuntimeError(f"missing API key env var {api_key_env} for model {model}")

    @staticmethod
    def convert(messages, tools):
        system = "\n".join(m["content"] for m in messages if m["role"] == "system")
        out = []
        for m in messages:
            if m["role"] == "user":
                out.append({"role": "user", "content": m["content"]})
            elif m["role"] == "assistant":
                blocks = [{"type": "text", "text": m["content"]}] if m.get("content") else []
                for tc in m.get("tool_calls") or []:
                    blocks.append({"type": "tool_use", "id": tc["id"], "name": tc["function"]["name"],
                                   "input": json.loads(tc["function"]["arguments"] or "{}")})
                out.append({"role": "assistant", "content": blocks or [{"type": "text", "text": "…"}]})
            elif m["role"] == "tool":
                block = {"type": "tool_result", "tool_use_id": m["tool_call_id"], "content": m["content"]}
                if out and out[-1]["role"] == "user" and isinstance(out[-1]["content"], list):
                    out[-1]["content"].append(block)
                else:
                    out.append({"role": "user", "content": [block]})
        atools = [{"name": t["function"]["name"], "description": t["function"].get("description", ""),
                   "input_schema": t["function"]["parameters"]} for t in tools]
        return system, out, atools

    def chat(self, messages, tools):
        system, msgs, atools = self.convert(messages, tools)
        body = {"model": self.model, "system": system, "messages": msgs, "tools": atools,
                "max_tokens": self.max_tokens, "temperature": self.temperature, **self.extra}
        url = self.base_url + ("/messages" if self.base_url.endswith("/v1") else "/v1/messages")
        req = urllib.request.Request(url, data=json.dumps(body).encode(), method="POST",
                                     headers={"Content-Type": "application/json", "x-api-key": self.api_key,
                                              "anthropic-version": "2023-06-01"})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                data = json.loads(r.read())
        except urllib.error.HTTPError as e:
            raise RuntimeError(f"HTTP {e.code}: {e.read().decode('utf-8', 'replace')[:300]}") from None
        text = "".join(b.get("text", "") for b in data.get("content", []) if b["type"] == "text")
        calls = [{"id": b["id"], "type": "function",
                  "function": {"name": b["name"], "arguments": json.dumps(b.get("input") or {}, ensure_ascii=False)}}
                 for b in data.get("content", []) if b["type"] == "tool_use"]
        u = data.get("usage") or {}
        return {"role": "assistant", "content": text or None, "tool_calls": calls}, \
            {"prompt_tokens": u.get("input_tokens"), "completion_tokens": u.get("output_tokens")}

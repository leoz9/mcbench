"""Chat-loop harness: drives any chat agent (OpenAI/Anthropic-compatible or scripted) through McBenchEnv."""
import json
import re

from .env import McBenchEnv

_SCRUB = re.compile(r'("coupon(?:Id|Code)"\s*:\s*")([^"]{4,})(")')


def scrub(obj):
    """Mask user-bound coupon ids/codes before a trace is written to disk."""
    s = json.dumps(obj, ensure_ascii=False)
    s = _SCRUB.sub(lambda m: m.group(1) + (m.group(2) if "MOCK" in m.group(2) or m.group(2).startswith("***")
                                           else "***" + m.group(2)[-4:]) + m.group(3), s)
    return json.loads(s)


def run_episode(agent, agent_name, task, env: McBenchEnv, max_turns=16):
    obs, _ = env.reset(task=task)
    messages = [{"role": "system", "content": obs["system"]}, {"role": "user", "content": obs["prompt"]}]
    usage_total = {"prompt_tokens": 0, "completion_tokens": 0}
    info, nudged = None, 0
    for _turn in range(max_turns):
        try:
            msg, usage = agent.chat(messages, obs["tools"])
        except Exception as e:  # noqa
            if getattr(e, "infra", False):  # provider/transport failure: discard episode, caller re-queues
                raise
            env.log({"type": "error", "text": f"LLM error: {str(e)[:300]}"})
            break
        for k in usage_total:
            usage_total[k] += (usage or {}).get(k) or 0
        msg = {k: v for k, v in msg.items() if v not in (None, [])} | {"role": "assistant"}
        messages.append(msg)
        env.think(msg.get("content"))
        if not msg.get("tool_calls"):
            if nudged < 2 and not getattr(agent, "scripted", False):
                nudged += 1
                messages.append({"role": "user", "content": "请继续：用工具完成任务，最后调用 submit_order 或 report_infeasible。"})
                continue
            break
        for tc in msg["tool_calls"]:
            out, reward, term, trunc, step_info = env.step({"name": tc["function"]["name"],
                                                            "arguments": tc["function"].get("arguments") or "{}"})
            messages.append({"role": "tool", "tool_call_id": tc["id"], "content": json.dumps(out, ensure_ascii=False)})
            if term or trunc:
                info = step_info
                break
        if info:
            break
    if not info:
        info = env.finish()
    tr = info["trace"]
    tr.update(model=agent_name, runtime=getattr(agent, "runtime", None), usage=usage_total)
    return scrub(tr)

# Gym-style environment API

```python
from mcbench.env import McBenchEnv
env = McBenchEnv(mode="offline", task_set="v1.0", max_steps=30)
obs = env.reset(task_id="budget-solo")      # {'system','user','tools'(OpenAI format),'task'}
obs, reward, terminated, truncated, info = env.step(
    {"name": "query-nearby-stores", "arguments": {"searchType": 2, "city": "上海", "keyword": "人民广场", "beType": 1}})
...
obs, reward, terminated, truncated, info = env.step(
    {"name": "submit_order", "arguments": {"storeCode": "...", "items": [...], "claimedPayable": 28.0}})
info["verdict"], info["score"], info["trace"]
```

- Reward is sparse: `score/100` on termination, 0 otherwise.
- Terminating actions: `submit_order`, `report_infeasible`; truncation at `max_steps`.
- `ask_user` returns the next scripted user reply (clarification tasks).
- Blocked write tools return `{"blocked": true}` and increment `safety_violations`.
- Fully deterministic offline (snapshot frozen, `now-time-info` frozen).

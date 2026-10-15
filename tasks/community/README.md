# 社区任务投稿 / Community tasks

把你的任务文件放在本目录（`.yml` / `.json`），然后：

```bash
mcbench task new --id community-<your-handle>-01 --category budget --difficulty medium
# 编辑生成的 YAML
mcbench task validate tasks/community/
```

PR 合并前 CI 会自动跑 schema + 冻结快照上的可解性检查。详见 [docs/contributing-tasks.md](../docs/contributing-tasks.md)。

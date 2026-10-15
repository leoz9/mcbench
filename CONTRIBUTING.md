# Contributing to McBench

欢迎共建！三种参与方式：
1. **贡献任务** → [docs/contributing-tasks.md](docs/contributing-tasks.md)
2. **提交模型成绩** → 打开 *Model submission* issue，附 `runs/<dir>/traces/*.json`
3. **代码** → `pip install -e .[dev] && pytest && ruff check .`

Rules: never add tools that place orders or mutate accounts; never commit tokens, phone numbers, addresses or real coupon codes; don't mention other brands.

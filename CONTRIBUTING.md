# Contributing to DivApply

Thanks for helping improve DivApply. This project is a Windows-first, AI-assisted job application pipeline, and changes should be checked carefully before merge.

## Local Setup

```bash
git clone https://github.com/InnitDivine/DivApply.git
cd DivApply
uv sync --locked --extra dev --extra full
uv run divapply --version
uv run python -m divapply --version
uv run pytest -q
uv run ruff check .
uv run mypy --platform linux src/divapply
uv run mypy --platform win32 src/divapply
```

Install `uv==0.11.28`; do not update `uv.lock` during ordinary verification. If `uv` is unavailable, `python -m pip install -e ".[dev,full]"` remains a compatibility fallback, but it does not reproduce CI's exact dependency tree.

JobSpy is not needed for unit tests. To exercise live JobSpy discovery, run `uv pip install --python .venv --no-deps python-jobspy==1.1.82` after the locked sync. Do not install upstream JobSpy dependencies directly until its `markdownify<0.14.0` pin is relaxed.

## Repo Layout

- `src/divapply/` contains the Python package.
- `src/divapply/config/` contains shipped YAML config.
- `README.md` documents the public workflow.

## Contributing Notes

- Keep the public CLI and docs aligned with DivApply.
- Keep editable installs and built wheel installs behaviorally aligned.
- Prefer small, reviewable changes.
- If you use AI-assisted code generation, review the result before commit.

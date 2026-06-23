# Contributing to DivApply

Thanks for helping improve DivApply. This project is a Windows-first, AI-assisted job application pipeline, and changes should be checked carefully before merge.

## Local Setup

```bash
git clone https://github.com/InnitDivine/DivApply.git
cd DivApply
python -m pip install -e ".[dev,full]"
python -m pip install --no-deps python-jobspy
divapply --version
python -m divapply --version
python -m pytest -q
ruff check .
```

The separate `python -m pip install --no-deps python-jobspy` step matches the runtime install path in the README. Do not install upstream JobSpy dependencies directly until its `markdownify<0.14.0` pin is relaxed.

## Repo Layout

- `src/divapply/` contains the Python package.
- `src/divapply/config/` contains shipped YAML config.
- `README.md` documents the public workflow.

## Contributing Notes

- Keep the public CLI and docs aligned with DivApply.
- Keep editable installs and built wheel installs behaviorally aligned.
- Prefer small, reviewable changes.
- If you use AI-assisted code generation, review the result before commit.

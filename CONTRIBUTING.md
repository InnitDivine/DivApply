# Contributing to divapply

Thanks for helping improve divapply. This project is a Windows-first, AI-assisted job application pipeline, and changes should be checked carefully before merge.

## Local Setup

```bash
git clone https://github.com/InnitDivine/divapply.git
cd divapply
pip install -e ".[dev]"
divapply --version
```

## Repo Layout

- `src/divapply/` contains the Python package.
- `src/divapply/config/` contains shipped YAML config.
- `README.md` documents the public workflow.

## Contributing Notes

- Keep the public CLI and docs aligned with `divapply`.
- Prefer small, reviewable changes.
- If you use AI-assisted code generation, review the result before commit.

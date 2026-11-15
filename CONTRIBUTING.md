# Contributing

```
pip install -e ".[dev]"
pytest
ruff check .
```

- The package lives at `synclayer/` in the repository root; use relative imports inside it.
- Add a line under `## Unreleased` in `CHANGELOG.md` for user-visible changes.
- Releases: `python scripts/pypimgr/pypimgr.py release patch --push`.

# Local Wiki Setup

This project can be viewed as a local wiki using MkDocs Material.

## Quick start

1. Install docs dependencies:

```bash
python -m pip install mkdocs mkdocs-material
```

2. Start local docs server:

```bash
python -m mkdocs serve
```

3. Open the local URL shown in terminal (usually `http://127.0.0.1:8000`).

## Build static docs

```bash
python -m mkdocs build
```

The built site is written to `site/`.

## Notes

- Source docs live in `docs/`.
- Navigation is configured in `mkdocs.yml`.
- Keep operational references in `docs/reference/` and system behavior docs in `docs/design-docs/`.


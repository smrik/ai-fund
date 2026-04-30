# Local Wiki Setup

This project can be viewed as a local wiki using MkDocs Material.

## Quick start

1. Install docs dependencies:

```bash
python -m pip install "mkdocs<2" "mkdocs-material<10"
```

2. Start local docs server:

```bash
NO_MKDOCS_2_WARNING=1 python -m mkdocs serve
```

3. Open the local URL shown in terminal (usually `http://127.0.0.1:8000`).

## Build static docs

```bash
NO_MKDOCS_2_WARNING=1 python -m mkdocs build
```

The built site is written to `site/`.

## Notes

- Source docs live in `docs/`.
- Navigation is configured in `mkdocs.yml`.
- Keep operational references in `docs/reference/` and system behavior docs in `docs/design-docs/`.
- Material for MkDocs 9.x emits a warning banner about a hypothetical MkDocs 2.0 upgrade. This repo is pinned to MkDocs 1.x and Material 9.x, and `NO_MKDOCS_2_WARNING=1` is the official way to suppress that banner during local docs work.

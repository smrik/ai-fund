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

## Recommended editing workflow

- Edit docs in VS Code.
- Read the rendered docs in the MkDocs browser view.
- Keep the Explorer focused on `docs/`, `mkdocs.yml`, and the few source files you are actively changing.

If you use the checked-in VS Code workspace files, the repo provides these tasks:

- `Docs: MkDocs Serve`
- `Docs: MkDocs Build Strict`
- `Quality: Local Gate`

Run them from `Terminal -> Run Task` or the command palette.

## Build static docs

```bash
python -m mkdocs build
```

The built site is written to `site/`.

## Notes

- Source docs live in `docs/`.
- Navigation is configured in `mkdocs.yml`.
- Keep operational references in `docs/reference/` and system behavior docs in `docs/design-docs/`.


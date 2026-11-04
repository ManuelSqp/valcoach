# Contributing to valcoach

## Set up

```bash
git clone https://github.com/ManuelSqp/valcoach.git && cd valcoach
python3 -m venv .venv && source .venv/bin/activate     # Python 3.11 or newer
pip install -e ".[dev]"
pre-commit install                                      # ruff runs before every commit
```

The tests need no API keys and no Ollama: they build their own synthetic matches and a short synthetic VOD.

```bash
pytest -q                    # the whole suite (a few minutes)
pytest -q -k aim             # only tests with "aim" in the name
ruff check valcoach tests    # the same lint check as CI
```

## Pull requests

- One topic per pull request; the tests and ruff must pass (CI runs both on Python 3.11 and 3.12).
- New behaviour comes with a test, and with a line in `CHANGELOG.md` if people will notice it.
- Bump the version in `valcoach/__init__.py`, `pyproject.toml` and the README's **Version** line for a release.
- Text people read in the web app: add the German line to `valcoach/i18n/de.json` (`#` = any number,
  `{name}` = any text). A missing line just stays English.
- Keep examples and docs generic (`Name#TAG`, `teammate1`), not about a real player or team.
- Never commit `data/` (database with API keys and password hashes) or `config.toml`.

## Security

Please don't open public issues for security problems: see [SECURITY.md](SECURITY.md).

# Contributing

Thank you for helping build SAP Knowledge Pipeline. The project is in an early
stage, so small protocol fixtures, documentation improvements, and focused bug
fixes are especially valuable.

## Set up the project

Fork the repository, clone your fork, and create a branch from `main`:

```console
git clone https://github.com/YOUR-USERNAME/sap-knowledge-pipeline.git
cd sap-knowledge-pipeline
git switch -c fix/short-description
python -m venv .venv
```

Activate the environment and install the development dependencies:

```console
# Windows PowerShell
.venv\Scripts\Activate.ps1
python -m pip install --group dev -e .

# macOS or Linux
source .venv/bin/activate
python -m pip install --group dev -e .
```

## Run the checks

Run the same checks used by CI before opening a pull request:

```console
ruff check .
ruff format --check .
mypy src
pytest
```

Use `ruff format .` to apply formatting. Add a regression test for every bug
fix. Tests must not require credentials or a live SAP system; use an
`httpx.MockTransport`, fake DB-API connection, and sanitized fixtures instead.

## Security and test data

Never commit SAP credentials, cookies, tokens, internal hostnames, customer
data, or metadata copied from a private system. Reduce payloads to the smallest
synthetic fixture that demonstrates the behavior.

Please do not open a public issue for a suspected vulnerability. Until a
private security contact is published, follow [SECURITY.md](SECURITY.md).

By participating, you agree to follow the project's
[Code of Conduct](CODE_OF_CONDUCT.md).

## Pull requests

Keep pull requests focused. In the description, explain the problem, the chosen
behavior, and how it was tested. Link the related issue with `Fixes #123` when
appropriate. Maintainers may ask for changes when a contribution expands the
public API or weakens continuation-link validation.

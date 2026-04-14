# Contributing to EagleEye-Nigeria

Thank you for your interest in contributing. This project exists to serve national security and peacebuilding in Nigeria — every contribution matters.

---

## Before You Start

- Read the [README](README.md) to understand the mission and roadmap.
- Check the [Issues](../../issues) tab for open tasks. Look for the `good-first-issue` label if you are new.
- If you want to work on something not listed, open an issue first to discuss it before writing code.

---

## Setting Up Locally

```bash
git clone https://github.com/your-org/eagleeye-nigeria.git
cd eagleeye-nigeria

python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate

pip install -r requirements.txt

cp .env.example .env
# Fill in your API keys in .env
```

See `docs/setup.md` for API key registration guides (NASA FIRMS, GEE, ACLED).

---

## Branch Naming

| Type | Format | Example |
|---|---|---|
| Feature | `feature/short-description` | `feature/firms-api-integration` |
| Bug fix | `fix/short-description` | `fix/sentinel-tile-offset` |
| Docs | `docs/short-description` | `docs/update-setup-guide` |
| ML / Model | `ml/short-description` | `ml/camp-detection-model-v1` |

Always branch off `main`.

---

## Pull Request Guidelines

1. Keep PRs focused — one feature or fix per PR.
2. Write or update tests for any new logic under `tests/`.
3. Run the linter before pushing:
   ```bash
   ruff check .
   black --check .
   ```
4. Fill out the PR template fully, including what was changed and how it was tested.
5. At least one reviewer must approve before merging.

---

## Code Style

- Python: [Black](https://black.readthedocs.io/) formatting, [Ruff](https://docs.astral.sh/ruff/) linting.
- Max line length: **88 characters** (Black default).
- All functions and classes must have docstrings.
- Use type hints throughout.

---

## Security & Sensitive Data

- **Never commit `.env` or any file containing real API keys.**
- Never log or print raw satellite coordinates or alert locations to public outputs.
- If you discover a security vulnerability, report it privately to [security contact] — do not open a public issue.

---

## Roles & Who to Contact

| Role | Responsibilities | Contact |
|---|---|---|
| GIS Engineers | Satellite data pipelines, coordinate systems | [Link] |
| Fullstack Devs | Dashboard, API endpoints | [Link] |
| AI Researchers | Model training, evaluation | [Link] |
| OSINT Analysts | Ground-truth verification | [Link] |

---

## Code of Conduct

This project is a professional, mission-driven space. Contributors are expected to engage respectfully and in good faith at all times. Contributions that could compromise operational security or endanger civilians will be rejected.

---

*"The eye of the eagle sees what the ground-dweller cannot."*

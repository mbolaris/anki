# Contributing

Thanks for your interest in improving the Anki Deck Viewer! This document
captures the conventions used throughout the project so contributions can be
reviewed quickly and confidently.

## Environment setup

1. Create a virtual environment and install the runtime + test dependencies:

   ```bash
   python -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   ```

2. Copy an Anki package (``.apkg``) into the ``data/`` directory. The MCAT deck
   referenced in the README is the default, but any Anki collection should work.

## Running checks

* Unit & integration tests with coverage (required):

  ```bash
  pytest
  ```

* Smoke test that exercises the Flask routes end-to-end:

  ```bash
  python scripts/smoke_test.py
  ```

The ``pytest.ini`` configuration fails the suite if coverage falls below 80 %,
so please add tests alongside new features or bug fixes.

## Code style

* The codebase targets Python 3.11+. Use type annotations and keep functions
  small with focused responsibilities.
* All public helpers and view functions must include docstrings with parameters,
  return types, and ``Examples`` sections.
* Run ``ruff --fix`` if you add it locally; the repository follows standard
  PEP 8 spacing and uses double quotes for strings in Python.
* Front-end changes should maintain accessibility attributes and keyboard
  navigation. If you add new controls, document the shortcuts in the help
  overlay and README.

## Submitting changes

1. Create a feature branch and commit logically grouped changes with descriptive
   messages.
2. Run the tests locally before opening a pull request.
3. Include a summary of user-facing updates plus any testing performed in your
   PR description.

Thank you for helping keep the project healthy! :tada:

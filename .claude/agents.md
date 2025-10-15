# Project Information for AI Agents

## Running Tests

This project uses pytest for unit testing.

### Test Command
```bash
python -m pytest
```

### Installing Dependencies
If pytest is not installed, first install the project dependencies:
```bash
pip install -r requirements.txt
```

### Test Files Location
All test files are located in the `tests/` directory:
- `test_card_types.py` - Tests for card type functionality
- `test_deck_loader.py` - Tests for deck loading functionality
- `test_routes.py` - Tests for Flask routes
- `test_smoke_script.py` - Smoke tests for the application

### Test Coverage
The project requires 80% test coverage. Coverage reports are automatically generated when running pytest (configured in pytest.ini).

### Quick Reference
- **Run all tests**: `python -m pytest`
- **Run with verbose output**: `python -m pytest -v`
- **Run specific test file**: `python -m pytest tests/test_card_types.py`
- **Run with coverage report**: `python -m pytest --cov` (default behavior)

## Project Structure

- `anki_viewer/` - Main application package
  - `__init__.py` - Flask application setup and routes
  - `card_types.py` - Card type definitions and handling
  - `deck_loader.py` - Deck loading and parsing functionality
- `tests/` - Test files
- `scripts/` - Utility scripts including smoke tests
- `data/` - Data directory (Anki decks, etc.)
- `docs/` - Documentation

## Technology Stack
- Python 3.13
- Flask 3.x - Web framework
- pytest 7.4+ - Testing framework
- pytest-cov 4.1+ - Coverage plugin

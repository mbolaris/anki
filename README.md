# Anki Deck Viewer

A minimal Flask web server that renders flashcards from the
`MCAT_High_Yield.apkg` deck.

## Getting started

1. Create a virtual environment and install dependencies:

   ```bash
   python -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   ```

2. Copy the Anki deck into the `data/` directory located at the root of this
   repository (the file is ignored by Git). The application prefers the
   `MCAT_High_Yield.apkg` filename but also recognizes the original export name
   `MCAT High Yield.apkg` (hyphenated variations work as well).

3. Start the server:

   ```bash
   flask --app app run --host 0.0.0.0 --port 5000
   ```

4. Visit <http://localhost:5000> in a browser to browse decks and cards.

The application automatically unpacks the Anki collection in a temporary
location on startup, so you can update the package at any time by replacing the
file and restarting the server.

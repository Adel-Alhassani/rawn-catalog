# rawn-catalog

Builds the book catalog for the Rawn Android app (an English→Arabic e-book reader).
`build_catalog.py` reads Project Gutenberg's official RDF metadata archive and writes
`catalog.json.gz` + `manifest.json`. A weekly GitHub Actions workflow publishes both as
assets of the GitHub Release tagged `latest`, which the app downloads.

## Working rules (same as the Rawn project)

- Use the built-in Read, Grep and Glob tools for files, not shell `cat`/`grep`/`find`.
- One plain command per Bash/PowerShell call: no `&&` chains, pipes or `cd` prefixes.
- Never push (or create/modify remote state) unless the user asks.

## Project rules

- Python standard library only. No third-party dependencies.
- Gutenberg robot policy: only download the official catalog feed
  (`https://www.gutenberg.org/cache/epub/feeds/rdf-files.tar.bz2`). Never crawl the site.
  Always send the `rawn-catalog/1.0` User-Agent.
- Never publish an empty or much smaller catalog (< 80% of the previous book count).
- The workflow uses only the built-in `GITHUB_TOKEN` with `contents: write`.
- Changing the output shape means bumping `SCHEMA_VERSION` in `build_catalog.py` and
  updating the README.

## Commands

- Build: `python build_catalog.py` (outputs to `dist/`, caches the archive in `build/`)
- Test: `python -m unittest discover -s tests -v`

# rawn-catalog

Builds the book catalog used by the Rawn Android app (an English→Arabic e-book reader).
A GitHub Actions workflow rebuilds it weekly and publishes it as a GitHub Release.

## Data source

[Project Gutenberg](https://www.gutenberg.org/) catalog metadata (public domain), taken
only from the official feed `https://www.gutenberg.org/cache/epub/feeds/rdf-files.tar.bz2`.
The website is never crawled, in line with Gutenberg's robot policy.

Kept: books whose type is `Text`, whose only language is English, and that have an EPUB.

## Output

- `catalog.json.gz`: compact JSON (no pretty printing):
  - `schemaVersion`, `version` (build date)
  - `books`: `i` id, `t` title, `a` authors `[name, birthYear|null, deathYear|null]`,
    `s` subjects, `b` bookshelves, `d` download count, `e` 1 if an EPUB3 with images exists
  - `popular`: ids of the top 200 books by downloads
  - `shelves`: `{n: bookshelf name, b: book ids ordered by downloads}`
- `manifest.json`: `schemaVersion`, `version` (build date), `bookCount`, `sha256` and
  `size` of `catalog.json.gz`.

## Download URLs

- https://github.com/Adel-Alhassani/rawn-catalog/releases/download/latest/manifest.json
- https://github.com/Adel-Alhassani/rawn-catalog/releases/download/latest/catalog.json.gz

Fetch the manifest first and download the catalog only when `version` changed; verify
the download against `sha256`.

## Run locally

Python 3.9+ and the standard library only.

    python build_catalog.py

Downloads the archive (about 150 MB) to `build/`, then writes `dist/catalog.json.gz` and
`dist/manifest.json` and prints the stats. Useful options: `--archive FILE` (use a local
archive), `--redownload`, `--out-dir`, `--previous-manifest URL_OR_PATH`.

Tests:

    python -m unittest discover -s tests -v

## Workflow

`.github/workflows/build.yml` runs every Monday 03:17 UTC and on manual "Run workflow".
It tests, builds, and replaces the assets of the `latest` release using only the built-in
`GITHUB_TOKEN` (`contents: write`). It fails, without publishing, if Gutenberg's file
cannot be downloaded or if the new catalog has under 80% of the previously published book
count.

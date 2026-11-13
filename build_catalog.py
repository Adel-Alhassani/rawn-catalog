#!/usr/bin/env python3
"""Build the Rawn book catalog from Project Gutenberg's RDF metadata archive.

Only the official catalog feed is downloaded (never the website itself).
Outputs dist/catalog.json.gz and dist/manifest.json. Standard library only.
"""

import argparse
import gzip
import hashlib
import json
import os
import re
import sys
import tarfile
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

SCHEMA_VERSION = 1
ARCHIVE_URL = "https://www.gutenberg.org/cache/epub/feeds/rdf-files.tar.bz2"
POPULAR_COUNT = 200
MIN_BOOKS = 1000  # absolute sanity floor
MIN_RATIO = 0.8  # never publish < 80% of the previous book count

RDF = "{http://www.w3.org/1999/02/22-rdf-syntax-ns#}"
DCT = "{http://purl.org/dc/terms/}"
DCAM = "{http://purl.org/dc/dcam/}"
PG = "{http://www.gutenberg.org/2009/pgterms/}"

_WS = re.compile(r"\s+")


def user_agent():
    repo = os.environ.get("GITHUB_REPOSITORY") or "<your-username>/rawn-catalog"
    return f"rawn-catalog/1.0 (+https://github.com/{repo})"


def _clean(text):
    return _WS.sub(" ", text).strip() if text else ""


def _int(text):
    try:
        return int(text.strip())
    except (AttributeError, ValueError):
        return None


def _values(parent, tag):
    """Text of rdf:Description/rdf:value under each <tag> child of parent."""
    out = []
    for el in parent.findall(tag):
        v = el.find(f"{RDF}Description/{RDF}value")
        if v is not None and v.text and v.text.strip():
            out.append(_clean(v.text))
    return out


def parse_book(xml_bytes):
    """Parse one Gutenberg RDF file. Returns a compact book dict, or None if the
    book is not kept (not Text, not English-only, or no EPUB)."""
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError:
        return None
    ebook = root.find(f"{PG}ebook")
    if ebook is None:
        return None

    about = ebook.get(f"{RDF}about", "")
    book_id = _int(about.rsplit("/", 1)[-1])
    if book_id is None:
        return None

    if _values(ebook, f"{DCT}type") != ["Text"]:
        return None
    if _values(ebook, f"{DCT}language") != ["en"]:
        return None

    has_epub = False
    epub3_images = False
    for f in ebook.findall(f"{DCT}hasFormat/{PG}file"):
        mimes = [
            _clean(v.text)
            for v in f.findall(f"{DCT}format/{RDF}Description/{RDF}value")
            if v.text
        ]
        if "application/epub+zip" in mimes:
            has_epub = True
            if f.get(f"{RDF}about", "").endswith(".epub3.images"):
                epub3_images = True
    if not has_epub:
        return None

    title = _clean(ebook.findtext(f"{DCT}title"))
    if not title:
        return None

    authors = []
    for creator in ebook.findall(f"{DCT}creator"):
        agent = creator.find(f"{PG}agent")
        if agent is None:
            continue
        name = _clean(agent.findtext(f"{PG}name"))
        if name:
            authors.append(
                [name, _int(agent.findtext(f"{PG}birthdate")),
                 _int(agent.findtext(f"{PG}deathdate"))]
            )

    subjects = []
    for s in ebook.findall(f"{DCT}subject"):
        desc = s.find(f"{RDF}Description")
        if desc is None:
            continue
        kind = desc.find(f"{DCAM}memberOf")
        if kind is None or not kind.get(f"{RDF}resource", "").endswith("LCSH"):
            continue
        v = desc.findtext(f"{RDF}value")
        if v and v.strip():
            subjects.append(_clean(v))

    return {
        "i": book_id,
        "t": title,
        "a": authors,
        "s": subjects,
        "b": _values(ebook, f"{PG}bookshelf"),
        "d": _int(ebook.findtext(f"{PG}downloads")) or 0,
        "e": 1 if epub3_images else 0,
    }


def download_archive(dest, url=ARCHIVE_URL, attempts=3):
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    last = None
    for attempt in range(1, attempts + 1):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": user_agent()})
            with urllib.request.urlopen(req, timeout=60) as resp, open(tmp, "wb") as out:
                expected = int(resp.headers.get("Content-Length") or 0)
                done = 0
                while chunk := resp.read(1 << 20):
                    out.write(chunk)
                    done += len(chunk)
            if expected and done != expected:
                raise OSError(f"truncated download: got {done} of {expected} bytes")
            if done == 0:
                raise OSError("empty download")
            tmp.replace(dest)
            return dest
        except (OSError, urllib.error.URLError) as e:
            last = e
            print(f"download attempt {attempt}/{attempts} failed: {e}", file=sys.stderr)
            if attempt < attempts:
                time.sleep(5 * attempt)
    raise SystemExit(f"ERROR: could not download {url}: {last}")


def read_archive(path):
    """Yield the bytes of every .rdf file in the tar.bz2, streaming (no extraction)."""
    try:
        with tarfile.open(path, "r|bz2") as tf:
            for member in tf:
                if member.isfile() and member.name.endswith(".rdf"):
                    f = tf.extractfile(member)
                    if f is not None:
                        yield f.read()
    except (tarfile.TarError, OSError, EOFError) as e:
        raise SystemExit(f"ERROR: archive {path} is corrupt or unreadable: {e}")


def build_catalog(rdf_iter):
    """Returns (catalog dict, scanned count)."""
    books = {}
    scanned = 0
    for data in rdf_iter:
        scanned += 1
        if scanned % 10000 == 0:
            print(f"  scanned {scanned} files, kept {len(books)}", file=sys.stderr)
        book = parse_book(data)
        if book:
            books[book["i"]] = book

    ranked = sorted(books.values(), key=lambda b: (-b["d"], b["i"]))
    shelves = {}
    for b in ranked:
        for name in b["b"]:
            shelves.setdefault(name, []).append(b["i"])

    catalog = {
        "books": [books[i] for i in sorted(books)],
        "popular": [b["i"] for b in ranked[:POPULAR_COUNT]],
        "shelves": [{"n": n, "b": shelves[n]} for n in sorted(shelves)],
    }
    return catalog, scanned


def load_previous_count(source):
    """bookCount from a previous manifest (URL or path); None if there isn't one yet."""
    if not source:
        return None
    try:
        if re.match(r"https?://", source):
            req = urllib.request.Request(source, headers={"User-Agent": user_agent()})
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.load(resp)
        else:
            if not Path(source).exists():
                return None
            data = json.loads(Path(source).read_text(encoding="utf-8"))
        return int(data["bookCount"])
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None  # first run: nothing published yet
        raise SystemExit(f"ERROR: could not read previous manifest {source}: {e}")
    except (OSError, ValueError, KeyError, urllib.error.URLError) as e:
        raise SystemExit(f"ERROR: could not read previous manifest {source}: {e}")


def check_size(count, previous_count):
    if count < MIN_BOOKS:
        raise SystemExit(f"ERROR: only {count} books kept (minimum {MIN_BOOKS}); refusing to publish")
    if previous_count and count < previous_count * MIN_RATIO:
        raise SystemExit(
            f"ERROR: {count} books is under {int(MIN_RATIO * 100)}% of the previous "
            f"{previous_count}; refusing to publish"
        )


def write_outputs(catalog, out_dir, version):
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    payload = dict(schemaVersion=SCHEMA_VERSION, version=version, **catalog)
    raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    blob = gzip.compress(raw, compresslevel=9, mtime=0)  # mtime=0: reproducible bytes
    (out_dir / "catalog.json.gz").write_bytes(blob)
    manifest = {
        "schemaVersion": SCHEMA_VERSION,
        "version": version,
        "bookCount": len(catalog["books"]),
        "sha256": hashlib.sha256(blob).hexdigest(),
        "size": len(blob),
    }
    (out_dir / "manifest.json").write_text(
        json.dumps(manifest, separators=(",", ":")) + "\n", encoding="utf-8"
    )
    return manifest, len(raw)


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--archive", help="use this local rdf-files.tar.bz2 instead of downloading")
    p.add_argument("--cache-dir", default="build", help="where the downloaded archive is kept")
    p.add_argument("--out-dir", default="dist")
    p.add_argument("--previous-manifest", help="URL or path of the last published manifest.json")
    p.add_argument("--redownload", action="store_true", help="ignore a cached archive")
    args = p.parse_args(argv)

    previous = load_previous_count(args.previous_manifest)

    if args.archive:
        archive = Path(args.archive)
        if not archive.exists():
            raise SystemExit(f"ERROR: archive not found: {archive}")
    else:
        archive = Path(args.cache_dir) / "rdf-files.tar.bz2"
        if args.redownload or not archive.exists():
            print(f"downloading {ARCHIVE_URL}", file=sys.stderr)
            download_archive(archive)

    print("parsing…", file=sys.stderr)
    catalog, scanned = build_catalog(read_archive(archive))
    check_size(len(catalog["books"]), previous)

    version = datetime.now(timezone.utc).date().isoformat()
    manifest, raw_size = write_outputs(catalog, args.out_dir, version)

    print(f"files scanned:  {scanned}")
    print(f"books kept:     {manifest['bookCount']}")
    print(f"popular list:   {len(catalog['popular'])}")
    print(f"bookshelves:    {len(catalog['shelves'])}")
    print(f"json size:      {raw_size / 1e6:.2f} MB")
    print(f"catalog.json.gz {manifest['size'] / 1e6:.2f} MB ({manifest['size']} bytes)")
    print(f"sha256:         {manifest['sha256']}")
    print(f"version:        {version}")


if __name__ == "__main__":
    main()

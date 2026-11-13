import gzip
import io
import json
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import build_catalog as bc  # noqa: E402

SAMPLES = Path(__file__).resolve().parent / "samples"


def sample(name):
    return (SAMPLES / name).read_bytes()


class ParseBookTest(unittest.TestCase):
    def test_normal_book(self):
        b = bc.parse_book(sample("pg1342.rdf"))
        self.assertEqual(b["i"], 1342)
        self.assertEqual(b["t"], "Pride and Prejudice")
        self.assertEqual(b["a"], [["Austen, Jane", 1775, 1817]])
        self.assertEqual(b["s"], ["England -- Fiction"])  # LCC code "PR" excluded
        self.assertEqual(b["b"], ["Best Books Ever Listings", "Romance"])
        self.assertEqual(b["d"], 54321)
        self.assertEqual(b["e"], 1)

    def test_non_english_skipped(self):
        self.assertIsNone(bc.parse_book(sample("pg2650.rdf")))

    def test_audio_skipped(self):
        self.assertIsNone(bc.parse_book(sample("pg12345.rdf")))

    def test_no_epub_skipped(self):
        self.assertIsNone(bc.parse_book(sample("pg777.rdf")))

    def test_multiple_authors_and_no_epub3_images(self):
        b = bc.parse_book(sample("pg4242.rdf"))
        self.assertEqual(b["t"], "The Collaboration Of Two Authors")  # whitespace collapsed
        self.assertEqual(b["a"], [["Doe, Jane", 1850, 1920], ["Roe, Richard", None, 1900]])
        self.assertEqual(b["e"], 0)  # only epub.noimages

    def test_garbage_skipped(self):
        self.assertIsNone(bc.parse_book(b"not xml"))


class BuildTest(unittest.TestCase):
    def make_archive(self, tmp):
        path = Path(tmp) / "rdf-files.tar.bz2"
        with tarfile.open(path, "w:bz2") as tf:
            for f in sorted(SAMPLES.glob("*.rdf")):
                data = f.read_bytes()
                info = tarfile.TarInfo(f"cache/epub/{f.stem[2:]}/{f.name}")
                info.size = len(data)
                tf.addfile(info, io.BytesIO(data))
        return path

    def test_end_to_end(self):
        with tempfile.TemporaryDirectory() as tmp:
            archive = self.make_archive(tmp)
            catalog, scanned = bc.build_catalog(bc.read_archive(archive))
            self.assertEqual(scanned, 5)
            self.assertEqual([b["i"] for b in catalog["books"]], [1342, 4242])
            self.assertEqual(catalog["popular"], [4242, 1342])  # by downloads
            shelves = {s["n"]: s["b"] for s in catalog["shelves"]}
            self.assertEqual(shelves["Romance"], [4242, 1342])  # ordered by downloads
            self.assertEqual(shelves["Best Books Ever Listings"], [1342])

            manifest, _ = bc.write_outputs(catalog, Path(tmp) / "dist", "2026-01-02")
            blob = (Path(tmp) / "dist" / "catalog.json.gz").read_bytes()
            self.assertEqual(manifest["size"], len(blob))
            self.assertEqual(manifest["bookCount"], 2)
            self.assertEqual(manifest["version"], "2026-01-02")
            self.assertEqual(manifest["schemaVersion"], bc.SCHEMA_VERSION)
            import hashlib
            self.assertEqual(manifest["sha256"], hashlib.sha256(blob).hexdigest())
            data = json.loads(gzip.decompress(blob))
            self.assertEqual(len(data["books"]), 2)
            on_disk = json.loads((Path(tmp) / "dist" / "manifest.json").read_text())
            self.assertEqual(on_disk, manifest)

    def test_popular_capped(self):
        books = (
            ('<pgterms:ebook rdf:about="ebooks/%d"><dcterms:title>T%d</dcterms:title>'
             '<dcterms:type><rdf:Description><rdf:value>Text</rdf:value></rdf:Description></dcterms:type>'
             '<dcterms:language><rdf:Description><rdf:value>en</rdf:value></rdf:Description></dcterms:language>'
             '<pgterms:downloads>%d</pgterms:downloads>'
             '<dcterms:hasFormat><pgterms:file rdf:about="x.epub3.images"><dcterms:format><rdf:Description>'
             '<rdf:value>application/epub+zip</rdf:value></rdf:Description></dcterms:format></pgterms:file>'
             '</dcterms:hasFormat></pgterms:ebook>') % (n, n, n)
            for n in range(1, 251)
        )
        wrap = (
            '<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#" '
            'xmlns:dcterms="http://purl.org/dc/terms/" '
            'xmlns:pgterms="http://www.gutenberg.org/2009/pgterms/">%s</rdf:RDF>'
        )
        catalog, _ =bc.build_catalog(w.encode() for w in (wrap % b for b in books))
        self.assertEqual(len(catalog["popular"]), 200)
        self.assertEqual(catalog["popular"][0], 250)


class GuardTest(unittest.TestCase):
    def test_too_few_books(self):
        with self.assertRaises(SystemExit):
            bc.check_size(10, None)

    def test_shrunk_catalog(self):
        with self.assertRaises(SystemExit):
            bc.check_size(7900, 10000)

    def test_ok(self):
        bc.check_size(8000, 10000)
        bc.check_size(5000, None)

    def test_previous_manifest_missing_file(self):
        self.assertIsNone(bc.load_previous_count("does-not-exist.json"))
        self.assertIsNone(bc.load_previous_count(None))


if __name__ == "__main__":
    unittest.main()

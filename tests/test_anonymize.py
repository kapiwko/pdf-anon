import contextlib
import io
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import pymupdf as pdf

from anonymize import anonymize, main, rendering_dpi, page_format
from unittest.mock import patch


class AnonymizationTests(unittest.TestCase):
    def test_cli_with_legacy_output_encoding_and_unicode_paths(self):
        with tempfile.TemporaryDirectory() as directory:
            inputs = Path(directory) / "Dokumenty źródłowe"
            outputs = Path(directory) / "Wynik łódź"
            inputs.mkdir()
            source = inputs / "zażółć 日本.PDF"
            with pdf.open() as doc:
                page = doc.new_page(width=100, height=100)
                page.add_redact_annot(pdf.Rect(10, 10, 50, 50))
                doc.save(source)
            before = source.read_bytes()
            script = Path(__file__).resolve().parents[1] / "anonymize.py"
            for encoding in ("cp1250", "cp1252"):
                with self.subTest(encoding=encoding):
                    completed = subprocess.run(
                        [sys.executable, str(script), "--input", str(inputs),
                         "--output", str(outputs), "--dpi", "72", "--overwrite"],
                        env={**os.environ, "PYTHONIOENCODING": encoding + ":strict"},
                        capture_output=True, timeout=60,
                    )
                    self.assertEqual(completed.returncode, 0,
                                     (completed.stdout, completed.stderr))
                    self.assertIn("Gotowe: 1 plików", completed.stdout.decode(encoding))
                    self.assertEqual(source.read_bytes(), before)
                    with pdf.open(outputs / source.name) as result:
                        self.assertEqual(len(result), 1)
                        self.assertFalse(result[0].get_text().strip())
                    self.assertFalse(list(outputs.glob(".anon-*")))

    def test_page_format_uses_visible_orientation_and_custom_dimensions(self):
        with pdf.open() as doc:
            page = doc.new_page(width=595.44, height=842.04)
            self.assertEqual(page_format(page), "A4, pion, 210.1 × 297.1 mm")
            page.set_rotation(90)
            self.assertEqual(page_format(page), "A4, poziom, 297.1 × 210.1 mm")
            page = doc.new_page(width=1190.52, height=842.04)
            self.assertTrue(page_format(page).startswith("A3, poziom,"))
            page = doc.new_page(width=720, height=720)
            self.assertIn("niestandardowy", page_format(page))
            self.assertIn("254.0 × 254.0 mm", page_format(page))

    def test_extracted_pixels_rotations_crop_and_shared_image(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source.pdf"
            target = Path(directory) / "result.pdf"
            with pdf.open() as doc:
                image = pdf.Pixmap(pdf.csRGB, pdf.IRect(0, 0, 240, 180), False)
                image.set_rect(image.irect, (220, 40, 20))
                xref = 0
                for rotation in (0, 90, 180, 270):
                    page = doc.new_page(width=240, height=180)
                    if xref:
                        page.insert_image(page.rect, xref=xref)
                    else:
                        xref = page.insert_image(page.rect, pixmap=image)
                    page.insert_text((70, 75), "HIDDEN_SECRET", fontsize=8)
                    page.set_cropbox(pdf.Rect(10, 10, 230, 170))
                    annot = page.add_rect_annot(pdf.Rect(40, 40, 150, 90))
                    annot.set_colors(stroke=(0, 0, 0), fill=(0, 0, 0))
                    annot.update()
                    page.set_rotation(rotation)
                doc.set_metadata({"author": "PRIVATE_AUTHOR"})
                doc.embfile_add("secret.txt", b"ATTACHMENT_SECRET")
                doc.save(source)
            before = source.read_bytes()
            self.assertEqual(anonymize(source, target, dpi=144, progress=lambda _: None,
                                      compression="lossless"), (4, 4))
            self.assertEqual(source.read_bytes(), before)
            with pdf.open(target) as output, pdf.open(source) as original:
                self.assertEqual(output.embfile_count(), 0)
                self.assertFalse(output.metadata.get("author"))
                for index, page in enumerate(output):
                    self.assertFalse(page.get_text().strip())
                    self.assertFalse(list(page.annots() or ()))
                    self.assertEqual(page.rect, original[index].rect)
                    images = page.get_images()
                    self.assertEqual(len(images), 1)
                    # Odczyt pikseli bezpośrednio z osadzonego obrazu, bez renderowania PDF.
                    pix = pdf.Pixmap(output, images[0][0])
                    region = pdf.Rect(40, 40, 150, 90) * original[index].rotation_matrix
                    region = (region * pdf.Matrix(2, 2)).irect
                    for y in range(region.y0, region.y1):
                        row = pix.samples[(y * pix.width + region.x0) * 3:
                                          (y * pix.width + region.x1) * 3]
                        self.assertFalse(any(row), (index, y))
                    self.assertEqual(pix.pixel(5, 5), (220, 40, 20))
            self.assertNotIn(b"ATTACHMENT_SECRET", target.read_bytes())

    def test_jpeg_masks_pixels_before_encoding_and_reduces_size(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source.pdf"
            jpeg = Path(directory) / "jpeg.pdf"
            lossless = Path(directory) / "lossless.pdf"
            # Deterministyczna tekstura zamiast jednolitego koloru, który Flate
            # kompresuje lepiej od JPEG; oba wejścia różnią się tylko pod maską.
            import random
            rng = random.Random(42)
            samples = bytes(rng.randrange(180, 256) for _ in range(400 * 400 * 3))
            for secret_color in ((255, 0, 0), (0, 255, 0)):
                with pdf.open() as doc:
                    page = doc.new_page(width=144, height=144)
                    pix = pdf.Pixmap(pdf.csRGB, 400, 400, samples, False)
                    pix.set_rect(pdf.IRect(150, 150, 250, 250), secret_color)
                    page.insert_image(page.rect, pixmap=pix)
                    page.add_redact_annot(pdf.Rect(50, 50, 95, 95))
                    self.assertEqual(rendering_dpi(page, None), 200)
                    self.assertEqual(rendering_dpi(page, 144), 144)
                    doc.save(source)
                anonymize(source, jpeg, progress=lambda _: None)
                with pdf.open(jpeg) as doc:
                    image = doc[0].get_images()[0]
                    self.assertEqual(image[8], "DCTDecode")
                    self.assertEqual(image[2:4], (400, 400))
                    data = doc.xref_stream_raw(image[0])
                    if secret_color == (255, 0, 0):
                        first = data
                    else:
                        # Dane pod maską nie wpływają nawet na bajty JPEG wyniku.
                        self.assertEqual(first, data)
                    pix = pdf.Pixmap(doc, image[0])
                    self.assertEqual(pix.pixel(200, 200), (0, 0, 0))
            anonymize(source, lossless, compression="lossless", progress=lambda _: None)
            self.assertLess(jpeg.stat().st_size, lossless.stat().st_size / 2)

    def test_no_masks_or_unsupported_annotation_never_produces_output(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source.pdf"
            target = Path(directory) / "result.pdf"
            for unsupported in (False, True):
                with pdf.open() as doc:
                    page = doc.new_page()
                    if unsupported:
                        page.add_text_annot((30, 30), "note")
                    doc.save(source)
                with self.assertRaises(ValueError):
                    anonymize(source, target, progress=lambda _: None)
                self.assertFalse(target.exists())

    def test_batch_continues_after_failure_and_protects_existing_result(self):
        with tempfile.TemporaryDirectory() as directory:
            inputs, outputs = Path(directory) / "in", Path(directory) / "out"
            inputs.mkdir()
            (inputs / "a.pdf").write_bytes(b"invalid pdf")
            with pdf.open() as doc:
                page = doc.new_page(width=100, height=100)
                page.add_redact_annot(pdf.Rect(10, 10, 50, 50))
                doc.save(inputs / "b.PDF")
            args = ["anonymize.py", "--input", str(inputs), "--output", str(outputs), "--dpi", "72"]
            with patch("sys.argv", args), contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(main(), 1)
                before = (outputs / "b.PDF").read_bytes()
                self.assertEqual(main(), 1)
                self.assertEqual((outputs / "b.PDF").read_bytes(), before)


if __name__ == "__main__":
    unittest.main()

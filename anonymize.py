#!/usr/bin/env python3
"""Trwała anonimizacja PDF na podstawie czarnych adnotacji Square / Redact."""

import argparse
import math
import os
from pathlib import Path
import sys
import tempfile
import time

try:
    import pymupdf as pdf
except ImportError:
    sys.exit("Brak PyMuPDF. Zainstaluj: python -m pip install -r requirements.txt")


def is_black(color):
    if not color:
        return False
    if len(color) == 1:
        return color[0] <= 0.02
    if len(color) == 3:
        return max(color) <= 0.02
    if len(color) == 4:
        c, m, y, k = color
        return max((1 - c) * (1 - k), (1 - m) * (1 - k),
                   (1 - y) * (1 - k)) <= 0.02
    return False


def redaction_rects(page, margin):
    """Współrzędne adnotacji są niezależne od obrotu strony."""
    rects = []
    for annot in page.annots() or ():
        kind = annot.type[0]
        if kind == pdf.PDF_ANNOT_REDACT:
            rects.append(pdf.Rect(annot.rect) + (-margin, -margin, margin, margin))
        elif kind == pdf.PDF_ANNOT_SQUARE and is_black(annot.colors.get("fill")):
            # Obejmujemy cały prostokąt, także przy nietypowej przezroczystości.
            # Dodatkowy zapas na obrys oraz antyaliasing przy krawędzi.
            pad = margin + max(0, annot.border.get("width", 0)) / 2
            rects.append(pdf.Rect(annot.rect) + (-pad, -pad, pad, pad))
        elif kind != pdf.PDF_ANNOT_POPUP:
            raise ValueError(
                f"strona {page.number + 1}: nieobsługiwana adnotacja {annot.type[1]}; "
                "zamień oznaczenia anonimizacji na prostokąty z czarnym wypełnieniem"
            )
    return rects


def pixel_rect(rect, page, pix):
    """Obrót i skala do rastra; zaokrąglenie na zewnątrz."""
    visible = (rect * page.rotation_matrix) & page.rect
    if visible.is_empty:
        raise ValueError(f"strona {page.number + 1}: prostokąt poza widoczną stroną")
    scale = pix.xres / 72
    return pdf.IRect(
        math.floor(visible.x0 * scale) - pix.x,
        math.floor(visible.y0 * scale) - pix.y,
        math.ceil(visible.x1 * scale) - pix.x,
        math.ceil(visible.y1 * scale) - pix.y,
    ) & pdf.IRect(0, 0, pix.width, pix.height)


def rendering_dpi(page, requested):
    if requested is not None:
        return requested
    resolutions = []
    for image in page.get_image_info():
        a, b, c, d, _, _ = image["transform"]
        width, height = math.hypot(a, b), math.hypot(c, d)
        if width > 0 and height > 0:
            resolutions.extend((image["width"] * 72 / width,
                                image["height"] * 72 / height))
    # Nie powiększamy skanów 200 DPI do 300 DPI. Limit ogranicza rozmiar rastrów.
    return max(72, min(300, round(max(resolutions)))) if resolutions else 300


def page_format(page):
    width, height = page.rect.width * 25.4 / 72, page.rect.height * 25.4 / 72
    short, long = sorted((width, height))
    formats = {"A0": (841, 1189), "A1": (594, 841), "A2": (420, 594),
               "A3": (297, 420), "A4": (210, 297), "A5": (148, 210),
               "A6": (105, 148), "Letter": (215.9, 279.4), "Legal": (215.9, 355.6)}
    label = next((name for name, (w, h) in formats.items()
                  if abs(short - w) <= 2 and abs(long - h) <= 2), "niestandardowy")
    orientation = "poziom" if width > height else "pion"
    return f"{label}, {orientation}, {width:.1f} × {height:.1f} mm"


def anonymize(source, destination, dpi=None, margin=1.0, progress=print,
              compression="jpeg", quality=85):
    """Nie kopiuje żadnych obiektów źródłowego PDF do dokumentu wynikowego."""
    temp_path = None
    try:
        with pdf.open(source) as original, pdf.open() as result:
            if original.needs_pass:
                raise ValueError("plik jest chroniony hasłem")
            if not original.is_pdf or not len(original):
                raise ValueError("plik nie jest niepustym dokumentem PDF")
            regions = [redaction_rects(page, margin) for page in original]
            total = sum(map(len, regions))
            if not total:
                raise ValueError("brak adnotacji anonimizacji; plik nie został zapisany")
            for page, rects in zip(original, regions):
                # Wyłączamy adnotacje: maski nanosimy sami bezpośrednio na piksele.
                page_dpi = rendering_dpi(page, dpi)
                pix = page.get_pixmap(dpi=page_dpi, colorspace=pdf.csRGB,
                                      alpha=False, annots=False)
                for rect in rects:
                    pix.set_rect(pixel_rect(rect, page, pix), (0, 0, 0))
                output_page = result.new_page(width=page.rect.width, height=page.rect.height)
                if compression == "jpeg":
                    # Kompresja dopiero PO usunięciu pikseli; oryginalny JPEG
                    # nigdy nie trafia do dokumentu wynikowego.
                    output_page.insert_image(output_page.rect,
                                             stream=pix.tobytes("jpeg", jpg_quality=quality))
                else:
                    output_page.insert_image(output_page.rect, pixmap=pix)
                del pix
                progress(f"  strona {page.number + 1}/{len(original)} "
                         f"({(page.number + 1) / len(original):.0%}), "
                         f"{page_format(page)}; "
                         f"prostokąty: {len(rects)}, {page_dpi} DPI, {compression}"
                         + (" — brak oznaczeń na tej stronie" if not rects else ""))
            # Nowy plik, bez zapisu przyrostowego i bez starych strumieni obrazów.
            fd, name = tempfile.mkstemp(prefix=".anon-", suffix=".pdf", dir=destination.parent)
            os.close(fd)
            temp_path = Path(name)
            progress("  zapis i kompresja…")
            result.save(temp_path, garbage=4, deflate=True)
            with pdf.open(temp_path) as check:
                if len(check) != len(original):
                    raise RuntimeError("nieprawidłowa liczba stron wyniku")
                for page in check:
                    if (list(page.annots() or ()) or page.get_text().strip()
                            or len(page.get_images()) != 1):
                        raise RuntimeError("wynik nie jest dokumentem wyłącznie rastrowym")
            os.replace(temp_path, destination)
            temp_path = None
            return len(original), total
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)


def main():
    # Windows może używać lokalnej strony kodowej przy przekierowaniu wyjścia.
    # Znak spoza kodowania (także w nazwie pliku) nie może przerwać anonimizacji.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="backslashreplace")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=Path("pdf"), help="katalog wejściowy (pdf)")
    parser.add_argument("--output", type=Path, default=Path("pdf-anon"), help="katalog wynikowy (pdf-anon)")
    parser.add_argument("--dpi", type=int, default=None,
                        help="stałe DPI; domyślnie rozdzielczość skanu, maks. 300")
    parser.add_argument("--compression", choices=("jpeg", "lossless"), default="jpeg",
                        help="kompresja obrazów (jpeg); lossless daje większe pliki")
    parser.add_argument("--quality", type=int, default=85, help="jakość JPEG: 1–100 (85)")
    parser.add_argument("--margin", type=float, default=1, help="zapas wokół maski w punktach PDF (1)")
    parser.add_argument("--overwrite", action="store_true", help="nadpisuj istniejące wyniki")
    args = parser.parse_args()
    if (args.dpi is not None and args.dpi < 72) or not math.isfinite(args.margin) or args.margin < 0:
        parser.error("DPI musi wynosić co najmniej 72, a margines musi być skończony i nieujemny")
    if not 1 <= args.quality <= 100:
        parser.error("jakość JPEG musi należeć do zakresu 1–100")
    source_dir, output_dir = args.input.resolve(), args.output.resolve()
    if not source_dir.is_dir():
        parser.error(f"brak katalogu wejściowego: {source_dir}")
    if source_dir == output_dir:
        parser.error("katalog wynikowy musi być inny niż wejściowy")
    files = sorted(p for p in source_dir.iterdir() if p.is_file() and p.suffix.lower() == ".pdf")
    if not files:
        parser.error("brak plików PDF w katalogu wejściowym")
    output_dir.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    ok = errors = pages = masks = 0
    log = lambda message: print(message, flush=True)
    for index, source in enumerate(files, 1):
        destination = output_dir / source.name
        log(f"[{index}/{len(files)}] {source.name}")
        try:
            if destination.exists() and os.path.samefile(source, destination):
                raise ValueError("wynik wskazuje plik źródłowy")
            if destination.exists() and not args.overwrite:
                raise FileExistsError("wynik już istnieje; użyj --overwrite, aby zastąpić")
            count, rectangles = anonymize(source, destination, args.dpi, args.margin, log,
                                         args.compression, args.quality)
            pages += count
            masks += rectangles
            ok += 1
            log(f"  OK → {destination} ({destination.stat().st_size / 1024**2:.1f} MiB)")
        except Exception as exc:
            errors += 1
            log(f"  BŁĄD: {exc}")
        log(f"Postęp plików: {index}/{len(files)} ({index / len(files):.0%})")
    log(f"Gotowe: {ok} plików, {pages} stron, {masks} prostokątów; "
        f"błędy: {errors}; czas: {time.monotonic() - started:.1f} s")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())

"""Grafische Oberfläche für Blechzeichnungen (Ofen- und QS-Blech)."""

import math
import os
import sys
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

import blech

EINSTELLUNGEN = os.path.join(os.path.expanduser("~"), ".blechzeichnung_ordner")


def _zahl(text, name, optional=False):
    text = text.strip().replace(",", ".")
    if not text:
        if optional:
            return None
        raise blech.BlechFehler(f"Bitte {name} eingeben.")
    try:
        return float(text)
    except ValueError:
        raise blech.BlechFehler(f"{name}: '{text}' ist keine Zahl.") from None


def _bogen_punkte(p1, p2, bulge, n=40):
    """Polyliniensegment mit Bulge in Punkte zerlegen (für die Vorschau)."""
    if abs(bulge) < 1e-12:
        return [p2]
    winkel = 4 * math.atan(bulge)
    dx, dy = p2[0] - p1[0], p2[1] - p1[1]
    sehne = math.hypot(dx, dy)
    r = sehne / (2 * math.sin(winkel / 2))
    # Mittelpunkt: von der Sehnenmitte senkrecht versetzt
    mx, my = (p1[0] + p2[0]) / 2, (p1[1] + p2[1]) / 2
    abstand = r * math.cos(winkel / 2)
    cx, cy = mx - dy / sehne * abstand, my + dx / sehne * abstand
    a1 = math.atan2(p1[1] - cy, p1[0] - cx)
    r = abs(r)
    return [(cx + r * math.cos(a1 + winkel * i / n),
             cy + r * math.sin(a1 + winkel * i / n)) for i in range(1, n + 1)]


def _polylinie(punkte):
    pts = [punkte[0][:2]]
    for i, (x, y, b) in enumerate(punkte):
        q = punkte[(i + 1) % len(punkte)]
        pts += _bogen_punkte((x, y), q[:2], b)
    return pts


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Blechzeichnung")
        self.geometry("1050x700")
        self.minsize(820, 600)
        self.blech = None

        self.art = tk.StringVar(value="Ofen")
        self.breite = tk.StringVar()
        self.radius1 = tk.StringVar()
        self.radius2 = tk.StringVar()
        self.hoehe = tk.StringVar(value=f"{blech.HOEHE_SEITE:g}")
        self.zugabe = tk.StringVar(value=f"{blech.MAX_ZUGABE:g}")
        self.rand = tk.StringVar()
        self.bemassung = tk.BooleanVar(value=True)
        self.ordner = tk.StringVar(value=self._lade_ordner())

        links = ttk.Frame(self, padding=10)
        links.pack(side="left", fill="y")
        rechts = ttk.Frame(self, padding=(0, 10, 10, 10))
        rechts.pack(side="left", fill="both", expand=True)

        art = ttk.LabelFrame(links, text="Blechart", padding=6)
        art.pack(fill="x")
        for wert in ("Ofen", "QS"):
            ttk.Radiobutton(art, text=f"{wert}-Blech", value=wert,
                            variable=self.art,
                            command=self._art_geaendert).pack(side="left", padx=4)

        werte = ttk.LabelFrame(links, text="Maße [mm]", padding=6)
        werte.pack(fill="x", pady=(8, 0))
        self.zeilen = {}
        for zeile, (key, text, var) in enumerate([
            ("breite", "Breite (Scheibe)", self.breite),
            ("r1", "Radius", self.radius1),
            ("r2", "Radius 2 (unten)", self.radius2),
        ]):
            lbl = ttk.Label(werte, text=text)
            lbl.grid(row=zeile, column=0, sticky="w", pady=2)
            ent = ttk.Entry(werte, textvariable=var, width=12)
            ent.grid(row=zeile, column=1, pady=2, padx=(6, 0))
            ent.bind("<Return>", lambda e: self.erstellen())
            self.zeilen[key] = (lbl, ent)

        extra = ttk.LabelFrame(links, text="Einstellungen", padding=6)
        extra.pack(fill="x", pady=(8, 0))
        for zeile, (text, var) in enumerate([
            ("Höhe an den Seiten", self.hoehe),
            ("max. Mehrbreite", self.zugabe),
            ("Langloch vom Rand", self.rand),
        ]):
            ttk.Label(extra, text=text).grid(row=zeile, column=0, sticky="w", pady=2)
            ttk.Entry(extra, textvariable=var, width=12).grid(
                row=zeile, column=1, pady=2, padx=(6, 0))
        self.bemassung_box = ttk.Checkbutton(extra, text="Radiusmaß einzeichnen",
                                             variable=self.bemassung)
        self.bemassung_box.grid(row=3, column=0, columnspan=2, sticky="w")

        ttk.Label(links, text="Beschriftung (mehrzeilig)").pack(anchor="w", pady=(8, 0))
        self.text = tk.Text(links, width=30, height=3)
        self.text.pack(fill="x")

        ordner = ttk.Frame(links)
        ordner.pack(fill="x", pady=(8, 0))
        ttk.Label(ordner, text="Speicherort").pack(anchor="w")
        ttk.Entry(ordner, textvariable=self.ordner, width=24).pack(side="left", fill="x", expand=True)
        ttk.Button(ordner, text="…", width=3, command=self._ordner_waehlen).pack(side="left", padx=(4, 0))

        knoepfe = ttk.Frame(links)
        knoepfe.pack(fill="x", pady=(12, 0))
        ttk.Button(knoepfe, text="Vorschau", command=self.vorschau).pack(side="left", expand=True, fill="x")
        ttk.Button(knoepfe, text="DXF erstellen", command=self.erstellen).pack(side="left", expand=True, fill="x", padx=(6, 0))

        self.info = ttk.Label(links, text="", justify="left", font=("Consolas", 9))
        self.info.pack(anchor="w", pady=(12, 0))

        self.canvas = tk.Canvas(rechts, background="white", highlightthickness=1,
                                highlightbackground="#bbb")
        self.canvas.pack(fill="both", expand=True)
        self.canvas.bind("<Configure>", lambda e: self._zeichne())

        self._art_geaendert()

    # ------------------------------------------------------------ Eingaben
    def _art_geaendert(self):
        qs = self.art.get() == "QS"
        self.zeilen["r1"][0].configure(text="Radius 1 (oben)" if qs else "Radius")
        lbl, ent = self.zeilen["r2"]
        if qs:
            lbl.grid()
            ent.grid()
        else:
            lbl.grid_remove()
            ent.grid_remove()
        self.bemassung.set(not qs)
        self.blech = None
        self._zeichne()

    def _lade_ordner(self):
        try:
            with open(EINSTELLUNGEN, encoding="utf-8") as f:
                ordner = f.read().strip()
            if os.path.isdir(ordner):
                return ordner
        except OSError:
            pass
        return os.path.join(os.path.expanduser("~"), "Desktop") \
            if os.path.isdir(os.path.join(os.path.expanduser("~"), "Desktop")) \
            else os.getcwd()

    def _ordner_waehlen(self):
        ordner = filedialog.askdirectory(initialdir=self.ordner.get() or None)
        if ordner:
            self.ordner.set(ordner)
            try:
                with open(EINSTELLUNGEN, "w", encoding="utf-8") as f:
                    f.write(ordner)
            except OSError:
                pass

    def _berechne(self):
        breite = _zahl(self.breite.get(), "Breite")
        r1 = _zahl(self.radius1.get(), "Radius")
        hoehe = _zahl(self.hoehe.get(), "Höhe")
        zugabe = _zahl(self.zugabe.get(), "Mehrbreite")
        rand = _zahl(self.rand.get(), "Langloch vom Rand", optional=True)
        if self.art.get() == "Ofen":
            return blech.berechne("ofen", breite, r1, hoehe_seite=hoehe,
                                  zugabe=zugabe, langloch_rand=rand)
        r2 = _zahl(self.radius2.get(), "Radius 2")
        return blech.berechne("qs", breite, r2, r1, hoehe_seite=hoehe,
                              zugabe=zugabe, langloch_rand=rand)

    # ------------------------------------------------------------ Aktionen
    def vorschau(self):
        try:
            self.blech = self._berechne()
        except blech.BlechFehler as e:
            self.blech = None
            self.info.configure(text="")
            self._zeichne()
            messagebox.showerror("Blechzeichnung", str(e))
            return False
        self.info.configure(text=blech.zusammenfassung(self.blech))
        self._zeichne()
        return True

    def erstellen(self):
        if not self.vorschau():
            return
        ordner = self.ordner.get().strip() or os.getcwd()
        if not os.path.isdir(ordner):
            messagebox.showerror("Blechzeichnung", f"Ordner nicht gefunden:\n{ordner}")
            return
        pfad = os.path.join(ordner, blech.dateiname(self.blech))
        if os.path.exists(pfad) and not messagebox.askyesno(
                "Blechzeichnung", f"{os.path.basename(pfad)} existiert schon.\nÜberschreiben?"):
            return
        try:
            blech.schreibe_dxf(self.blech, pfad, self.text.get("1.0", "end"),
                               self.bemassung.get())
        except Exception as e:  # z. B. Datei in AutoCAD geöffnet
            messagebox.showerror("Blechzeichnung", f"Speichern fehlgeschlagen:\n{e}")
            return
        self.info.configure(text=blech.zusammenfassung(self.blech)
                            + f"\n\nGespeichert:\n{pfad}")

    # ------------------------------------------------------------ Vorschau
    def _zeichne(self):
        c = self.canvas
        c.delete("all")
        w, h = c.winfo_width(), c.winfo_height()
        if self.blech is None:
            c.create_text(w / 2, h / 2, text="Maße eingeben und „Vorschau“ klicken",
                          fill="#888")
            return
        b = self.blech
        _, f_hoehe, _, f_gez = b.format
        rand = 30
        # Blechformat (gezeichnete Größe) als Rahmen, Blech links unten darin
        massstab = min((w - 2 * rand) / f_gez, (h - 2 * rand) / (f_hoehe - blech.FORMAT_RAND))
        ox = (w - f_gez * massstab) / 2
        oy = (h + (f_hoehe - blech.FORMAT_RAND) * massstab) / 2

        def p(x, y):
            return ox + x * massstab, oy - y * massstab

        c.create_rectangle(*p(0, 0), *p(f_gez, f_hoehe - blech.FORMAT_RAND),
                           outline="#ccc", dash=(4, 3))
        c.create_text(*p(f_gez, f_hoehe - blech.FORMAT_RAND), anchor="ne",
                      text=f"Format {b.format[0]} {b.format[1]}x{b.format[2]}",
                      fill="#999")
        for punkte, farbe in [(b.kontur, "#0077cc")] + [(l, "#cc3300") for l in b.langloecher]:
            pts = [k for xy in _polylinie(punkte) for k in p(*xy)]
            c.create_line(*pts, fill=farbe, width=2)
        c.create_text(*p(b.breite / 2, b.hoehe / 2), fill="#555",
                      text=f"{b.breite:g} mm")


def main():
    if len(sys.argv) > 1:      # Kommandozeile: blech_gui.exe ofen 1909 1424
        blech.main()
        return
    App().mainloop()


if __name__ == "__main__":
    main()

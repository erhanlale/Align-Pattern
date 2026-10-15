"""Blechzeichnungen (Ofen-Blech und QS-Blech) als DXF erzeugen.

Alles in einer Datei: ohne Argumente startet die Oberfläche,
mit Argumenten die Kommandozeile (python blech.py ofen 1909 1424).

Koordinaten in mm. Der linke Rand liegt bei x = 0, der tiefste Punkt der
Unterkante bei y = 0. Die Kontur wird als geschlossene LWPOLYLINE mit Bulges
(Bögen) gezeichnet, die 5-mm-Eckrundungen sind direkt eingerechnet.

Alle Bögen hängen nach unten durch (Mittelpunkt oben), wie in den
Beispielzeichnungen Blech_Ofen_1909_1424.dxf und Blech_qs_1909_1431_1417.dxf.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import sys
from dataclasses import dataclass, field

try:                      # Tkinter nur für die Oberfläche nötig
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk
except ImportError:       # pragma: no cover
    tk = None

# Blechformate: Name -> (Höhe, Länge, gezeichnete Länge)
FORMATE = [
    ("S", 1000, 2000, 1980),
    ("M", 1250, 2500, 2480),
    ("L", 1500, 3000, 2980),
]
FORMAT_RAND = 20          # gezeichnet wird Format minus 20 mm (auch für die Höhe)
MAX_ZUGABE = 400          # Blech darf bis zu 400 mm breiter sein als die Scheibe
ECKEN_RADIUS = 5.0
HOEHE_SEITE = 100.0       # Höhe an den Seiten (Ecke Unterkante -> Oberkante)

LANGLOCH_RAND_OFEN = 170.0  # Langloch-Mitte vom Seitenrand (waagrecht gemessen)
LANGLOCH_RAND_QS = 82.0
LANGLOCH_OBEN = 55.0      # Ofen: Langloch-Mitte unterhalb der Oberkante
LANGLOCH_ABSTAND = 80.0   # Abstand der beiden Bogenmittelpunkte
LANGLOCH_RADIUS = 20.0

LAYER_KONTUR = ("alu", 140)
LAYER_TEXT = ("text-035", 50)
LAYER_BEMASSUNG = ("dimension", 82)


class BlechFehler(ValueError):
    pass


@dataclass
class Kante:
    """Ober- oder Unterkante: Gerade (radius None) oder Kreisbogen."""
    radius: float | None
    mitte: tuple[float, float] | None = None   # Kreismittelpunkt

    def y(self, x: float, y_gerade: float = 0.0) -> float:
        if self.radius is None:
            return y_gerade
        cx, cy = self.mitte
        return cy - math.sqrt(self.radius ** 2 - (x - cx) ** 2)


@dataclass
class Blech:
    art: str                       # "Ofen" oder "QS"
    scheibe: float                 # eingegebene Breite (Scheibe)
    breite: float                  # gezeichnete Breite
    format: tuple                  # (Name, Höhe, Länge, gez. Länge)
    hoehe: float                   # Gesamthöhe (Bounding Box)
    radius_oben: float | None
    radius_unten: float
    kontur: list = field(default_factory=list)      # [(x, y, bulge), ...]
    langloecher: list = field(default_factory=list) # je [(x, y, bulge), ...]
    mitte_oben: tuple | None = None
    mitte_unten: tuple | None = None


# ---------------------------------------------------------------- Geometrie

def _bogen_hoehe(radius: float | None, halbe: float) -> float:
    """Stichhöhe eines Bogens über der halben Sehne."""
    if radius is None:
        return 0.0
    return radius - math.sqrt(radius * radius - halbe * halbe)


def _hoehe_gesamt(breite, r_oben, r_unten, hoehe_seite) -> float:
    # Tiefster Punkt = Mitte der Unterkante, höchster = obere Ecken
    return _bogen_hoehe(r_unten, breite / 2) + hoehe_seite


def waehle_format(scheibe, r_oben, r_unten, hoehe_seite=HOEHE_SEITE,
                  zugabe=MAX_ZUGABE):
    """Kleinstes passendes Format und gezeichnete Breite bestimmen."""
    if scheibe <= 0:
        raise BlechFehler("Breite muss größer als 0 sein.")
    radien = [r for r in (r_oben, r_unten) if r is not None]
    for r in radien:
        if r <= scheibe / 2:
            raise BlechFehler(
                f"Radius {r:g} ist zu klein für Breite {scheibe:g} "
                f"(Radius muss größer als Breite/2 = {scheibe / 2:g} sein).")
    # Breite muss kleiner als 2R bleiben (sonst keine Sehne mehr)
    max_bogen = min(2 * r for r in radien) - 2.0
    for fmt in FORMATE:
        name, f_hoehe, f_laenge, gez = fmt
        if scheibe > gez:
            continue
        breite = min(scheibe + zugabe, gez, max_bogen)
        breite = max(breite, scheibe)
        if _hoehe_gesamt(breite, r_oben, r_unten, hoehe_seite) > f_hoehe - FORMAT_RAND:
            # Mit weniger Zugabe passt es evtl. noch ins Format
            if _hoehe_gesamt(scheibe, r_oben, r_unten, hoehe_seite) > f_hoehe - FORMAT_RAND:
                continue
            lo, hi = scheibe, breite
            for _ in range(60):
                mid = (lo + hi) / 2
                if _hoehe_gesamt(mid, r_oben, r_unten, hoehe_seite) <= f_hoehe - FORMAT_RAND:
                    lo = mid
                else:
                    hi = mid
            breite = math.floor(lo)
            breite = max(breite, scheibe)
        return fmt, breite
    raise BlechFehler(
        f"Breite {scheibe:g} passt auf kein Blechformat "
        f"(max. {FORMATE[-1][3]} mm bzw. Höhe zu groß).")


def _bulge(mitte, p1, p2):
    """Bulge für den kleineren Bogen von p1 nach p2 um mitte."""
    a1 = math.atan2(p1[1] - mitte[1], p1[0] - mitte[0])
    a2 = math.atan2(p2[1] - mitte[1], p2[0] - mitte[0])
    d = (a2 - a1 + math.pi) % (2 * math.pi) - math.pi
    return math.tan(d / 4)


def _verrundung_linie_kreis(x_linie, innen_richtung, kreis_m, kreis_r,
                            innerhalb, ecke, r):
    """Eckenradius zwischen senkrechter Linie und Kreis.

    innen_richtung: +1 wenn das Blech rechts der Linie liegt, -1 links.
    innerhalb: True wenn das Blech im Kreis liegt.
    Liefert (Tangentenpunkt Linie, Tangentenpunkt Kreis, Mittelpunkt).
    """
    cx = x_linie + innen_richtung * r
    d = kreis_r - r if innerhalb else kreis_r + r
    dx = cx - kreis_m[0]
    if d * d < dx * dx:
        raise BlechFehler("Eckenradius lässt sich nicht konstruieren.")
    w = math.sqrt(d * d - dx * dx)
    cy = min((kreis_m[1] + w, kreis_m[1] - w), key=lambda v: abs(v - ecke[1]))
    m = (cx, cy)
    t_linie = (x_linie, cy)
    t_kreis = (kreis_m[0] + (cx - kreis_m[0]) * kreis_r / d,
               kreis_m[1] + (cy - kreis_m[1]) * kreis_r / d)
    return t_linie, t_kreis, m


def _ecke(x_linie, innen_richtung, kante: Kante, ecke, ist_oben, r):
    """Verrundung an einer Ecke -> (Punkt auf Seite, Punkt auf Kante, Mitte)."""
    if kante.radius is None:
        # Gerade Ober-/Unterkante
        vy = -1 if ist_oben else 1
        m = (x_linie + innen_richtung * r, ecke[1] + vy * r)
        return (x_linie, m[1]), (m[0], ecke[1]), m
    # Mittelpunkt liegt oben: Unterkante -> Blech im Kreis, Oberkante -> außen
    return _verrundung_linie_kreis(x_linie, innen_richtung, kante.mitte,
                                   kante.radius, not ist_oben, ecke, r)


def _langloch(mitte, winkel, abstand=LANGLOCH_ABSTAND, r=LANGLOCH_RADIUS):
    """Geschlossenes Langloch als [(x, y, bulge)], gedreht um winkel (rad)."""
    tx, ty = math.cos(winkel), math.sin(winkel)
    nx, ny = -ty, tx
    h = abstand / 2
    c1 = (mitte[0] - tx * h, mitte[1] - ty * h)
    c2 = (mitte[0] + tx * h, mitte[1] + ty * h)
    # Reihenfolge wie Beispielzeichnung (im Uhrzeigersinn, Bulge -1)
    return [
        (c1[0] - nx * r, c1[1] - ny * r, -1.0),
        (c1[0] + nx * r, c1[1] + ny * r, 0.0),
        (c2[0] + nx * r, c2[1] + ny * r, -1.0),
        (c2[0] - nx * r, c2[1] - ny * r, 0.0),
    ]


def _normale(kante: Kante, x):
    """Punkt auf der Kante bei x und Einheitsvektor nach unten senkrecht dazu."""
    cx, cy = kante.mitte
    y = kante.y(x)
    return (x, y), ((x - cx) / kante.radius, (y - cy) / kante.radius)


def _schnitt_kreis(p, n, kante: Kante):
    """Schnitt des Strahls p + t*n (t >= 0) mit dem Kreis der Kante."""
    cx, cy = kante.mitte
    r = kante.radius
    fx, fy = p[0] - cx, p[1] - cy
    b = fx * n[0] + fy * n[1]
    c = fx * fx + fy * fy - r * r
    disk = b * b - c
    if disk < 0:
        raise BlechFehler("Langloch lässt sich nicht platzieren.")
    w = math.sqrt(disk)
    ts = [t for t in (-b - w, -b + w) if t >= 0]
    if not ts:
        raise BlechFehler("Langloch lässt sich nicht platzieren.")
    t = min(ts)
    return (p[0] + n[0] * t, p[1] + n[1] * t)


def _mitte_zwischen(oben: Kante, unten: Kante, x_ziel):
    """Langloch-Mitte bei x = x_ziel, mittig zwischen Ober- und Unterkante
    (senkrecht zur Oberkante gemessen). Drehwinkel = Mittel der beiden
    Tangentenwinkel."""
    x = x_ziel
    for _ in range(50):   # Punkt auf der Oberkante suchen, dessen Mitte bei x_ziel liegt
        mitte, winkel = _mitte_bei(oben, unten, x)
        fehler = mitte[0] - x_ziel
        if abs(fehler) < 1e-9:
            break
        x -= fehler
    return mitte, winkel


def _mitte_bei(oben: Kante, unten: Kante, x):
    p_o, n_o = _normale(oben, x)
    p_u = _schnitt_kreis(p_o, n_o, unten)
    mitte = ((p_o[0] + p_u[0]) / 2, (p_o[1] + p_u[1]) / 2)
    _, n_u = _normale(unten, p_u[0])
    winkel = [math.atan2(n[0], -n[1]) for n in (n_o, n_u)]
    return mitte, sum(winkel) / 2


def berechne(art: str, scheibe: float, radius_unten: float,
             radius_oben: float | None = None, hoehe_seite=HOEHE_SEITE,
             zugabe=MAX_ZUGABE, eckenradius=ECKEN_RADIUS,
             langloch_rand: float | None = None) -> Blech:
    art = art.strip().lower()
    if art == "ofen":
        art, radius_oben = "Ofen", None
    elif art == "qs":
        art = "QS"
        if radius_oben is None:
            raise BlechFehler("QS-Blech braucht Radius 1 (oben).")
    else:
        raise BlechFehler(f"Unbekannte Blechart: {art}")
    if radius_unten <= 0 or (radius_oben is not None and radius_oben <= 0):
        raise BlechFehler("Radius muss größer als 0 sein.")
    if hoehe_seite <= 2 * eckenradius:
        raise BlechFehler("Höhe an den Seiten ist zu klein.")

    fmt, breite = waehle_format(scheibe, radius_oben, radius_unten,
                                hoehe_seite, zugabe)
    h = breite / 2
    y_ecke_u = _bogen_hoehe(radius_unten, h)   # Ecken der Unterkante
    y_ecke_o = y_ecke_u + hoehe_seite          # Ecken der Oberkante

    def kreis(radius, y_ecke):
        return (h, y_ecke + math.sqrt(radius * radius - h * h))

    unten = Kante(radius_unten, kreis(radius_unten, y_ecke_u))
    oben = Kante(radius_oben, kreis(radius_oben, y_ecke_o) if radius_oben else None)

    r = eckenradius
    # Ecken: links unten, links oben, rechts oben, rechts unten
    lu = _ecke(0.0, +1, unten, (0.0, y_ecke_u), False, r)
    lo = _ecke(0.0, +1, oben, (0.0, y_ecke_o), True, r)
    ro = _ecke(breite, -1, oben, (breite, y_ecke_o), True, r)
    ru = _ecke(breite, -1, unten, (breite, y_ecke_u), False, r)

    def kanten_bulge(kante, p1, p2):
        return 0.0 if kante.radius is None else _bulge(kante.mitte, p1, p2)

    # Im Uhrzeigersinn wie die Beispielzeichnung: links hoch, oben nach rechts,
    # rechts runter, unten nach links.
    kontur = [
        (*lu[0], 0.0),                                  # linke Seite hoch
        (*lo[0], _bulge(lo[2], lo[0], lo[1])),          # Ecke links oben
        (*lo[1], kanten_bulge(oben, lo[1], ro[1])),     # Oberkante
        (*ro[1], _bulge(ro[2], ro[1], ro[0])),          # Ecke rechts oben
        (*ro[0], 0.0),                                  # rechte Seite runter
        (*ru[0], _bulge(ru[2], ru[0], ru[1])),          # Ecke rechts unten
        (*ru[1], _bulge(unten.mitte, ru[1], lu[1])),    # Unterkante
        (*lu[1], _bulge(lu[2], lu[1], lu[0])),          # Ecke links unten
    ]

    rand_min = LANGLOCH_RADIUS + eckenradius
    if oben.radius is not None:
        # Oberkante darf der Unterkante nicht zu nahe kommen
        dicke = oben.y(h) - unten.y(h)
        if dicke < 2 * rand_min:
            raise BlechFehler(
                f"Blech ist in der Mitte zu schmal ({dicke:.1f} mm) - "
                f"Radius 1 zu klein gegenüber Radius 2?")

    # Langlöcher
    #  Ofen: LANGLOCH_OBEN unter der geraden Oberkante, waagrecht.
    #  QS:   mittig zwischen Ober- und Unterkante, entlang der Bögen gedreht.
    if langloch_rand is None:
        langloch_rand = LANGLOCH_RAND_OFEN if oben.radius is None else LANGLOCH_RAND_QS
    langloecher = []
    for x in (langloch_rand, breite - langloch_rand):
        if oben.radius is None:
            mitte, winkel = (x, y_ecke_o - LANGLOCH_OBEN), 0.0
        else:
            mitte, winkel = _mitte_zwischen(oben, unten, x)
        langloecher.append(_langloch(mitte, winkel))
        # Langloch muss mit Abstand zu beiden Kanten im Blech liegen
        for k, ist_oben in ((oben, True), (unten, False)):
            if k.radius is None:
                frei = y_ecke_o - mitte[1]
            else:
                d = math.dist(mitte, k.mitte)
                frei = d - k.radius if ist_oben else k.radius - d
            if frei < rand_min:
                raise BlechFehler(
                    "Langloch passt nicht ins Blech (Radien/Höhe prüfen).")

    # Tiefster Punkt (Mitte Unterkante) liegt bei y = 0, höchster an den
    # oberen Ecken.
    return Blech(art, scheibe, breite, fmt, y_ecke_o, radius_oben,
                 radius_unten, kontur, langloecher, oben.mitte, unten.mitte)


# ---------------------------------------------------------------- DXF

def _zahl(v):
    return f"{v:g}" if v is not None else ""


def dateiname(blech: Blech, name: str = "") -> str:
    if blech.art == "Ofen":
        datei = f"Blech_Ofen_{_zahl(blech.scheibe)}_{_zahl(blech.radius_unten)}.dxf"
    else:
        datei = (f"Blech_QS_{_zahl(blech.scheibe)}_{_zahl(blech.radius_oben)}"
                 f"_{_zahl(blech.radius_unten)}.dxf")
    name = re.sub(r'[\\/:*?"<>|]+', "_", name.strip())
    return f"{name}_{datei}" if name else datei


def beschriftung(blech: Blech, bezeichnung: str = "") -> list[str]:
    """Textzeilen wie in den Beispielzeichnungen.

    Ofen: Bezeichnung, R...      QS: R1 (oben), Bezeichnung, R2 (unten)
    """
    zeilen = [z for z in bezeichnung.splitlines() if z.strip()]
    if blech.art == "Ofen":
        return zeilen + [f"R{_zahl(blech.radius_unten)}"]
    return ([f"R{_zahl(blech.radius_oben)}"] + zeilen
            + [f"R{_zahl(blech.radius_unten)}"])


def schreibe_dxf(blech: Blech, pfad: str, bezeichnung: str = "",
                 bemassung: bool | None = None) -> str:
    """DXF schreiben. bemassung=None: Radiusmaß nur beim Ofen-Blech
    (wie in den Beispielzeichnungen)."""
    try:
        import ezdxf
    except ImportError:
        raise BlechFehler("Python-Paket 'ezdxf' fehlt. Bitte installieren:\n"
                          "    pip install ezdxf") from None

    doc = ezdxf.new("R2004", setup=True)
    doc.units = ezdxf.units.MM
    for name, farbe in (LAYER_KONTUR, LAYER_TEXT, LAYER_BEMASSUNG):
        doc.layers.add(name, color=farbe)
    msp = doc.modelspace()

    attr = {"layer": LAYER_KONTUR[0]}
    msp.add_lwpolyline([(x, y, 0, 0, b) for x, y, b in blech.kontur],
                       format="xyseb", close=True, dxfattribs=attr)
    for loch in blech.langloecher:
        msp.add_lwpolyline([(x, y, 0, 0, b) for x, y, b in loch],
                           format="xyseb", close=True, dxfattribs=attr)

    # Text in der Mitte des Blechs
    tx = blech.breite / 2
    if blech.radius_oben is None:
        oben_mitte = max(p[1] for p in blech.kontur)
    else:
        oben_mitte = blech.mitte_oben[1] - blech.radius_oben
    ty = (oben_mitte + blech.mitte_unten[1] - blech.radius_unten) / 2
    mtext = msp.add_mtext("\\P".join(beschriftung(blech, bezeichnung)),
                          dxfattribs={"layer": LAYER_TEXT[0], "char_height": 20})
    mtext.set_location((tx, ty), attachment_point=5)

    if bemassung is None:
        bemassung = blech.art == "Ofen"
    if bemassung:
        dim_attr = {"layer": LAYER_BEMASSUNG[0]}
        override = {"dimtxt": 20, "dimasz": 20, "dimtad": 0,
                    "dimtih": 0, "dimtoh": 0}
        # Radius unten: Pfeil auf den Bogen links neben der Mitte
        cx, cy = blech.mitte_unten
        r = blech.radius_unten
        winkel = 270 - math.degrees(math.asin(min(0.6, blech.breite * 0.3 / r)))
        dim = msp.add_radius_dim(center=(cx, cy), radius=r, angle=winkel,
                                 text=f"R{_zahl(r)}", override=override,
                                 dxfattribs=dim_attr)
        dim.render()
        if blech.radius_oben:
            cx, cy = blech.mitte_oben
            r = blech.radius_oben
            winkel = 270 + math.degrees(math.asin(min(0.6, blech.breite * 0.3 / r)))
            dim = msp.add_radius_dim(center=(cx, cy), radius=r, angle=winkel,
                                     text=f"R{_zahl(r)}", override=override,
                                     dxfattribs=dim_attr)
            dim.render()

    if os.path.isdir(pfad):
        pfad = os.path.join(pfad, dateiname(blech))
    doc.saveas(pfad)
    return pfad


def zusammenfassung(blech: Blech) -> str:
    name, fh, fl, gez = blech.format
    zeilen = [
        f"Blech:          {blech.art}",
        f"Scheibe:        {_zahl(blech.scheibe)} mm",
        f"Blechbreite:    {blech.breite:.1f} mm (+{blech.breite - blech.scheibe:.1f})",
        f"Höhe gesamt:    {blech.hoehe:.1f} mm",
        f"Format:         {name} {fh}x{fl} (max. {gez})",
    ]
    if blech.radius_oben:
        zeilen.append(f"Radius 1 oben:  {_zahl(blech.radius_oben)}")
    zeilen.append(f"Radius unten:   {_zahl(blech.radius_unten)}")
    return "\n".join(zeilen)


# ---------------------------------------------------------------- Excel

EINSTELLUNGEN = os.path.join(os.path.expanduser("~"), ".blechzeichnung.json")

# Spalten der Excel-Liste (Buchstaben). Leer = nicht verwenden.
# Änderbar in der Oberfläche unter "Excel-Spalten…".
EXCEL_FELDER = [
    ("name", "Name", "A"),
    ("stueck", "Stück", "B"),
    ("breite", "Breite", "C"),
    ("radius1", "Radius 1", "E"),
    ("radius2", "Radius 2", "G"),
    ("projektnr", "Projektnr.", "I"),
    ("projekt", "Projektname", "J"),
    ("datum", "Datum", "O"),
    ("von", "Von", "P"),
]


def lade_einstellungen() -> dict:
    try:
        with open(EINSTELLUNGEN, encoding="utf-8") as f:
            daten = json.load(f)
        if isinstance(daten, dict):
            return daten
    except (OSError, ValueError):
        pass
    return {}


def speichere_einstellungen(daten: dict):
    try:
        with open(EINSTELLUNGEN, "w", encoding="utf-8") as f:
            json.dump(daten, f, indent=2, ensure_ascii=False)
    except OSError:
        pass


def excel_spalten(einstellungen: dict | None = None) -> dict:
    gespeichert = (einstellungen or lade_einstellungen()).get("spalten", {})
    return {key: gespeichert.get(key, standard).strip().upper()
            for key, _, standard in EXCEL_FELDER}


def _excel_zahl(text: str, name: str, optional=False):
    """Zahl aus Excel-Text, auch '6.101' oder '6101,5'. '-' gilt als leer."""
    t = text.strip().replace(" ", "").replace("\u00a0", "")
    if t in ("", "-", "–", "0"):
        if optional:
            return None
        raise BlechFehler(f"Excel: {name} fehlt.")
    if re.fullmatch(r"\d{1,3}(\.\d{3})+(,\d+)?", t):
        t = t.replace(".", "")
    try:
        return float(t.replace(",", "."))
    except ValueError:
        raise BlechFehler(f"Excel: {name} '{text}' ist keine Zahl.") from None


def aus_excel_zeile(werte: dict) -> dict:
    """Werte einer Excel-Zeile -> Eingaben für das Blech.

    Radius 2 leer oder '-' -> Ofen-Blech, sonst QS-Blech.
    """
    werte = {k: str(v or "").strip() for k, v in werte.items()}
    breite = _excel_zahl(werte.get("breite", ""), "Breite")
    r1 = _excel_zahl(werte.get("radius1", ""), "Radius 1")
    r2 = _excel_zahl(werte.get("radius2", ""), "Radius 2", optional=True)
    projekt = " ".join(t for t in (werte.get("projektnr"), werte.get("projekt")) if t)
    stueck = werte.get("stueck", "")
    rest = "  ".join(t for t in (f"{stueck} Stk" if stueck else "",
                                 werte.get("datum"), werte.get("von")) if t)
    return {
        "art": "Ofen" if r2 is None else "QS",
        "breite": breite,
        "radius1": r1,
        "radius2": r2,
        "name": werte.get("name", ""),
        "text": "\n".join(t for t in (projekt, rest) if t),
    }


def lies_excel_zeile(spalten: dict | None = None) -> dict:
    """Aktive Zeile aus dem geöffneten Excel lesen (nur Windows)."""
    spalten = spalten or excel_spalten()
    try:
        import win32com.client
    except ImportError:
        raise BlechFehler("Für Excel wird das Paket 'pywin32' gebraucht:\n"
                          "    pip install pywin32") from None
    try:
        excel = win32com.client.GetActiveObject("Excel.Application")
    except Exception:
        raise BlechFehler("Excel ist nicht geöffnet.") from None
    try:
        zelle = excel.ActiveCell
        if zelle is None:
            raise BlechFehler("In Excel ist keine Zelle ausgewählt.")
        blatt, zeile = zelle.Worksheet, zelle.Row
        werte = {key: blatt.Range(f"{sp}{zeile}").Text
                 for key, sp in spalten.items() if sp}
    except BlechFehler:
        raise
    except Exception:
        raise BlechFehler("Excel antwortet nicht - bitte die Zellbearbeitung "
                          "beenden (Enter oder Esc) und nochmal versuchen.") from None
    werte["_zeile"] = zeile
    return werte


# ---------------------------------------------------------------- Oberfläche

_TkBasis = tk.Tk if tk else object


def _eingabe_zahl(text, name, optional=False):
    text = text.strip().replace(",", ".")
    if not text:
        if optional:
            return None
        raise BlechFehler(f"Bitte {name} eingeben.")
    try:
        return float(text)
    except ValueError:
        raise BlechFehler(f"{name}: '{text}' ist keine Zahl.") from None


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


class App(_TkBasis):
    def __init__(self):
        super().__init__()
        self.title("Blechzeichnung")
        self.geometry("1050x800")
        self.minsize(820, 700)
        self.blech = None

        self.art = tk.StringVar(value="Ofen")
        self.breite = tk.StringVar()
        self.radius1 = tk.StringVar()
        self.radius2 = tk.StringVar()
        self.hoehe = tk.StringVar(value=f"{HOEHE_SEITE:g}")
        self.zugabe = tk.StringVar(value=f"{MAX_ZUGABE:g}")
        self.rand = tk.StringVar()
        self.bemassung = tk.BooleanVar(value=True)
        self.name = tk.StringVar()
        self.einstellungen = lade_einstellungen()
        self.ordner = tk.StringVar(value=self._lade_ordner())

        links = ttk.Frame(self, padding=10)
        links.pack(side="left", fill="y")
        rechts = ttk.Frame(self, padding=(0, 10, 10, 10))
        rechts.pack(side="left", fill="both", expand=True)

        excel = ttk.LabelFrame(links, text="Excel", padding=6)
        excel.pack(fill="x")
        ttk.Button(excel, text="Aktive Zeile übernehmen",
                   command=self.aus_excel).pack(side="left", expand=True, fill="x")
        ttk.Button(excel, text="Spalten…",
                   command=self._spalten_dialog).pack(side="left", padx=(6, 0))

        art = ttk.LabelFrame(links, text="Blechart", padding=6)
        art.pack(fill="x", pady=(8, 0))
        for wert in ("Ofen", "QS"):
            ttk.Radiobutton(art, text=f"{wert}-Blech", value=wert,
                            variable=self.art,
                            command=self._art_geaendert).pack(side="left", padx=4)

        werte = ttk.LabelFrame(links, text="Maße [mm]", padding=6)
        werte.pack(fill="x", pady=(8, 0))
        self.zeilen = {}
        for zeile, (key, text, var) in enumerate([
            ("name", "Name", self.name),
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
        ordner = self.einstellungen.get("ordner", "")
        if ordner and os.path.isdir(ordner):
            return ordner
        return os.path.join(os.path.expanduser("~"), "Desktop") \
            if os.path.isdir(os.path.join(os.path.expanduser("~"), "Desktop")) \
            else os.getcwd()

    def _ordner_waehlen(self):
        ordner = filedialog.askdirectory(initialdir=self.ordner.get() or None)
        if ordner:
            self.ordner.set(ordner)
            self.einstellungen["ordner"] = ordner
            speichere_einstellungen(self.einstellungen)

    def _spalten_dialog(self):
        fenster = tk.Toplevel(self)
        fenster.title("Excel-Spalten")
        fenster.transient(self)
        fenster.resizable(False, False)
        rahmen = ttk.Frame(fenster, padding=10)
        rahmen.pack()
        ttk.Label(rahmen, text="Spaltenbuchstaben der Excel-Liste\n"
                               "(leer = nicht verwenden)").grid(
            row=0, column=0, columnspan=2, sticky="w", pady=(0, 6))
        aktuell = excel_spalten(self.einstellungen)
        felder = {}
        for zeile, (key, text, _) in enumerate(EXCEL_FELDER, start=1):
            ttk.Label(rahmen, text=text).grid(row=zeile, column=0, sticky="w", pady=1)
            var = tk.StringVar(value=aktuell[key])
            ttk.Entry(rahmen, textvariable=var, width=6).grid(
                row=zeile, column=1, padx=(8, 0), pady=1)
            felder[key] = var

        def speichern():
            spalten = {k: v.get().strip().upper() for k, v in felder.items()}
            falsch = [s for s in spalten.values() if s and not re.fullmatch(r"[A-Z]{1,3}", s)]
            if falsch:
                messagebox.showerror("Excel-Spalten", f"Ungültige Spalte: {falsch[0]}",
                                     parent=fenster)
                return
            self.einstellungen["spalten"] = spalten
            speichere_einstellungen(self.einstellungen)
            fenster.destroy()

        ttk.Button(rahmen, text="Speichern", command=speichern).grid(
            row=len(EXCEL_FELDER) + 1, column=0, columnspan=2, sticky="ew", pady=(8, 0))
        fenster.grab_set()

    def aus_excel(self):
        try:
            werte = lies_excel_zeile(excel_spalten(self.einstellungen))
            daten = aus_excel_zeile(werte)
        except BlechFehler as e:
            messagebox.showerror("Excel", str(e))
            return
        self.art.set(daten["art"])
        self._art_geaendert()
        self.name.set(daten["name"])
        self.breite.set(_zahl(daten["breite"]))
        self.radius1.set(_zahl(daten["radius1"]))
        self.radius2.set(_zahl(daten["radius2"]))
        self.text.delete("1.0", "end")
        self.text.insert("1.0", daten["text"])
        self.vorschau()

    def _berechne(self):
        breite = _eingabe_zahl(self.breite.get(), "Breite")
        r1 = _eingabe_zahl(self.radius1.get(), "Radius")
        hoehe = _eingabe_zahl(self.hoehe.get(), "Höhe")
        zugabe = _eingabe_zahl(self.zugabe.get(), "Mehrbreite")
        rand = _eingabe_zahl(self.rand.get(), "Langloch vom Rand", optional=True)
        if self.art.get() == "Ofen":
            return berechne("ofen", breite, r1, hoehe_seite=hoehe,
                                  zugabe=zugabe, langloch_rand=rand)
        r2 = _eingabe_zahl(self.radius2.get(), "Radius 2")
        return berechne("qs", breite, r2, r1, hoehe_seite=hoehe,
                              zugabe=zugabe, langloch_rand=rand)

    # ------------------------------------------------------------ Aktionen
    def vorschau(self):
        try:
            self.blech = self._berechne()
        except BlechFehler as e:
            self.blech = None
            self.info.configure(text="")
            self._zeichne()
            messagebox.showerror("Blechzeichnung", str(e))
            return False
        self.info.configure(text=zusammenfassung(self.blech))
        self._zeichne()
        return True

    def erstellen(self):
        if not self.vorschau():
            return
        ordner = self.ordner.get().strip() or os.getcwd()
        if not os.path.isdir(ordner):
            messagebox.showerror("Blechzeichnung", f"Ordner nicht gefunden:\n{ordner}")
            return
        pfad = os.path.join(ordner, dateiname(self.blech, self.name.get()))
        if os.path.exists(pfad) and not messagebox.askyesno(
                "Blechzeichnung", f"{os.path.basename(pfad)} existiert schon.\nÜberschreiben?"):
            return
        try:
            text = self.name.get().strip() + "\n" + self.text.get("1.0", "end")
            schreibe_dxf(self.blech, pfad, text, self.bemassung.get())
        except Exception as e:  # z. B. Datei in AutoCAD geöffnet
            messagebox.showerror("Blechzeichnung", f"Speichern fehlgeschlagen:\n{e}")
            return
        self.info.configure(text=zusammenfassung(self.blech)
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
        massstab = min((w - 2 * rand) / f_gez, (h - 2 * rand) / (f_hoehe - FORMAT_RAND))
        ox = (w - f_gez * massstab) / 2
        oy = (h + (f_hoehe - FORMAT_RAND) * massstab) / 2

        def p(x, y):
            return ox + x * massstab, oy - y * massstab

        c.create_rectangle(*p(0, 0), *p(f_gez, f_hoehe - FORMAT_RAND),
                           outline="#ccc", dash=(4, 3))
        c.create_text(*p(f_gez, f_hoehe - FORMAT_RAND), anchor="ne",
                      text=f"Format {b.format[0]} {b.format[1]}x{b.format[2]}",
                      fill="#999")
        for punkte, farbe in [(b.kontur, "#0077cc")] + [(l, "#cc3300") for l in b.langloecher]:
            pts = [k for xy in _polylinie(punkte) for k in p(*xy)]
            c.create_line(*pts, fill=farbe, width=2)
        c.create_text(*p(b.breite / 2, b.hoehe / 2), fill="#555",
                      text=f"{b.breite:g} mm")


# ---------------------------------------------------------------- CLI

def main(argv=None):
    if argv is None:
        argv = sys.argv[1:]
    if not argv:          # ohne Argumente -> Oberfläche
        if tk is None:
            sys.exit("Tkinter fehlt - bitte Maße als Argumente angeben "
                     "(python blech.py -h).")
        App().mainloop()
        return
    p = argparse.ArgumentParser(description="Blechzeichnung als DXF erzeugen.")
    sub = p.add_subparsers(dest="art", required=True)
    ofen = sub.add_parser("ofen", help="Ofen-Blech (Unterkante = Bogen)")
    ofen.add_argument("breite", type=float)
    ofen.add_argument("radius", type=float)
    qs = sub.add_parser("qs", help="QS-Blech (Ober- und Unterkante = Bogen)")
    qs.add_argument("breite", type=float)
    qs.add_argument("radius1", type=float, help="Radius oben")
    qs.add_argument("radius2", type=float, help="Radius unten")
    excel = sub.add_parser("excel", help="aktive Zeile der geöffneten Excel-Liste")
    for s in (ofen, qs, excel):
        s.add_argument("-o", "--ausgabe", default=None,
                       help="Datei oder Ordner (Standard: zuletzt in der "
                            "Oberfläche gewählter Ordner, sonst aktueller Ordner)")
        s.add_argument("-t", "--text", default="",
                       help="Bezeichnung, mehrere Zeilen mit '|' trennen")
        s.add_argument("--hoehe", type=float, default=HOEHE_SEITE,
                       help=f"Höhe an den Seiten (Standard {HOEHE_SEITE:g})")
        s.add_argument("--zugabe", type=float, default=MAX_ZUGABE,
                       help=f"max. Mehrbreite (Standard {MAX_ZUGABE})")
        s.add_argument("--rand", type=float, default=None,
                       help="Langloch-Mitte vom Seitenrand (Standard Ofen "
                            f"{LANGLOCH_RAND_OFEN:g}, QS {LANGLOCH_RAND_QS:g})")
        s.add_argument("--bemassung", dest="bemassung", action="store_true",
                       default=None, help="Radiusmaß immer einzeichnen")
        s.add_argument("--ohne-bemassung", dest="bemassung",
                       action="store_false", help="kein Radiusmaß")
    a = p.parse_args(argv)
    if a.ausgabe is None:
        a.ausgabe = lade_einstellungen().get("ordner") or "."
        if not os.path.isdir(a.ausgabe):
            a.ausgabe = "."
    name = ""
    try:
        if a.art == "excel":
            werte = lies_excel_zeile()
            daten = aus_excel_zeile(werte)
            name = daten["name"]
            a.text = "|".join(t for t in [name] + daten["text"].splitlines() + [a.text] if t)
            print(f"Excel-Zeile {werte['_zeile']}: {name}")
            einstellungen = dict(hoehe_seite=a.hoehe, zugabe=a.zugabe,
                                 langloch_rand=a.rand)
            if daten["art"] == "QS":
                blech = berechne("qs", daten["breite"], daten["radius2"],
                                 daten["radius1"], **einstellungen)
            else:
                blech = berechne("ofen", daten["breite"], daten["radius1"],
                                 **einstellungen)
        elif a.art == "ofen":
            blech = berechne("ofen", a.breite, a.radius, hoehe_seite=a.hoehe,
                             zugabe=a.zugabe, langloch_rand=a.rand)
        else:
            blech = berechne("qs", a.breite, a.radius2, a.radius1,
                             hoehe_seite=a.hoehe, zugabe=a.zugabe,
                             langloch_rand=a.rand)
    except BlechFehler as e:
        p.exit(1, f"Fehler: {e}\n")
    if os.path.isdir(a.ausgabe):
        a.ausgabe = os.path.join(a.ausgabe, dateiname(blech, name))
    pfad = schreibe_dxf(blech, a.ausgabe, a.text.replace("|", "\n"),
                        a.bemassung)
    print(zusammenfassung(blech))
    print(f"Gespeichert:    {pfad}")


if __name__ == "__main__":
    main()

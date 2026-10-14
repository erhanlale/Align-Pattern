import math
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import blech  # noqa: E402


def _relativ(punkte, x0, y0):
    return [(round(x - x0, 3), round(y - y0, 3), round(b, 4)) for x, y, b in punkte]


# Kontur aus Blech_Ofen_1909_1424.dxf (Ursprung: linke Seite, Unterkante Mitte)
OFEN_1909_1424 = [
    (0.0, 402.562, 0.0), (0.0, 495.44, -0.4142), (5.0, 500.44, 0.0),
    (1975.0, 500.44, -0.4142), (1980.0, 495.44, 0.0),
    (1980.0, 402.562, -0.2036), (1978.471, 398.963, -0.4036),
    (1.529, 398.963, -0.2036),
]

# Kontur aus Blech_qs_1909_1431_1417.dxf
QS_1909_1431_1417 = [
    (0.0, 405.309, 0.0), (0.0, 491.551, -0.6576), (8.43, 495.189, 0.397),
    (1971.57, 495.189, -0.6576), (1980.0, 491.551, 0.0),
    (1980.0, 405.309, -0.2024), (1978.488, 401.726, -0.4064),
    (1.512, 401.726, -0.2024),
]


def _vergleiche(ist, soll, tol=0.01):
    assert len(ist) == len(soll)
    for a, b in zip(ist, soll):
        assert a == pytest.approx(b, abs=tol)


def test_ofen_wie_beispiel():
    b = blech.berechne("ofen", 1909, 1424)
    assert b.format[0] == "S"
    assert b.breite == 1980
    _vergleiche(_relativ(b.kontur, 0, 0), OFEN_1909_1424)
    # Langlöcher 170 vom Rand, 55 unter der Oberkante, waagrecht
    _vergleiche(_relativ(b.langloecher[0], 0, 0), [
        (130, 425.44, -1), (130, 465.44, 0), (210, 465.44, -1), (210, 425.44, 0)])
    _vergleiche(_relativ(b.langloecher[1], 0, 0), [
        (1770, 425.44, -1), (1770, 465.44, 0), (1850, 465.44, -1), (1850, 425.44, 0)])


def test_qs_wie_beispiel():
    b = blech.berechne("qs", 1909, 1417, 1431)
    assert b.breite == 1980
    _vergleiche(_relativ(b.kontur, 0, 0), QS_1909_1431_1417)


def test_qs_langloch_gedreht_und_mittig():
    b = blech.berechne("qs", 1909, 1417, 1431)
    for loch, vorzeichen in zip(b.langloecher, (-1, 1)):
        c1 = [(loch[0][i] + loch[1][i]) / 2 for i in (0, 1)]
        c2 = [(loch[2][i] + loch[3][i]) / 2 for i in (0, 1)]
        assert math.dist(c1, c2) == pytest.approx(80)
        winkel = math.degrees(math.atan2(c2[1] - c1[1], c2[0] - c1[0]))
        # Beispiel: ca. -38.6° (links) bzw. gespiegelt (rechts)
        assert abs(winkel) == pytest.approx(39.6, abs=1.0) or \
            abs(winkel) == pytest.approx(180 - 39.6, abs=1.0)
        mitte = [(c1[i] + c2[i]) / 2 for i in (0, 1)]
        oben = math.dist(mitte, b.mitte_oben) - 1431
        unten = 1417 - math.dist(mitte, b.mitte_unten)
        assert oben == pytest.approx(unten, abs=1.0)


@pytest.mark.parametrize("scheibe,breite,fmt", [
    (1000, 1400, "S"), (1700, 1980, "S"), (1980, 1980, "S"),
    (1981, 2381, "M"), (2400, 2480, "M"), (2500, 2900, "L"), (2980, 2980, "L"),
])
def test_formatwahl(scheibe, breite, fmt):
    b = blech.berechne("ofen", scheibe, 20000)
    assert b.format[0] == fmt
    assert b.breite == breite


def test_hoehe_begrenzt_zugabe():
    # Volle Zugabe (1898 breit) wäre mit R950 über 980 mm hoch -> schmaler
    b = blech.berechne("ofen", 1850, 950)
    assert b.format[0] == "S"
    assert 1850 <= b.breite < 1898
    assert b.hoehe <= b.format[1] - blech.FORMAT_RAND


@pytest.mark.parametrize("args", [
    ("ofen", 3000, 20000), ("ofen", 1000, 400), ("ofen", 1000, -2000),
    ("qs", 1900, 1500, 1000),
])
def test_fehler(args):
    with pytest.raises(blech.BlechFehler):
        blech.berechne(*args)


def test_dxf(tmp_path):
    ezdxf = pytest.importorskip("ezdxf")
    for b in (blech.berechne("ofen", 1909, 1424),
              blech.berechne("qs", 1909, 1417, 1431)):
        pfad = blech.schreibe_dxf(b, str(tmp_path), "ASH-458\n50480GL12C-2 Lite1")
        doc = ezdxf.readfile(pfad)
        assert not doc.audit().has_errors
        polys = doc.modelspace().query("LWPOLYLINE")
        assert len(polys) == 3 and all(p.closed for p in polys)
        text = doc.modelspace().query("MTEXT")[0].plain_text()
        assert "ASH-458" in text
    assert sorted(os.listdir(tmp_path)) == [
        "Blech_Ofen_1909_1424.dxf", "Blech_QS_1909_1431_1417.dxf"]

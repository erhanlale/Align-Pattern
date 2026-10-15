# Blechzeichnung (Ofen- und QS-Blech → DXF)

Erzeugt aus Breite und Radius/Radien eine DXF-Zeichnung des Blechs, so wie in
den Beispielzeichnungen `Blech_Ofen_1909_1424.dxf` und
`Blech_qs_1909_1431_1417.dxf`.

## Bedienung

**Windows-Programm:** `Blechzeichnung.exe` starten, Blechart wählen, Maße
eingeben, *DXF erstellen*. Die Datei heißt automatisch
`Blech_Ofen_<Breite>_<Radius>.dxf` bzw. `Blech_QS_<Breite>_<R1>_<R2>.dxf`.

**Python:** Alles steckt in der einen Datei `blech.py`.
Einmalig `pip install ezdxf pywin32`, dann

```
python blech.py                           # Oberfläche
python blech.py ofen 1909 1424            # Ofen-Blech: Breite Radius
python blech.py qs 1909 1431 1417         # QS-Blech: Breite Radius1 Radius2
python blech.py ofen 1909 1424 -t "ASH-458|50480GL12C-2 Lite1" -o C:\Zeichnungen
python blech.py excel                     # aktive Zeile der offenen Excel-Liste
```

## Aus Excel

In Excel die Zeile anklicken (irgendeine Zelle der Zeile), dann in der
Oberfläche **Aktive Zeile übernehmen** und **DXF erstellen** – oder direkt
`python blech.py excel` (bzw. `Blechzeichnung.exe excel`).

- Radius 2 leer oder `-` → Ofen-Blech, sonst QS-Blech.
- Datei: `<Name>_Blech_QS_<Breite>_<R1>_<R2>.dxf`, z. B.
  `ASH-468_Blech_QS_2900_6101_6141.dxf`.
- Text in der Zeichnung: Name, Projektnr. + Projektname, Stück/Datum/Von,
  dazu die Radien.
- Die Spaltenbuchstaben (Standard: Name A, Stück B, Breite C, Radius 1 E,
  Radius 2 G, Projektnr. I, Projektname J, Datum O, Von P) lassen sich unter
  **Spalten…** ändern und werden gespeichert (`%USERPROFILE%\.blechzeichnung.json`).

## Regeln

| | |
|---|---|
| Formate | S 1000×2000 (gezeichnet max. 1980), M 1250×2500 (2480), L 1500×3000 (2980) |
| Breite | Scheibe + bis zu 400 mm, aber nur so breit, wie das **kleinste** Format erlaubt, in das die Scheibe passt (1909 → 1980, Format S). Passt die Höhe nicht ins Format (Höhe − 20), wird die Mehrbreite verkleinert oder das nächste Format genommen. |
| Höhe | 100 mm an den Seiten (Ecke Unterkante bis Ecke Oberkante) |
| Ecken | R5, direkt in die Polylinie eingerechnet |
| Ofen-Blech | Oberkante gerade, Unterkante Bogen R. Langlöcher waagrecht, Mitte 170 mm vom Rand und 55 mm unter der Oberkante, mit Radiusmaß |
| QS-Blech | Oberkante Bogen R1, Unterkante Bogen R2 (beide hängen nach unten durch). Langlöcher mittig zwischen den Bögen, entlang der Bögen gedreht, Mitte 82 mm vom Rand |
| Langloch | 2 × R20, Abstand 80 (gesamt 120 × 40) |
| Layer | Kontur/Langlöcher `alu`, Text `text-035` (Höhe 20), Maß `dimension` |

Höhe, Mehrbreite und Langloch-Abstand vom Rand lassen sich in der Oberfläche
bzw. mit `--hoehe`, `--zugabe`, `--rand` ändern. Die festen Werte stehen oben
in `blech.py`.

## EXE bauen

- Automatisch: GitHub Actions (*Blechzeichnung EXE*) baut bei jeder Änderung
  in `blechzeichnung/` die EXE. Sie liegt im Lauf unter *Artifacts*.
- Lokal unter Windows: `build_exe.bat` → `dist\Blechzeichnung.exe`.

## Tests

```
pip install pytest ezdxf
python -m pytest tests
```

Die Tests vergleichen die Kontur mit den Koordinaten aus den beiden
Beispielzeichnungen.

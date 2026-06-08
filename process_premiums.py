#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Budget Guard - Praemien-Roboter
Erstellt kkPremiums.json aus den offiziellen BAG-Praemien.
1) Versucht zuerst, die aktuelle CSV automatisch von opendata.swiss zu laden.
2) Findet es keine, nimmt es eine CSV-Datei aus dem Repository.
Laeuft automatisch via GitHub Actions.
"""
import json
import os
import io
import glob
import urllib.request

import pandas as pd

DATASET = "health-insurance-premiums"
API = "https://opendata.swiss/api/3/action/package_show?id=" + DATASET
OUTPUT = "kkPremiums.json"
NEEDED_COLS = {
    "Versicherer", "Kanton", "Region", "Altersklasse",
    "Unfalleinschluss", "Tariftyp", "Franchise", "Prämie",
}

# BAG-Nummer -> Kassen-Name (Stand 2026). Unbekannte Nummern werden gemeldet.
INS = {
    "8": "CSS", "32": "Aquilana", "134": "Einsiedler KK", "194": "Sumiswalder",
    "246": "KK Steffisburg", "290": "Concordia", "312": "Atupri", "343": "Avenir",
    "360": "Luzerner Hinterland", "376": "KPT", "455": "ÖKK", "509": "Sympany",
    "780": "Glarner", "820": "curaulta", "881": "EGK", "923": "SLKK", "941": "sodalis",
    "966": "vita surselva", "1040": "Visperterminen", "1113": "Vallée d'Entremont",
    "1179": "Mutuelle Neuchâteloise", "1318": "Wädenswil", "1322": "Birchmeier",
    "1384": "SWICA", "1386": "Galenos", "1401": "rhenusana", "1402": "Bildende Künstler",
    "1479": "Mutuel", "1491": "Gewerbliche KK", "1507": "AMB", "1509": "Sanitas",
    "1520": "Hotela", "1522": "Metallbau KK", "1535": "Philos", "1542": "Assura",
    "1555": "Visana", "1560": "Agrisano", "1562": "Helsana", "1568": "sana24",
    "901": "curaulta", "1570": "Galenos", "829": "KLuG",
}
MODEL = {"TAR-BASE": 0, "TAR-HAM": 1, "TAR-HMO": 2, "TAR-DIV": 3}
DROP_CANTONS = {"ZE", "ZR", "ZZ"}
HEADERS = {"User-Agent": "Mozilla/5.0 (BudgetGuard data updater)"}


def http_get(url, timeout=120):
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def valid(df):
    return NEEDED_COLS.issubset(set(df.columns)) and len(df) > 50000


def try_download_csv():
    """Versucht, die passende CH-Praemien-CSV von opendata.swiss zu laden."""
    try:
        meta = json.loads(http_get(API))
        resources = meta["result"]["resources"]
    except Exception as e:
        print("i Konnte opendata.swiss nicht erreichen:", e)
        return None
    urls = []
    for res in resources:
        url = res.get("download_url") or res.get("url") or ""
        fmt = (res.get("format") or "").upper()
        if url.lower().endswith(".csv") or fmt == "CSV":
            urls.append(url)
    for url in urls:
        try:
            raw = http_get(url)
            df = pd.read_csv(io.BytesIO(raw), encoding="utf-8-sig", dtype=str)
            if valid(df):
                print("OK CSV automatisch geladen:", url, "(" + str(len(df)) + " Zeilen)")
                return df
        except Exception:
            continue
    print("i Keine passende CSV automatisch gefunden.")
    return None


def load_local_csv():
    files = glob.glob("*.csv")
    if not files:
        return None
    path = max(files, key=os.path.getsize)
    try:
        df = pd.read_csv(path, encoding="utf-8-sig", dtype=str)
        if valid(df):
            print("OK Lokale CSV genutzt:", path, "(" + str(len(df)) + " Zeilen)")
            return df
        print("! " + path + " hat nicht die erwarteten Spalten - uebersprungen.")
    except Exception as e:
        print("! Lokale CSV konnte nicht gelesen werden:", e)
    return None


def build(df):
    df = df[~df["Kanton"].isin(DROP_CANTONS)].copy()
    year = 2026
    if "Geschäftsjahr" in df.columns:
        try:
            year = int(df["Geschäftsjahr"].dropna().iloc[0])
        except Exception:
            pass
    unknown = sorted(c for c in df["Versicherer"].dropna().unique() if c not in INS)
    if unknown:
        print("! Unbekannte Versicherer-Nummern (Mapping ergaenzen):", unknown)
    df["prem"] = pd.to_numeric(df["Prämie"], errors="coerce")
    df["reg"] = df["Region"].str.replace("PR-REG CH", "", regex=False).astype(int)
    df["age"] = df["Altersklasse"].map({"AKL-KIN": 0, "AKL-JUG": 1, "AKL-ERW": 2})
    df["acc"] = df["Unfalleinschluss"].map({"MIT-UNF": 1, "OHN-UNF": 0})
    df["mod"] = df["Tariftyp"].map(MODEL)
    df["fr"] = df["Franchise"].str.replace("FRA-", "", regex=False).astype(int)
    df["ins"] = df["Versicherer"].map(lambda c: INS.get(c, "Kasse " + str(c)))
    df = df.dropna(subset=["prem", "age", "acc", "mod"])
    g = df.groupby(["ins", "Kanton", "reg", "age", "acc", "mod", "fr"], as_index=False)["prem"].min()
    g["prem"] = g["prem"].round(2)
    insurers = sorted(g["ins"].unique().tolist())
    ii = {n: i for i, n in enumerate(insurers)}
    franchises = sorted(int(x) for x in g["fr"].unique().tolist())
    fi = {f: i for i, f in enumerate(franchises)}
    by = {}
    for r in g.itertuples(index=False):
        by.setdefault(r.Kanton, []).append(
            [ii[r.ins], int(r.reg), int(r.age), int(r.acc), int(r.mod), fi[int(r.fr)], float(r.prem)]
        )
    return {
        "year": year,
        "insurers": insurers,
        "models": ["Standard", "Hausarzt", "HMO", "Telmed/Andere"],
        "franchises": franchises,
        "byCanton": by,
    }


def main():
    df = try_download_csv()
    if df is None:
        df = load_local_csv()
    if df is None:
        print("i Keine Daten zum Verarbeiten - bestehende kkPremiums.json bleibt unveraendert.")
        return
    out = build(df)
    with open(OUTPUT, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, separators=(",", ":"))
    print("OK " + OUTPUT + " erstellt - Jahr " + str(out["year"]) +
          ", " + str(len(out["byCanton"])) + " Kantone, " + str(len(out["insurers"])) + " Kassen.")


if __name__ == "__main__":
    main()

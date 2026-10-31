"""Erzeugt ein kleines, formatgetreues HRDF-ZIP und eine atlas-CSV fuer die Tests.

Linien (erfunden, an Bern–Neuenburg angelehnt):
* IR 66  BN–KZ–INS–NE   stuendlich 06–21, hin :13, zurueck asymmetrisch
* S 5    INS–GAMP–NE    halbstuendlich (Taktfahrt *Z mit Anzahl/Taktzeit)
* RE     BN–(KZ Durchfahrt)–INS   nur gerade Stunden (120)
* B 101  Bus (muss rausgefiltert werden)
"""
from __future__ import annotations

import io
import zipfile
from pathlib import Path

STATIONS = {  # nummer: (abk, name, lat, lon)
    8507000: ("BN", "Bern", 46.94883, 7.43913),
    8504489: ("KZ", "Kerzers", 46.97578, 7.19458),
    8504488: ("INS", "Ins", 47.00563, 7.10646),
    8504487: ("GAMP", "Gampelen", 47.01216, 7.05705),
    8504221: ("NE", "Neuchâtel", 46.99677, 6.93563),
    8504100: ("FR", "Fribourg/Freiburg", 46.80313, 7.15108),
}


def t(m: int | None, neg: bool = False) -> str:
    if m is None:
        return " " * 6
    return ("-" if neg else " ") + f"{m // 60:03d}{m % 60:02d}"


def stop(num: int, arr: int | None, dep: int | None, neg: bool = False) -> str:
    name = STATIONS.get(num, ("", "Irgendwo"))[1]
    line = f"{num:07d} {name[:21]:<21}{t(arr, neg)} {t(dep, neg)}"
    assert line[29:35] == t(arr, neg) and line[36:42] == t(dep, neg)
    return line


def z(fnr: int, admin="000011", n=None, step=None) -> str:
    s = f"*Z {fnr:06d} {admin}   101"
    if n:
        s = s.ljust(22) + f"{n:03d} {step:03d}"
    return s


def fplan() -> str:
    L = []
    fnr = 1
    for h in range(6, 22):
        b = h * 60
        L += [z(fnr), "*G IR  8507000 8504221", "*L 66      8507000 8504221",
              "*A VE 8507000 8504221 000000",
              stop(8507000, None, b + 13), stop(8504489, b + 30, b + 31),
              stop(8504488, b + 36, b + 38), stop(8504221, b + 48, None)]
        fnr += 1
        # Rueckfahrt NE ab :11 (asymmetrisch, Spiegel waere :12), ab INS wieder symmetrisch
        L += [z(fnr), "*G IR  8504221 8507000", "*L 66      8504221 8507000",
              stop(8504221, None, b + 11), stop(8504488, b + 22, b + 24),
              stop(8504489, b + 29, b + 30), stop(8507000, b + 47, None)]
        fnr += 1
    # S5 halbstuendlich als Taktfahrt: erste 06:05, 31 Wiederholungen alle 30'
    L += [z(fnr, n=31, step=30), "*G S   8504488 8504221", "*L S5     8504488 8504221",
          stop(8504488, None, 6 * 60 + 5), stop(8504487, 6 * 60 + 9, 6 * 60 + 10),
          "8500999 Zwischenhalt Fiktiv   00615  00616",
          stop(8504221, 6 * 60 + 22, None)]
    fnr += 1
    L += [z(fnr, n=31, step=30), "*G S   8504221 8504488", "*L S5     8504221 8504488",
          stop(8504221, None, 6 * 60 + 38), "8500999 Zwischenhalt Fiktiv   00644  00645",
          stop(8504487, 6 * 60 + 50, 6 * 60 + 51), stop(8504488, 6 * 60 + 55, None)]
    fnr += 1
    # RE nur gerade Stunden, KZ als Durchfahrt; Bitfeld 000001 (nur bestimmte Tage)
    for h in range(6, 22, 2):
        b = h * 60
        L += [z(fnr), "*G RE  8507000 8504488", "*L #0000001", "*A VE 8507000 8504488 000001",
              stop(8507000, None, b + 40), stop(8504489, b + 55, b + 55, neg=True),
              stop(8504488, b + 59, None)]
        fnr += 1
        L += [z(fnr), "*G RE  8504488 8507000", "*L #0000001", "*A VE 8504488 8507000 000001",
              stop(8504488, None, b + 1), stop(8504489, b + 5, b + 5, neg=True),
              stop(8507000, b + 20, None)]
        fnr += 1
    # Bus
    L += [z(fnr, "000801"), "*G B   8507000 8504100", "*L 101",
          stop(8507000, None, 7 * 60), stop(8504100, 8 * 60, None)]
    return "\n".join(L) + "\n"


def make(dir_: Path) -> tuple[Path, Path]:
    dir_.mkdir(parents=True, exist_ok=True)
    zp = dir_ / "hrdf_mini.zip"
    with zipfile.ZipFile(zp, "w") as zf:
        zf.writestr("ECKDATEN", "14.12.2025\n12.12.2026\nFahrplan 2026\n")
        days = 364
        every = "F" * (days // 4 + 1)
        # 000001: nur jeder 2. Tag laeuft NICHT -> Muster 1010 = A
        zf.writestr("BITFELD", f"000001 {'A' * (days // 4 + 1)}\n000002 {every}\n")
        zf.writestr("LINIE", "0000001 K RE5\n0000001 N T Bern-Ins\n")
        zf.writestr("BAHNHOF", "".join(f"{n:07d}     {v[1]}$<1>${v[0]}$<3>\n" for n, v in STATIONS.items())
                    + "8500999     Zwischenhalt Fiktiv$<1>\n")
        zf.writestr("BFKOORD_WGS", "".join(f"{n:07d}   {v[3]:.6f}  {v[2]:.6f}      450     % {v[1]}\n"
                                           for n, v in STATIONS.items()))
        zf.writestr("FPLAN", fplan().encode("utf-8"))
    csvp = dir_ / "actual-date-swiss-service-point.csv"
    with open(csvp, "w", encoding="utf-8") as f:
        f.write("sloid;number;numberShort;uicCountryCode;designationOfficial;abbreviation;"
                "meansOfTransport;wgs84East;wgs84North;validFrom;validTo\n")
        for n, (a, name, lat, lon) in STATIONS.items():
            if a == "GAMP":   # fehlt bewusst -> kommt aus HRDF
                continue
            f.write(f"ch:1:sloid:{n % 100000};{n};{n % 100000};85;{name};{a};TRAIN;{lon};{lat};2020-01-01;9999-12-31\n")
        f.write("ch:1:sloid:12345;8512345;12345;85;Bern, Bahnhof;;BUS;7.44;46.95;2020-01-01;9999-12-31\n")
    return zp, csvp


if __name__ == "__main__":
    print(make(Path(__file__).parent / "fixtures"))

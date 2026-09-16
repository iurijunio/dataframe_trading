"""Diagnostico rapido da deteccao de rolagem. Nao e teste; e para olhar."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import db_manager as db
from core import rollovers as roll

SYM = "WIN$N"
con = db.connect(read_only=True)

print("=== rolagens detectadas por calendario mas SEM gap grande ===")
rows = con.execute(
    "SELECT date, prev_close, next_open, gap_points FROM rollovers "
    "WHERE symbol = ? AND detected_by = 'calendar' ORDER BY date",
    [SYM],
).fetchall()
for d, pc, no, gap in rows:
    print(f"  {d}  {pc} -> {no}  gap {gap:+d}")
print(f"  ({len(rows)} de 30)")

print("\n=== maiores gaps que NAO sao rolagem (dias de noticia) ===")
for prev_d, d, pc, no, gap in roll.unexplained_gaps(con, SYM, threshold=2500)[:8]:
    print(f"  {prev_d} -> {d}   {pc} -> {no}   gap {gap:+d}")

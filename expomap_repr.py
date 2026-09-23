from pathlib import Path

html = Path(r"d:\habsy\scrapping\expomap_event_probe.html").read_text(encoding="utf-8")
i = 223036
snip = html[i : i + 80]
Path(r"d:\habsy\scrapping\expomap_repr.txt").write_text(repr(snip), encoding="utf-8")
print("ok")

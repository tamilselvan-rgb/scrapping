import json
from pathlib import Path

html = Path(r"d:\habsy\scrapping\expomap_event_probe.html").read_text(encoding="utf-8")
idx = html.rfind("eventPageStore")
start = html.rfind("self.__next_f.push(", 0, idx)
print("start", start, "idx", idx)
# argument begins at [
arg_start = html.find("[", start)
# parse one JSON value with raw_decode
decoder = json.JSONDecoder()
value, end = decoder.raw_decode(html, arg_start)
print(type(value), len(value) if isinstance(value, list) else None)
payload = value[1] if isinstance(value, list) else ""
print("payload type", type(payload), "len", len(payload))
j = payload.find('"event":{')
Path(r"d:\habsy\scrapping\expomap_payload_snip.txt").write_text(
    payload[j : j + 2500], encoding="utf-8"
)
print("event at", j, "payload_len", len(payload))

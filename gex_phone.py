"""Temporary phone-based GEX feed -> page6.html (GEX Heat iPhone app via phone-harness).

Run:   phone-harness < gex_phone.py            (read + write files, no push)
       PUSH=1 phone-harness < gex_phone.py     (also git add/commit/pull --rebase/push)
Env:   TICKERS=NVDA,SPY  (override list)   DEBUG=1  (print cell colours / OCR)
Needs: iPhone Mirroring connected + phone locked. Uses macOS Vision for OCR (system python).
"""
import os, re, json, time, subprocess, html
from datetime import date, datetime, timedelta
import Quartz, Vision
from Foundation import NSURL

DIR = os.path.expanduser("~/gex-dashboard")
DATA_FILE = os.path.join(DIR, "gex_data_phone.json")
HTML_FILE = os.path.join(DIR, "page6.html")
TICKERS = os.environ.get("TICKERS", "TSLA,NVDA,AAPL,SPY,QQQ,IWM").split(",")
MWF = {"TSLA", "NVDA", "AAPL"}          # same expiry rule as gex_a: Mon/Wed/Fri expiries, else next day
DEBUG = os.environ.get("DEBUG") == "1"
PUSH = os.environ.get("PUSH") == "1"
IMG = tuple(screen_info()["img_px"])

# ── expiry (same rule as gex_a.py get_expiry) ────────────────────────────────
def get_expiry(ticker):
    today = date.today(); wd = today.weekday()
    if ticker in MWF:
        if wd in (0, 2, 4): return today
        return today + timedelta(days={1: 1, 3: 1, 5: 2, 6: 1}[wd])
    return today

# ── OCR / screen helpers ─────────────────────────────────────────────────────
class Shot:
    def __init__(self, path):
        h = Vision.VNImageRequestHandler.alloc().initWithURL_options_(NSURL.fileURLWithPath_(path), None)
        r = Vision.VNRecognizeTextRequest.alloc().init()
        r.setRecognitionLevel_(Vision.VNRequestTextRecognitionLevelAccurate)
        ok, err = h.performRequests_error_([r], None)
        if not ok: raise RuntimeError(err)
        self.items = []
        for o in r.results() or []:
            c = o.topCandidates_(1)
            if c:
                b = o.boundingBox()
                self.items.append((str(c[0].string()).strip(), b.origin.x + b.size.width / 2, 1 - b.origin.y - b.size.height / 2, b.size.width))
        src = Quartz.CGImageSourceCreateWithURL(NSURL.fileURLWithPath_(path), None)
        img = Quartz.CGImageSourceCreateImageAtIndex(src, 0, None)
        self.W, self.H = Quartz.CGImageGetWidth(img), Quartz.CGImageGetHeight(img)
        self.data = Quartz.CGDataProviderCopyData(Quartz.CGImageGetDataProvider(img))
        self.bpr = Quartz.CGImageGetBytesPerRow(img); self.bpp = Quartz.CGImageGetBitsPerPixel(img) // 8
    def px(self, fx, fy):
        o = int(fy * self.H) * self.bpr + int(fx * self.W) * self.bpp
        return tuple(self.data[o:o + 3])
    def find(self, text, ymin=0, ymax=1):
        for t in self.items:
            if t[0].upper() == text.upper() and ymin <= t[2] <= ymax: return t
    def dash_left_of(self, item):
        """True if a minus dash is drawn just left of an OCR box (Vision drops faint grey dashes)."""
        _, cx, cy, w = item
        left = cx - w / 2
        vals = [sum(self.px(left - 0.004 - i * 0.003, cy)) / 3 for i in range(8)]
        return max(vals) - min(vals) >= 15 and max(vals) < 120   # grey dash on near-black cell
    def has(self, sub): return any(sub.lower() in t[0].lower() for t in self.items)

def look():
    time.sleep(0.4); return Shot(screenshot())

def tap_frac(x, y): tap_image_point(x * IMG[0], y * IMG[1], image_size=IMG)

def wait_for(pred, timeout=10, step=1.0):
    end = time.time() + timeout; s = None
    while time.time() < end:
        s = look()
        if pred(s): return s
        time.sleep(step)
    return None

# ── navigation ───────────────────────────────────────────────────────────────
IN_APP = lambda s: not s.has("Top Hit") and not s.has("Suggestions") and (s.has("Ask, and watch") or s.has("NET GEX") or s.has("FAVORITES") or s.find("GEX", 0.9, 1) is not None or s.has("Heatmap"))

def launch():
    """Get into the app. If it is already on screen do nothing; otherwise Spotlight -> tap the Top Hit icon."""
    s = look()
    if IN_APP(s): return
    for attempt in range(2):
        if not s.has("Top Hit"):
            home(); time.sleep(1); open_app("GEX heat")
            s = wait_for(lambda s: s.has("Top Hit") or IN_APP(s), 10)
            if s is None: continue
        if s.has("Top Hit"):
            tap_frac(0.17, 0.195)
            s = wait_for(IN_APP, 10)
        if s and IN_APP(s): return
    raise RuntimeError("could not open the GEX Heat app")

def close_overlay():
    """Tap the top handle of the sparkle overlay to go back to the previous screen."""
    s = look()
    if s.has("Ask, and watch"): tap_frac(0.5, 0.108); time.sleep(1.5)

def normalize():
    """Get the app to a known state: crosshair cleared, bottom sheet at full height (tab bar visible)."""
    s = look()
    for _ in range(3):
        c = s.find("Clear", 0.6, 1)
        if c: tap_frac(c[1], c[2]); time.sleep(1); s = look()
        if s.has("Ask, and watch") or s.find("GEX", 0.9, 1): return s
        # sheet in a half-height detent hides the tab bar: tap its drag handle (just above the ticker header)
        anchor = next((t for t in s.items if t[0] in ("Heatmap", "BID") and t[2] > 0.4), None)   # sheet labels sit ~0.06 below its handle
        if not anchor: return s
        tap_frac(0.5, anchor[2] - 0.06); time.sleep(2); s = look()
    return s

def chip_match(text, t):
    """OCR reads chips with icon noise ('= SPY', '• AAPLI', 'IW M'): compare letters only."""
    c = re.sub(r"[^A-Z]", "", text.upper())
    return c == t or (len(c) <= len(t) + 2 and (c.startswith(t) or c.endswith(t)))

def goto_ticker(t):
    s = normalize()
    if not s.has("Ask, and watch"):
        tap_frac(0.5, 0.936)                   # sparkle button -> ticker chips
        s = wait_for(lambda s: s.has("Ask, and watch"), 5)
        if not s: return None
    time.sleep(1.5); s = look()                # let the overlay finish animating before reading chip positions
    chip = next((x for x in s.items if 0.3 < x[2] < 0.7 and chip_match(x[0], t)), None)
    if DEBUG: print("   chip", t, chip)
    if not chip:
        if DEBUG: print("   items", [(x[0], round(x[1],2), round(x[2],2)) for x in s.items][:30])
        return None
    tap_frac(chip[1], chip[2])
    s = wait_for(lambda s: not s.has("Ask, and watch") and s.find("GEX", 0.9, 1) is not None, 12)
    if DEBUG: print("   after chip: GEX tab", bool(s))
    if not s: return None
    g = s.find("GEX", 0.9, 1); tap_frac(g[1], g[2])
    s = wait_for(lambda s: s.has("NET GEX") or s.find("Heatmap") is not None, 10)
    if s and not s.has("NET GEX"):
        h = s.find("Heatmap"); tap_frac(h[1], h[2])
        s = wait_for(lambda s: s.has("NET GEX"), 6)
    time.sleep(1.5)                            # let numbers settle
    return look() if s else None

# ── parsing ──────────────────────────────────────────────────────────────────
VAL = re.compile(r"^([-–−+])?\s*(\d+(?:\.\d+)?)([MKB])$")
MULT = {"K": 1e3, "M": 1e6, "B": 1e9}
def parse_val(txt, shot=None, fx=None, fy=None):
    m = VAL.match(txt.replace("$", "").strip())
    if not m: return None
    v = float(m.group(2)) * MULT[m.group(3)]
    return -v if m.group(1) in ('-', '–', '−') else v

def parse(shot, ticker, expiry_str):
    items = shot.items
    lab = lambda name: shot.find(name)
    def above(name):
        l = lab(name)
        if not l: return None
        c = [t for t in items if abs(t[1] - l[1]) < 0.12 and 0 < l[2] - t[2] < 0.05]
        return c[0][0] if c else None
    net = parse_val(above("NET GEX") or "")
    cw = re.sub(r"\D", "", above("CALL WALL") or ""); pw = re.sub(r"\D", "", above("PUT WALL") or "")
    tk = next((x for x in items if x[2] < 0.6 and x[1] < 0.4 and x[0].upper().split()[-1:] == [ticker]), None)
    spot = None
    for t in items:
        m = re.match(r"(\d{1,4}\.\d\d)\b", t[0])
        if tk and m and abs(t[2] - tk[2]) < 0.02 and t[1] > 0.4: spot = float(m.group(1)); break
    hdr = shot.find(expiry_str)
    strikes = {}
    if hdr:
        ladder = sorted((t for t in items if re.fullmatch(r"\d{2,4}", t[0]) and t[1] < 0.25 and 0.25 < t[2] < 0.97), key=lambda t: t[2])
        vals_ = [int(t[0]) for t in ladder]            # on screen the strikes must strictly descend top -> bottom
        bad = {ladder[i][0] for i in range(1, len(ladder) - 1) if vals_[i - 1] > vals_[i + 1] and not (vals_[i + 1] < vals_[i] < vals_[i - 1])}   # OCR outlier between two consistent neighbours
        for t in items:
            if re.fullmatch(r"\d{2,4}", t[0]) and t[1] < 0.25 and t[0] not in bad:
                cells = [c for c in items if abs(c[2] - t[2]) < 0.012 and abs(c[1] - hdr[1]) < 0.06 and parse_val(c[0]) is not None]
                if cells:
                    c = cells[0]; v = parse_val(c[0])
                    r_, g_, b_ = shot.px(c[1] - c[3] / 2 - 0.012, c[2])   # cell background just left of the text
                    if r_ > 110 and r_ > g_ * 1.6: v = -abs(v)             # red cell = negative GEX
                    elif g_ > 110 and g_ > r_ * 1.4: v = abs(v)            # green cell = positive GEX
                    elif v > 0 and sum((r_, g_, b_)) < 150 and shot.dash_left_of(c): v = -v   # faint grey minus dropped by OCR
                    if DEBUG: print("  ", t[0], c[0], "bg", shot.px(c[1] - 0.05, c[2]), shot.px(c[1] + 0.05, c[2]))
                    strikes[float(t[0])] = v
    return net, int(cw) if cw else None, int(pw) if pw else None, spot, strikes, hdr is not None

def collect_all_strikes(ticker, exp, strikes, spot=None):
    """Scroll the whole strike ladder (to the top, then down to the bottom) and merge every strike seen,
    like the website table gave us. End of list = the strike labels on screen stop changing (twice in a row)."""
    normalize()                                         # sheet must be full height or the list will not scroll
    w = screen_info()["window"]; at = (w["x"] + w["w"] / 2, w["y"] + w["h"] * 0.6)
    allk = dict(strikes)
    labels = lambda sh: frozenset(t[0] for t in sh.items if re.fullmatch(r"\d{2,4}", t[0]) and t[1] < 0.25 and 0.25 < t[2] < 0.95)
    for direction in ("up", "down"):
        prev, same = None, 0
        for _ in range(30):
            scroll(direction, 0.4, at=at); time.sleep(1.6)
            sh = look()
            for k, v in parse(sh, ticker, exp)[4].items():
                if k in allk and abs(abs(allk[k]) - abs(v)) < 1e-6 * max(abs(v), 1) and allk[k] != v:
                    v = -abs(v)                            # same strike read twice with different signs: a dropped minus is the usual error
                allk[k] = v
            lab = labels(sh)
            same = same + 1 if lab == prev else 0
            if same >= 2: break
            prev = lab
        normalize()                                     # overscrolling past the top/bottom can collapse the sheet: re-expand
    for k1 in list(allk):                               # OCR misreads one digit of a strike label (360 -> 260): same value, labels 100 apart
        for k2 in list(allk):
            if k1 in allk and k2 in allk and k1 != k2 and abs(k1 - k2) == 100 and allk[k1] == allk[k2]:
                allk.pop(k1 if abs(k1 - (spot or k2)) > abs(k2 - (spot or k1)) else k2)
    if spot:                                            # the app only shows +/-30% around spot: drop OCR junk outside it
        allk = {k: v for k, v in allk.items() if abs(k - spot) / spot <= 0.30}
    if DEBUG: print("   strikes collected:", len(allk))
    return allk

def max_pain(strikes, spot):
    rows = sorted(strikes.items(), reverse=True)   # table order: high strike -> low strike
    flips = [rows[i][0] for i in range(len(rows) - 1) if rows[i][1] * rows[i + 1][1] < 0]
    if flips: return min(flips, key=lambda x: abs(x - spot))
    return min(rows, key=lambda kv: abs(kv[1]))[0] if rows else None

def fmt(v):
    if v is None: return None, None
    return (round(v / 1e9, 1), "B") if abs(v) >= 1e9 else (round(v / 1e6, 1), "M")

def make_entry(now, net, cw, pw, spot, strikes, expiry_str):
    top = sorted(strikes.items(), key=lambda kv: -abs(kv[1]))[:3] + [(None, None)] * 3
    e = {"time": now.strftime("%H:%M"), "spot": spot, "expiry": expiry_str, "mp": max_pain(strikes, spot), "cw": cw, "pw": pw}
    for i, (k, v) in enumerate(top[:3]):
        pre = "gex" if i == 0 else f"gex{i + 1}"
        d, u = fmt(v); e[f"{pre}_display"], e[f"{pre}_unit"], e[f"{pre}_at"] = d, u, k
    d, u = fmt(net); e["net_gamma_display"], e["net_gamma_unit"] = d, u
    e["call_gamma_display"] = e["call_gamma_unit"] = e["put_gamma_display"] = e["put_gamma_unit"] = None
    return e

# ── files ────────────────────────────────────────────────────────────────────
def load_today():
    today = date.today().strftime("%Y-%m-%d")
    if os.path.exists(DATA_FILE):
        d = json.load(open(DATA_FILE, encoding="utf-8"))
        if d.get("date") == today: return d
    return {"date": today, "snapshots": {}}

def write_html(stored, now):
    base = open(os.path.join(DIR, "page4.html"), encoding="utf-8").read()
    style = re.search(r"<style>.*?</style>", base, re.S).group(0)
    # reuse page4's JS renderer verbatim, swap data/tickers/headers
    script = re.search(r"<script>.*</script>", base, re.S).group(0)
    script = re.sub(r"const data = .*?;\nconst tickers = .*?;\n",
                    lambda m: f"const data = {json.dumps(stored['snapshots'], ensure_ascii=False)};\nconst tickers = {json.dumps(TICKERS)};\n", script, count=1, flags=re.S)
    script = script.replace("<th>Call Gamma</th><th>Put Gamma</th><th>MP</th>", "<th>Call Gamma</th><th>Put Gamma</th><th>MP</th>")
    page = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>GEX Dashboard (phone) {stored['date']}</title>
{style}
</head>
<body>
<div class="header">
  <span class="header-title">📱 GEX Dashboard · Page 6 (phone feed, temporary) &nbsp;{stored['date']} &nbsp;|&nbsp; Last updated: {now.strftime('%Y-%m-%d %H:%M')} PST</span>
  <div class="page-links">
    <a href="index.html" class="page-link">Page 1</a>
    <a href="page2.html" class="page-link">Page 2</a>
    <a href="page3.html" class="page-link">Page 3</a>
    <a href="page4.html" class="page-link">Page 4</a>
  </div>
</div>
<div class="tabs" id="tab-container"></div>
<div id="panel-container"></div>
<div class="footer">Source: GEX Heat iPhone app via OCR · GEX/GEX2/GEX3 = three largest |GEX| strikes visible in the app's heatmap for the ticker's target expiry · Net Gamma = app's NET GEX · CW/PW = app's call/put wall · small values' signs may be misread</div>
{script}
</body>
</html>
"""
    open(HTML_FILE, "w", encoding="utf-8").write(page)

def git_push(now):
    msg = f"update-phone {now.strftime('%Y-%m-%d %H:%M')}"
    try:
        run = lambda *a: subprocess.run(["git", "-C", DIR, *a], check=True)
        run("add", "page6.html", "gex_data_phone.json"); run("commit", "-m", msg)
        run("pull", "--rebase"); run("push"); print("Git push successful")
    except subprocess.CalledProcessError as e:
        print("Git push failed:", e)

# ── main ─────────────────────────────────────────────────────────────────────
t0 = time.time(); now = datetime.now()
launch()
stored = load_today(); ok_list, failed = [], []
for t in TICKERS:
    exp = get_expiry(t).strftime("%m/%d")
    try:
        shot = goto_ticker(t)
        if not shot: raise RuntimeError("navigation failed")
        net, cw, pw, spot, strikes, found = parse(shot, t, exp)
        if net is None or not strikes or spot is None:
            shot = look()
            net, cw, pw, spot, strikes, found = parse(shot, t, exp)   # one re-read for OCR flakes
        if strikes: strikes = collect_all_strikes(t, exp, strikes, spot)
        if net is None or not strikes or spot is None:
            raise RuntimeError(f"incomplete read (net={net}, spot={spot}, strikes={len(strikes)}, expiry col {exp} visible={found})")
        if DEBUG: print("   signed:", {int(k): round(v / 1e6, 2) for k, v in sorted(strikes.items())})
        stored["snapshots"].setdefault(t, []).append(make_entry(now, net, cw, pw, spot, strikes, exp))
        close_overlay()
        ok_list.append(t); print(f"OK   {t} {exp} spot {spot} net {net/1e6:.0f}M cw {cw} pw {pw} strikes {len(strikes)}")
    except Exception as e:
        failed.append(t); print(f"FAIL {t}: {e}")
if ok_list:
    json.dump(stored, open(DATA_FILE, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    write_html(stored, now)
    if PUSH: git_push(now)
print(f"done in {time.time() - t0:.0f}s ok={ok_list} failed={failed}")

#!/usr/bin/env python3
"""
בונה את אתר קטלוג הסניפים מדוחות Priority.

שימוש:
    python build.py --src D:\\priority\\zabanCatalog ^
                    --img-root D:\\priority\\system\\mail\\Pics ^
                    --img-root D:\\priority\\system\\images

כל דוח (.htm/.html/.mht) הופך ל-<סניף>/index.html. התמונות נשמרות פעם אחת
ב-assets/img/ ומשותפות לכל הסניפים — אותה תמונת מוצר חוזרת בהרבה סניפים.

הפניות לתמונות נפתרות לפי שם הקובץ מול תיקיות --img-root, ולכן לא משנה אם
הדוח כותב אותן ככתובת HTTPS, כנתיב file:/// או כנתיב יחסי.

קבצי MHT נקראים חלק-אחרי-חלק, כך שקובץ ג'יגה לא נטען לזיכרון.
"""

import argparse, base64, binascii, html as htmlmod, io, os, quopri, re, sqlite3, sys, time
from pathlib import Path

try:
    from PIL import Image
except ImportError:
    Image = None      # בלי Pillow התמונות נשמרות בגודלן המקורי

ROOT = Path(__file__).resolve().parent
ASSETS_REL = 'assets/img'
PICS_NAMES = ('pic', 'pics')

BS = chr(92)
Q = '["' + chr(39) + ']'
NQ = '[^"' + chr(39) + '>]'

IMG_EXT = ('.gif', '.png', '.jpg', '.jpeg', '.svg', '.ico', '.bmp', '.webp')
MIME = {'jpg': 'jpeg', 'jpeg': 'jpeg', 'svg': 'svg+xml', 'ico': 'x-icon',
        'gif': 'gif', 'png': 'png', 'bmp': 'bmp', 'webp': 'webp'}

INLINE_MAX = 8000       # אייקונים קטנים מזה מוטמעים בעמוד
SHRINK_OVER = 40000     # רק קבצים גדולים מזה מוקטנים

EXT_GROUP = '(?:jpg|jpeg|png|gif|bmp|webp|ico|svg)'
REF_RE = re.compile(
    '(?i)(?:(?:src|href)\\s*=\\s*' + Q + '([^"' + chr(39) + ']+?\\.' + EXT_GROUP + ')' + Q +
    '|url\\(\\s*' + Q + '?([^)"' + chr(39) + ']+?\\.' + EXT_GROUP + ')' + Q + '?\\s*\\))')


# ---------------------------------------------------------------- MIME זורם

def _read_headers(f):
    hdrs, last = {}, None
    while True:
        line = f.readline()
        if not line or line in (b'\r\n', b'\n'):
            break
        if line[:1] in (b' ', b'\t') and last:
            hdrs[last] += ' ' + line.strip().decode('latin-1')
            continue
        if b':' in line:
            k, v = line.split(b':', 1)
            last = k.strip().decode('latin-1').lower()
            hdrs[last] = v.strip().decode('latin-1')
    return hdrs


def stream_parts(path):
    """(headers, payload) לכל חלק MIME. חלק אחד בזיכרון בכל רגע."""
    with open(path, 'rb') as f:
        top = _read_headers(f)
        m = re.search('boundary="?([^";\r\n]+)"?', top.get('content-type', ''))
        if not m:
            raise SystemExit('אין boundary בקובץ ' + str(path))
        delim = b'--' + m.group(1).encode('latin-1')

        while True:
            line = f.readline()
            if not line:
                return
            if line.startswith(delim):
                break

        while True:
            hdrs = _read_headers(f)
            buf, closing = [], False
            while True:
                line = f.readline()
                if not line:
                    closing = True
                    break
                if line.startswith(delim):
                    closing = line.startswith(delim + b'--')
                    break
                buf.append(line)
            raw = b''.join(buf)
            if raw.endswith(b'\r\n'):
                raw = raw[:-2]
            elif raw.endswith(b'\n'):
                raw = raw[:-1]
            enc = hdrs.get('content-transfer-encoding', '').lower()
            try:
                if enc == 'base64':
                    raw = base64.b64decode(re.sub(rb'\s', b'', raw))
                elif enc == 'quoted-printable':
                    raw = quopri.decodestring(raw)
            except (binascii.Error, ValueError):
                pass
            if hdrs:
                yield hdrs, raw
            if closing:
                return


# ---------------------------------------------------------------- נתיבים

def ref_key(ref):
    """שם הקובץ בלבד, באותיות קטנות. זה המפתח לזיהוי תמונה."""
    ref = ref.split('?')[0].split('#')[0]
    return os.path.basename(ref.replace(BS, '/')).strip().lower()


def resolve_local(ref, base_dir):
    """file:///d:/x.jpg, file:\\\\\\d:\\x.jpg, d:\\x.jpg או יחסי -> Path."""
    if re.match('(?i)^https?://', ref):
        return None
    p = ref.split('?')[0].split('#')[0]
    try:
        from urllib.parse import unquote
        p = unquote(p)
    except Exception:
        pass
    m = re.search('(?i)(?<![a-z0-9])([a-z]:[\\\\/].*)$', p)
    if m:
        p = m.group(1)
    else:
        p = re.sub('(?i)^file:[\\\\/]*', '', p)
    p = p.replace(BS, '/')
    path = Path(p)
    if not path.is_absolute():
        path = base_dir / p
    return path


def safe_name(name, fallback):
    name = re.sub(r'[^A-Za-z0-9._-]', '_', name.strip())
    return name if name and '.' in name else fallback


class ImageRoots:
    """איתור תמונה לפי שם קובץ בתיקיות התמונות של Priority.

    רוב התמונות יושבות ישירות בשורש תיקיית Pics, ולכן קודם כל מרכיבים את
    הנתיב ובודקים קיום — מיידי. השאר מפוזרות בתתי-תיקיות לפי תאריך
    (mail\\202108\\vs3qb\\...), ואותן מוצאים דרך אינדקס.

    האינדקס יושב ב-SQLite ולא בזיכרון: ספריית התמונות מכילה מעל מיליון
    קבצים, ומילון כזה היה תופס מאות מגה-בייט בכל ריצה. הבנייה שלו נעשית
    פעם בכמה ימים, והשאילתות קוראות מהדיסק.
    """

    def __init__(self, directories, db_path, reindex_days=7, force=False,
                 log=print):
        self.roots, self.dirs = [], []
        for d in directories:
            d = Path(d)
            if d.is_dir():
                self.roots.append(d)
                self.dirs.append((d, None))
            else:
                self.dirs.append((d, -1))

        self.db = None
        self.hits_direct = self.hits_index = 0
        if not self.roots:
            return

        db_path = Path(db_path)
        stale = True
        if db_path.exists() and not force:
            age_days = (time.time() - db_path.stat().st_mtime) / 86400
            stale = age_days > reindex_days
            if stale:
                log('אינדקס התמונות בן %.0f ימים — נבנה מחדש' % age_days)
        if stale or force:
            self._build(db_path, log)
        self.db = sqlite3.connect(str(db_path))
        self.db.execute('PRAGMA query_only = ON')

    @staticmethod
    def _inside(child, parent):
        try:
            child.relative_to(parent)
            return True
        except ValueError:
            return False

    def _build(self, db_path, log):
        tmp = db_path.with_suffix('.building')
        if tmp.exists():
            tmp.unlink()
        con = sqlite3.connect(str(tmp))
        con.execute('PRAGMA journal_mode = OFF')
        con.execute('PRAGMA synchronous = OFF')
        con.execute('CREATE TABLE img (name TEXT PRIMARY KEY, path TEXT)')
        # תיקייה שנמצאת בתוך תיקייה אחרת ברשימה תיסרק ממילא, ואין טעם
        # לעבור עליה פעמיים — בספרייה הזו זה הפרש של מאות אלפי קבצים
        tops = []
        for d in sorted(self.roots, key=lambda p: len(str(p))):
            if not any(self._inside(d, t) for t in tops):
                tops.append(d)

        t0, n = time.time(), 0
        batch = []
        for d in tops:
            for dirpath, _dirs, files in os.walk(d):
                for f in files:
                    if f.lower().endswith(IMG_EXT):
                        batch.append((f.lower(), os.path.join(dirpath, f)))
                        n += 1
                if len(batch) >= 50000:
                    con.executemany('INSERT OR IGNORE INTO img VALUES (?,?)', batch)
                    batch = []
        if batch:
            con.executemany('INSERT OR IGNORE INTO img VALUES (?,?)', batch)
        con.commit()
        con.close()
        if db_path.exists():
            db_path.unlink()
        tmp.rename(db_path)
        log('אינדקס תמונות נבנה: %d קבצים ב-%.0f שניות' % (n, time.time() - t0))

    def get(self, key):
        for d in self.roots:
            p = d / key
            try:
                if p.is_file():
                    self.hits_direct += 1
                    return p
            except OSError:
                pass
        if self.db is not None:
            row = self.db.execute('SELECT path FROM img WHERE name = ?', (key,)).fetchone()
            if row:
                p = Path(row[0])
                if p.is_file():
                    self.hits_index += 1
                    return p
        return None


# ---------------------------------------------------------------- תמונות

def shrink(raw, max_edge, quality):
    """מקטין תמונה גדולה. מחזיר None אם אין מה לשפר."""
    if Image is None or len(raw) <= SHRINK_OVER:
        return None
    try:
        im = Image.open(io.BytesIO(raw))
        im.load()
    except Exception:
        return None
    if max(im.size) <= max_edge and len(raw) < 150000:
        return None
    if im.mode not in ('RGB', 'L'):
        im = im.convert('RGB')
    im.thumbnail((max_edge, max_edge), Image.LANCZOS)
    buf = io.BytesIO()
    im.save(buf, 'JPEG', quality=quality, optimize=True, progressive=True)
    out = buf.getvalue()
    return out if len(out) < len(raw) else None


class AssetStore:
    """assets/img משותף לכל הסניפים.

    אותה תמונת מוצר מופיעה בהרבה סניפים, ולכן היא נשמרת פעם אחת בלבד.
    תמונה שכבר קיימת מריצה קודמת לא נקראת ולא מעובדת שוב — זה מה שהופך
    את הריצה היומית למהירה גם עם אלפי תמונות.
    """

    def __init__(self, root, opts):
        self.dir = root / ASSETS_REL.replace('/', os.sep)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.opts = opts
        self.on_disk = {}
        for p in self.dir.iterdir():
            if p.is_file():
                self.on_disk.setdefault(os.path.splitext(p.name)[0].lower(), p.name)
        self.resolved = {}      # key -> נתיב יחסי מתוך תיקיית סניף, או data URI
        self.used = set()
        self.added = self.reused = self.inlined = 0
        self.bytes = 0

    def _url(self, name):
        return '../' + ASSETS_REL + '/' + name

    def has(self, key):
        return key in self.resolved

    def take(self, key, loader):
        """מחזיר נתיב לשימוש ב-HTML, או None אם אין תמונה."""
        if key in self.resolved:
            return self.resolved[key]

        stem = os.path.splitext(key)[0]
        if not self.opts.refresh_assets and stem in self.on_disk:
            name = self.on_disk[stem]
            self.used.add(name)
            self.reused += 1
            self.resolved[key] = self._url(name)
            return self.resolved[key]

        try:
            raw = loader()
        except OSError:
            raw = None
        if not raw:
            return None

        name = safe_name(key, 'img%04d.png' % len(self.resolved))
        small = shrink(raw, self.opts.max_edge, self.opts.quality)
        if small is not None:
            raw = small
            name = re.sub(r'\.[^.]+$', '', name) + '.jpg'

        if len(raw) <= INLINE_MAX:
            mt = MIME.get(name.rsplit('.', 1)[-1].lower(), 'png')
            value = 'data:image/' + mt + ';base64,' + base64.b64encode(raw).decode('ascii')
            self.inlined += 1
        else:
            (self.dir / name).write_bytes(raw)
            self.on_disk[os.path.splitext(name)[0].lower()] = name
            self.used.add(name)
            self.added += 1
            self.bytes += len(raw)
            value = self._url(name)

        self.resolved[key] = value
        return value

    def prune(self):
        """מוחק תמונות שאף סניף כבר לא מפנה אליהן."""
        removed = 0
        for p in self.dir.iterdir():
            if p.is_file() and p.name not in self.used:
                try:
                    p.unlink()
                    removed += 1
                except OSError:
                    pass
        return removed


# ---------------------------------------------------------------- המרה

def convert(src_path, out_dir, store, roots, opts):
    out_dir.mkdir(parents=True, exist_ok=True)
    page, texts = None, {}
    embedded = set()        # מפתחות שהגיעו מתוך ה-MHT עצמו

    if src_path.suffix.lower() in ('.mht', '.mhtml'):
        for hdrs, payload in stream_parts(src_path):
            ctype = hdrs.get('content-type', '').split(';')[0].strip().lower()
            loc = hdrs.get('content-location', '').strip()
            low = loc.lower()
            if ctype == 'text/html' and page is None:
                cs = 'utf-8'
                mm = re.search('charset="?([\\w-]+)', hdrs.get('content-type', ''))
                if mm:
                    cs = mm.group(1)
                page = payload.decode(cs, errors='replace')
            elif ctype.startswith('image/') or low.endswith(IMG_EXT):
                key = ref_key(loc) or ('img%04d.png' % len(embedded))
                if store.take(key, lambda p=payload: p):
                    embedded.add(key)
            elif low.endswith('.js') or ctype in ('application/javascript', 'text/javascript'):
                texts[loc] = ('JS', payload.decode('utf-8', errors='replace'))
            elif low.endswith('.css') or ctype == 'text/css':
                texts[loc] = ('CSS', payload.decode('utf-8', errors='replace'))
    else:
        raw = src_path.read_bytes()
        enc = 'utf-8'
        mm = re.search(rb'(?i)charset=["\']?([\w-]+)', raw[:4000])
        if mm:
            enc = mm.group(1).decode('ascii', 'replace')
        try:
            page = raw.decode(enc, errors='replace')
        except LookupError:
            page = raw.decode('utf-8', errors='replace')

    if page is None:
        raise SystemExit('אין תוכן HTML בקובץ ' + str(src_path))

    # --- פתרון כל הפניות התמונות, מעבר אחד על העמוד -------------------
    base_dir = src_path.parent
    ref_map, missing = {}, set()

    for m in REF_RE.finditer(page):
        ref = m.group(1) or m.group(2)
        if ref in ref_map or ref.startswith('data:'):
            continue
        key = ref_key(ref)
        if not key:
            continue

        def loader(ref=ref, key=key):
            local = resolve_local(ref, base_dir)
            if local is not None and local.is_file():
                return local.read_bytes()
            hit = roots.get(key)
            if hit is not None:
                return hit.read_bytes()
            return None

        value = store.take(key, loader)
        if value:
            ref_map[ref] = value
        else:
            missing.add(key)

    def swap(m):
        ref = m.group(1) or m.group(2)
        value = ref_map.get(ref)
        if not value:
            return m.group(0)
        return m.group(0).replace(ref, value)

    page = REF_RE.sub(swap, page)

    # --- IE מרוקן src ומשאיר את הנתיב רק ב-href של הקישור העוטף -------
    def fill_from_anchor(m):
        head, href, attrs = m.group(1), m.group(2), m.group(3)
        if not (href.startswith('../') or href.startswith('data:')):
            return m.group(0)
        if re.search('(?i)src\\s*=\\s*' + Q + '\\s*[^"' + chr(39) + '\\s]', attrs):
            return m.group(0)
        if re.search('(?i)src\\s*=\\s*' + Q, attrs):
            attrs = re.sub('(?i)src\\s*=\\s*' + Q + '[^"' + chr(39) + ']*' + Q,
                           lambda _: 'src="' + href + '"', attrs, count=1)
        else:
            attrs = ' src="' + href + '"' + attrs
        return '<a' + head + '><img' + attrs + '>'

    page = re.compile(
        '(?is)<a((?:[^>]*?)href\\s*=\\s*' + Q + '([^"' + chr(39) + ']+?)' + Q +
        '(?:[^>]*?))>\\s*<img([^>]*)>').sub(fill_from_anchor, page)

    # --- טעינה עצלה -------------------------------------------------
    def lazify(m):
        tag = m.group(0)
        if '../' + ASSETS_REL not in tag or re.search('(?i)loading\\s*=', tag):
            return tag
        return tag[:-1].rstrip() + ' loading="lazy" decoding="async">'

    page = re.sub('(?is)<img[^>]*>', lazify, page)

    # --- הטמעת JS ו-CSS ---------------------------------------------
    for loc, (kind, body) in texts.items():
        base = re.escape(os.path.basename(loc.replace(BS, '/')))
        if kind == 'JS':
            repl = '<script>' + chr(10) + body.replace('</script', '<' + BS + '/script') + chr(10) + '</script>'
            page = re.sub('(?is)<script[^>]*src\\s*=\\s*' + Q + '?' + NQ + '*?' + base +
                          Q + '?[^>]*>\\s*</script>', lambda m: repl, page)
        else:
            repl = '<style>' + chr(10) + body + chr(10) + '</style>'
            page = re.sub('(?is)<link[^>]*href\\s*=\\s*' + Q + '?' + NQ + '*?' + base +
                          Q + '?[^>]*>', lambda m: repl, page)

    # --- ניטרול הפניות מקומיות מתות (פונטים, נתיבי D: שלא נפתרו) -----
    page = re.sub('(?i)url\\(\\s*' + Q + '?file:[^)]*\\)', 'url(about:blank)', page)
    page = re.sub('(?is)<script[^>]*src\\s*=\\s*' + Q + '?file:[^>]*>\\s*</script>', '', page)
    page = re.sub('(?is)<link[^>]*(href|src)\\s*=\\s*' + Q + '?file:[^>]*>', '', page)

    if not re.search('(?i)<meta[^>]+charset', page):
        page = re.sub('(?i)(<head[^>]*>)',
                      lambda m: m.group(1) + chr(10) + '<meta charset="utf-8">', page, count=1)

    m = re.search('(?is)<title[^>]*>(.*?)</title>', page)
    title = re.sub(r'\s+', ' ', htmlmod.unescape(m.group(1))).strip() if m else ''

    (out_dir / 'index.html').write_text(page, encoding='utf-8')

    return {'title': title, 'html': len(page), 'images': len(ref_map),
            'missing': sorted(missing)}


# ---------------------------------------------------------------- תפריט

def build_menu(entries):
    cards = []
    for name, info in entries:
        label = htmlmod.escape(info['title']) if info['title'] else '&nbsp;'
        cards.append(
            '    <a class="card" href="./' + htmlmod.escape(name) + '/">'
            '<span class="num">' + htmlmod.escape(name) + '</span>'
            '<span class="ttl">' + label + '</span>'
            '<span class="meta">' + str(info['images']) + ' תמונות</span></a>')
    return '''<!DOCTYPE html>
<html lang="he" dir="rtl">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex">
<title>קטלוג סניפים</title>
<style>
  :root { --bg:#f6f7f9; --fg:#1b1f24; --muted:#6b7280; --card:#fff; --line:#e3e6ea; --accent:#1f6feb; }
  @media (prefers-color-scheme: dark) {
    :root { --bg:#0f1216; --fg:#e8eaed; --muted:#9aa3ad; --card:#181c22; --line:#2a2f37; --accent:#58a6ff; }
  }
  * { box-sizing: border-box; }
  body { margin:0; padding:40px 16px; background:var(--bg); color:var(--fg);
         font-family:"Segoe UI",system-ui,Arial,sans-serif; }
  .wrap { max-width:900px; margin:0 auto; }
  h1 { font-size:1.6rem; margin:0 0 4px; }
  p.sub { color:var(--muted); margin:0 0 28px; font-size:.95rem; }
  .grid { display:grid; gap:12px; grid-template-columns:repeat(auto-fill,minmax(220px,1fr)); }
  .card { display:flex; flex-direction:column; gap:6px; padding:16px 18px; text-decoration:none;
          background:var(--card); border:1px solid var(--line); border-radius:10px; color:inherit;
          transition:border-color .15s, transform .15s; }
  .card:hover { border-color:var(--accent); transform:translateY(-2px); }
  .num { font-size:1.25rem; font-weight:600; color:var(--accent); }
  .ttl { font-size:.85rem; color:var(--muted); line-height:1.4; }
  .meta { font-size:.75rem; color:var(--muted); opacity:.8; }
  footer { margin-top:32px; color:var(--muted); font-size:.8rem; }
</style>
</head>
<body>
  <div class="wrap">
    <h1>קטלוג סניפים</h1>
    <p class="sub">''' + str(len(entries)) + ''' דוחות מלאי. בחר סניף:</p>
    <div class="grid">
''' + chr(10).join(cards) + '''
    </div>
    <footer>נבנה אוטומטית מדוחות Priority · build.py</footer>
  </div>
</body>
</html>
'''


# ---------------------------------------------------------------- main

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--src', default=str(ROOT / 'branches'), help='תיקיית הדוחות')
    ap.add_argument('--img-root', action='append', default=[],
                    help='תיקיית תמונות של Priority (אפשר לחזור על הדגל)')
    ap.add_argument('--max-edge', type=int, default=300,
                    help='צלע מקסימלית לתמונה. בטבלה הן מוצגות ב-100x50')
    ap.add_argument('--quality', type=int, default=75)
    ap.add_argument('--index-db', default=str(ROOT / '.imgindex.db'),
                    help='אינדקס שמות הקבצים בתיקיות התמונות')
    ap.add_argument('--reindex', action='store_true', help='לבנות את האינדקס מחדש')
    ap.add_argument('--reindex-days', type=int, default=7,
                    help='גיל מרבי לאינדקס לפני בנייה מחדש')
    ap.add_argument('--refresh-assets', action='store_true',
                    help='לעבד מחדש גם תמונות שכבר קיימות ב-assets/img')
    opts = ap.parse_args()

    src = Path(opts.src)
    if not src.is_dir():
        raise SystemExit('לא נמצאה תיקיית המקור: ' + str(src))

    dirs = list(opts.img_root)
    dirs += [d for d in ROOT.rglob('*')
             if d.is_dir() and d.name.lower() in PICS_NAMES and '.git' not in d.parts]
    for d in dirs:
        if not Path(d).is_dir():
            print('אזהרה: תיקיית תמונות לא קיימת — ' + str(d))
        else:
            print('תמונות: ' + str(d))
    roots = ImageRoots(dirs, opts.index_db, opts.reindex_days, opts.reindex)
    if Image is None:
        print('אזהרה: Pillow לא מותקן — תמונות יישמרו בגודלן המקורי')

    sources = sorted(p for p in src.iterdir()
                     if p.suffix.lower() in ('.mht', '.mhtml', '.htm', '.html'))
    if not sources:
        raise SystemExit('לא נמצאו דוחות ב-' + str(src))

    store = AssetStore(ROOT, opts)
    entries, all_missing = [], set()

    for report in sources:
        name = re.sub(r'[^A-Za-z0-9._-]', '_', report.stem)
        info = convert(report, ROOT / name, store, roots, opts)
        entries.append((name, info))
        all_missing |= set(info['missing'])
        line = ('  ' + name + '/  ' + str(info['html'] // 1024) + 'KB, ' +
                str(info['images']) + ' תמונות')
        if info['missing']:
            line += '  | לא נמצאו: ' + str(len(info['missing']))
        print(line)

    removed = store.prune()
    (ROOT / 'index.html').write_text(build_menu(entries), encoding='utf-8')
    (ROOT / '.nojekyll').write_text('', encoding='utf-8')

    print('')
    print('איתור תמונות: ' + str(roots.hits_direct) + ' ישיר, ' +
          str(roots.hits_index) + ' דרך האינדקס')
    print('סניפים: ' + str(len(entries)) +
          ' | תמונות חדשות: ' + str(store.added) +
          ', קיימות: ' + str(store.reused) +
          ', מוטמעות: ' + str(store.inlined) +
          ', נמחקו: ' + str(removed))
    total = sum(p.stat().st_size for p in store.dir.iterdir() if p.is_file())
    print('assets/img: ' + str(total // 1048576) + 'MB')
    if total > 900 * 1048576:
        print('אזהרה: GitHub Pages מוגבל ל-1GB לאתר')

    if all_missing:
        print('')
        print(str(len(all_missing)) + ' תמונות לא נמצאו באף תיקיית --img-root:')
        for n in sorted(all_missing)[:20]:
            print('   ' + n)
        if len(all_missing) > 20:
            print('   ... ועוד ' + str(len(all_missing) - 20))


if __name__ == '__main__':
    main()

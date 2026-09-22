#!/usr/bin/env python3
"""
בונה את האתר מקבצי MHT של דוחות Priority.

שימוש:
    python build.py [--src <תיקיית mht>] [--max-edge 700] [--quality 82]

כל קובץ <שם>.mht בתיקיית המקור הופך ל-<שם>/index.html, והתמונות נשמרות
כקבצים נפרדים ב-<שם>/img/ עם טעינה עצלה. כך עמוד נפתח מיידית גם כשקובץ
המקור שוקל ג'יגה — הדפדפן מוריד רק את התמונות שגוללים אליהן.

קבצי MHT נקראים חלק-אחרי-חלק ולא נטענים לזיכרון במלואם.
"""

import argparse, base64, binascii, html as htmlmod, io, os, quopri, re, sys
from pathlib import Path

try:
    from PIL import Image
except ImportError:
    Image = None      # בלי Pillow התמונות נשמרות בגודלן המקורי

ROOT = Path(__file__).resolve().parent
PICS_NAMES = ("pic", "pics")
IMG_DIR_NAME = "img"

BS = chr(92)
Q = '["' + chr(39) + ']'
NQ = '[^"' + chr(39) + '>]'

IMG_EXT = ('.gif', '.png', '.jpg', '.jpeg', '.svg', '.ico', '.bmp', '.webp')
MIME = {'jpg': 'jpeg', 'jpeg': 'jpeg', 'svg': 'svg+xml', 'ico': 'x-icon',
        'gif': 'gif', 'png': 'png', 'bmp': 'bmp', 'webp': 'webp'}

INLINE_MAX = 8000       # אייקונים קטנים מזה מוטמעים, כדי לא ליצור עשרות בקשות
SHRINK_OVER = 40000     # רק קבצים גדולים מזה מוקטנים


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
    """מחזיר (headers, payload) לכל חלק. כל חלק נקרא בנפרד, כך שגודל הקובץ
    כולו לא משפיע על הזיכרון — רק גודל החלק הבודד (תמונה אחת)."""
    with open(path, 'rb') as f:
        top = _read_headers(f)
        m = re.search('boundary="?([^";\r\n]+)"?', top.get('content-type', ''))
        if not m:
            raise SystemExit('אין boundary בקובץ ' + str(path))
        delim = b'--' + m.group(1).encode('latin-1')

        while True:                       # דילוג על הפתיח עד הגבול הראשון
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
            if raw.endswith(b'\r\n'):     # ה-CRLF האחרון שייך לגבול
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


# ---------------------------------------------------------------- קלט אחיד

REF_RE = re.compile(
    '(?i)(?:src|href)\\s*=\\s*' + Q + '([^"' + chr(39) + ']+?\\.(?:jpg|jpeg|png|gif|bmp|webp|ico|svg))' + Q +
    '|url\\(\\s*' + Q + '?([^)"' + chr(39) + ']+?\\.(?:jpg|jpeg|png|gif|bmp|webp|ico|svg))' + Q + '?\\s*\\)')


def resolve_local(ref, base_dir):
    """file:///d:/x.jpg, file:\\\\\\d:\\x.jpg, d:\\x.jpg או נתיב יחסי -> Path."""
    p = ref.split('?')[0]
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


def iter_resources(path):
    """מחזיר ('html'|'image'|'js'|'css', loc, payload) לכל משאב, אחד-אחד.

    תומך בשני פורמטים: MHT (חלקי MIME) ו-HTML רגיל עם תיקיית תמונות לידו.
    בשני המקרים לא נטען יותר ממשאב אחד לזיכרון בכל רגע.
    """
    if path.suffix.lower() in ('.mht', '.mhtml'):
        for hdrs, payload in stream_parts(path):
            ctype = hdrs.get('content-type', '').split(';')[0].strip().lower()
            loc = hdrs.get('content-location', '').strip()
            low = loc.lower()
            if ctype == 'text/html':
                cs = 'utf-8'
                mm = re.search('charset="?([\\w-]+)', hdrs.get('content-type', ''))
                if mm:
                    cs = mm.group(1)
                yield 'html', loc, payload.decode(cs, errors='replace')
            elif ctype.startswith('image/') or low.endswith(IMG_EXT):
                yield 'image', loc or ('x.' + (ctype.split('/')[-1] or 'png')), payload
            elif low.endswith('.js') or ctype in ('application/javascript', 'text/javascript'):
                yield 'js', loc, payload.decode('utf-8', errors='replace')
            elif low.endswith('.css') or ctype == 'text/css':
                yield 'css', loc, payload.decode('utf-8', errors='replace')
        return

    # HTML רגיל: התמונות יושבות בדיסק לצד הקובץ או בנתיב מוחלט
    raw = path.read_bytes()
    enc = 'utf-8'
    mm = re.search(rb'(?i)charset=["\']?([\w-]+)', raw[:4000])
    if mm:
        enc = mm.group(1).decode('ascii', 'replace')
    try:
        page = raw.decode(enc, errors='replace')
    except LookupError:
        page = raw.decode('utf-8', errors='replace')
    yield 'html', path.name, page

    base_dir = path.parent
    seen = set()
    for m in REF_RE.finditer(page):
        ref = m.group(1) or m.group(2)
        key = os.path.basename(ref.replace(BS, '/')).lower()
        if key in seen:
            continue
        seen.add(key)
        f = resolve_local(ref, base_dir)
        if f.is_file():
            yield 'image', ref, f.read_bytes()


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


def safe_name(loc, fallback):
    name = os.path.basename(loc.replace(BS, '/').split('?')[0]).strip()
    name = re.sub(r'[^A-Za-z0-9._-]', '_', name)
    return name if name and '.' in name else fallback


class PicIndex:
    """מאגר תמונות מקומי, לדוחות ישנים שבהם IE לא הטמיע את התמונות."""

    def __init__(self, directories):
        self.paths, self.dirs = {}, []
        for d in directories:
            if not d.is_dir():
                continue
            n = 0
            for p in d.rglob('*'):
                if p.is_file() and p.suffix.lower() in IMG_EXT:
                    if self.paths.setdefault(p.name.lower(), p) is p:
                        n += 1
            self.dirs.append((d, n))

    def __len__(self):
        return len(self.paths)

    def __contains__(self, name):
        return name in self.paths


# ---------------------------------------------------------------- המרה

def convert(mht_path, out_dir, extra_pics, opts):
    img_dir = out_dir / IMG_DIR_NAME
    img_dir.mkdir(parents=True, exist_ok=True)
    written = set()                     # לניקוי תמונות שנשארו מריצה קודמת

    page, texts = None, {}
    refs = {}          # שם קובץ -> נתיב יחסי או data URI
    locs = {}          # Content-Location מקורי -> אותו ערך
    n_files = n_inline = 0
    bytes_out = 0

    for kind, loc, payload in iter_resources(mht_path):
        low = loc.lower()

        if kind == 'html':
            if page is None:
                page = payload
            continue

        if kind == 'image':
            ext = low.rsplit('.', 1)[-1] if '.' in low else 'png'
            name = safe_name(loc, 'img%03d.%s' % (len(refs), ext))
            key = name.lower()
            if key in refs:
                locs[loc] = refs[key]
                continue
            small = shrink(payload, opts.max_edge, opts.quality)
            if small is not None:
                payload = small
                name = re.sub(r'\.[^.]+$', '', name) + '.jpg'
                key = name.lower()
            if len(payload) <= INLINE_MAX:
                mt = MIME.get(name.rsplit('.', 1)[-1].lower(), 'png')
                value = 'data:image/' + mt + ';base64,' + base64.b64encode(payload).decode('ascii')
                n_inline += 1
            else:
                (img_dir / name).write_bytes(payload)
                written.add(name.lower())
                value = IMG_DIR_NAME + '/' + name
                n_files += 1
                bytes_out += len(payload)
            refs[key] = value
            locs[loc] = value
            continue

        texts[loc] = ('JS' if kind == 'js' else 'CSS', payload)

    if page is None:
        raise SystemExit('אין חלק HTML בקובץ ' + str(mht_path))

    # דוחות ישנים: התמונות לא ב-MHT אלא במאגר מקומי
    for ref in set(re.findall('(?i)file:[^"' + chr(39) + ')>\\s]*', page)):
        key = os.path.basename(ref.replace(BS, '/')).lower()
        if key in refs or key not in extra_pics:
            continue
        raw = extra_pics.paths[key].read_bytes()
        name = safe_name(key, key)
        small = shrink(raw, opts.max_edge, opts.quality)
        if small is not None:
            raw = small
            name = re.sub(r'\.[^.]+$', '', name) + '.jpg'
        if len(raw) <= INLINE_MAX:
            mt = MIME.get(name.rsplit('.', 1)[-1].lower(), 'png')
            refs[key] = 'data:image/' + mt + ';base64,' + base64.b64encode(raw).decode('ascii')
            n_inline += 1
        else:
            (img_dir / name).write_bytes(raw)
            written.add(name.lower())
            refs[key] = IMG_DIR_NAME + '/' + name
            n_files += 1
            bytes_out += len(raw)

    def lookup(ref):
        return refs.get(os.path.basename(ref.replace(BS, '/')).lower())

    # 1. החלפת כל הפניה לתמונה בנתיב החדש
    for loc, value in sorted(locs.items(), key=lambda kv: -len(kv[0])):
        if not loc:
            continue
        for cand in {loc, loc.replace('file:///', 'file://'), loc.lower(),
                     loc.replace('/', BS), loc.lower().replace('/', BS)}:
            page = page.replace(cand, value)

    def swap_attr(m):
        value = lookup(m.group(2))
        return m.group(1) + value + m.group(3) if value else m.group(0)

    attr_ref = re.compile('(?i)((?:src|href)\\s*=\\s*' + Q + ')([^"' + chr(39) +
                          ']*?\\.(?:jpg|jpeg|png|gif|bmp|webp|ico|svg))(' + Q + ')')
    page = attr_ref.sub(swap_attr, page)

    css_ref = re.compile('(?i)(url\\(\\s*' + Q + '?)([^)"' + chr(39) +
                         ']*?\\.(?:jpg|jpeg|png|gif|bmp|webp|ico|svg))(' + Q + '?\\s*\\))')
    page = css_ref.sub(swap_attr, page)

    # 2. IE מרוקן את src ומשאיר את הנתיב רק ב-href של הקישור העוטף
    filled = []

    def fill_from_anchor(m):
        head, href, attrs = m.group(1), m.group(2), m.group(3)
        if not href.startswith(IMG_DIR_NAME + '/') and not href.startswith('data:'):
            return m.group(0)
        if re.search('(?i)src\\s*=\\s*' + Q + '\\s*[^"' + chr(39) + '\\s]', attrs):
            return m.group(0)
        if re.search('(?i)src\\s*=\\s*' + Q, attrs):
            attrs = re.sub('(?i)src\\s*=\\s*' + Q + '[^"' + chr(39) + ']*' + Q,
                           lambda _: 'src="' + href + '"', attrs, count=1)
        else:
            attrs = ' src="' + href + '"' + attrs
        filled.append(href)
        return '<a' + head + '><img' + attrs + '>'

    page = re.compile(
        '(?is)<a((?:[^>]*?)href\\s*=\\s*' + Q + '([^"' + chr(39) + ']+?)' + Q +
        '(?:[^>]*?))>\\s*<img([^>]*)>').sub(fill_from_anchor, page)

    # 3. טעינה עצלה לתמונות חיצוניות
    def lazify(m):
        tag = m.group(0)
        if IMG_DIR_NAME + '/' not in tag or re.search('(?i)loading\\s*=', tag):
            return tag
        return tag[:-1].rstrip() + ' loading="lazy" decoding="async">'

    page = re.sub('(?is)<img[^>]*>', lazify, page)

    # 4. הטמעת JS ו-CSS
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

    # 5. ניטרול הפניות מקומיות מתות שנשארו
    missing = sorted({os.path.basename(r.replace(BS, '/')).lower()
                      for r in re.findall('(?i)file:[^"' + chr(39) + ')>\\s]*', page)
                      if r.lower().endswith(IMG_EXT)})
    page = re.sub('(?i)url\\(\\s*' + Q + '?file:[^)]*\\)', 'url(about:blank)', page)
    page = re.sub('(?is)<script[^>]*src\\s*=\\s*' + Q + '?file:[^>]*>\\s*</script>', '', page)
    page = re.sub('(?is)<link[^>]*(href|src)\\s*=\\s*' + Q + '?file:[^>]*>', '', page)

    if not re.search('(?i)<meta[^>]+charset', page):
        page = re.sub('(?i)(<head[^>]*>)',
                      lambda m: m.group(1) + chr(10) + '<meta charset="utf-8">', page, count=1)

    m = re.search('(?is)<title[^>]*>(.*?)</title>', page)
    title = re.sub(r'\s+', ' ', htmlmod.unescape(m.group(1))).strip() if m else ''

    (out_dir / 'index.html').write_text(page, encoding='utf-8')

    for stale in img_dir.iterdir():     # תמונות שכבר לא בשימוש
        if stale.is_file() and stale.name.lower() not in written:
            try:
                stale.unlink()
            except OSError:
                pass

    return {'title': title, 'html': len(page), 'files': n_files,
            'inline': n_inline, 'bytes': bytes_out, 'missing': missing}


# ---------------------------------------------------------------- תפריט

def build_menu(entries):
    cards = []
    for name, info in entries:
        label = htmlmod.escape(info['title']) if info['title'] else '&nbsp;'
        n = info['files'] + info['inline']
        cards.append(
            '    <a class="card" href="./' + htmlmod.escape(name) + '/">'
            '<span class="num">' + htmlmod.escape(name) + '</span>'
            '<span class="ttl">' + label + '</span>'
            '<span class="meta">' + str(n) + ' תמונות</span></a>')
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
    <footer>נבנה אוטומטית מקבצי MHT · build.py</footer>
  </div>
</body>
</html>
'''


# ---------------------------------------------------------------- main

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--src', default=str(ROOT / 'branches'),
                    help='תיקיית קבצי ה-MHT')
    ap.add_argument('--max-edge', type=int, default=700)
    ap.add_argument('--quality', type=int, default=82)
    opts = ap.parse_args()

    src = Path(opts.src)
    if not src.is_dir():
        raise SystemExit('לא נמצאה תיקיית המקור: ' + str(src))

    pic_dirs = sorted(d for d in ROOT.rglob('*')
                      if d.is_dir() and d.name.lower() in PICS_NAMES
                      and '.git' not in d.parts)
    extra = PicIndex(pic_dirs)
    for d, n in extra.dirs:
        print('מאגר תמונות: ' + d.relative_to(ROOT).as_posix() + '/  (' + str(n) + ' קבצים)')
    if Image is None:
        print('אזהרה: Pillow לא מותקן — תמונות יישמרו בגודלן המקורי')

    sources = sorted(p for p in src.iterdir()
                     if p.suffix.lower() in ('.mht', '.mhtml', '.htm', '.html'))
    if not sources:
        raise SystemExit('לא נמצאו קבצי mht או html ב-' + str(src))

    entries, total, all_missing = [], 0, set()
    for mht in sources:
        name = re.sub(r'[^A-Za-z0-9._-]', '_', mht.stem)
        info = convert(mht, ROOT / name, extra, opts)
        entries.append((name, info))
        total += info['bytes'] + info['html']
        all_missing |= set(info['missing'])
        line = ('  ' + name + '/  ' + str(info['html'] // 1024) + 'KB html, ' +
                str(info['files']) + ' תמונות (' + str(info['bytes'] // 1048576) + 'MB)')
        if info['inline']:
            line += ', ' + str(info['inline']) + ' מוטמעות'
        if info['missing']:
            line += '  | חסרות: ' + str(len(info['missing']))
        print(line)

    (ROOT / 'index.html').write_text(build_menu(entries), encoding='utf-8')
    (ROOT / '.nojekyll').write_text('', encoding='utf-8')

    print('')
    print('נבנו ' + str(len(entries)) + ' סניפים, סה"כ ' + str(total // 1048576) + 'MB')
    if total > 900 * 1048576:
        print('אזהרה: GitHub Pages מוגבל ל-1GB לאתר')
    if all_missing:
        print('')
        print(str(len(all_missing)) + ' תמונות חסרות:')
        for n in sorted(all_missing)[:30]:
            print('   ' + n)


if __name__ == '__main__':
    main()

#!/usr/bin/env python3
"""
בונה את האתר מקבצי MHT.

שימוש:
    python build.py

כל קובץ branches/<שם>.mht הופך ל-<שם>/index.html — קובץ HTML עצמאי אחד
עם התמונות מוטמעות בתוכו (base64). בנוסף נוצר index.html ראשי עם קישורים לכולם.

תמונות שלא הוטמעו בקובץ ה-MHT (נתיבי file:/// לשרת Priority) מחופשות
בתיקיית pics/ המקומית לפי שם הקובץ, ומוטמעות אם נמצאו.
"""

import base64, email, html as htmlmod, os, re, sys
from email import policy
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SRC_DIR = ROOT / "branches"
PICS_NAMES = ("pic", "pics")   # כל תיקייה בשם כזה בפרויקט משמשת מאגר תמונות
BS = chr(92)
Q = '["' + chr(39) + ']'
NQ = '[^"' + chr(39) + '>]'

IMG_EXT = ('.gif', '.png', '.jpg', '.jpeg', '.svg', '.ico', '.bmp', '.webp')
MIME = {'jpg': 'jpeg', 'jpeg': 'jpeg', 'svg': 'svg+xml', 'ico': 'x-icon',
        'gif': 'gif', 'png': 'png', 'bmp': 'bmp', 'webp': 'webp'}


class PicIndex:
    """מפתח שם קובץ -> נתיב בתיקיית pics/, וממיר ל-data URI רק לפי דרישה.

    האינדוקס לא קורא את הקבצים, כדי שתיקיית pics ענקית (עשרות אלפי תמונות)
    לא תיטען כולה לזיכרון — רק תמונות שבאמת מופיעות בדוח מקודדות.
    """

    def __init__(self, directories):
        self.paths = {}
        self.cache = {}
        self.dirs = []
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

    def uri(self, name):
        if name not in self.cache:
            p = self.paths[name]
            ext = p.suffix.lower().lstrip('.')
            data = base64.b64encode(p.read_bytes()).decode('ascii')
            self.cache[name] = 'data:image/' + MIME.get(ext, ext) + ';base64,' + data
        return self.cache[name]


def convert(mht_path, extra_pics):
    with open(mht_path, 'rb') as f:
        msg = email.message_from_binary_file(f, policy=policy.default)

    page = None
    images = {}
    texts = {}

    for part in msg.walk():
        if part.is_multipart():
            continue
        ctype = part.get_content_type()
        loc = (part.get('Content-Location') or '').strip()
        payload = part.get_payload(decode=True)
        if payload is None:
            continue
        low = loc.lower()
        if ctype == 'text/html' and page is None:
            page = payload.decode(part.get_content_charset() or 'utf-8', errors='replace')
        elif ctype.startswith('image/') or low.endswith(IMG_EXT):
            guess = ctype if ctype.startswith('image/') else \
                'image/' + MIME.get(low.rsplit('.', 1)[-1], 'png')
            images[loc] = 'data:' + guess + ';base64,' + base64.b64encode(payload).decode('ascii')
        elif low.endswith('.js') or ctype in ('application/javascript', 'text/javascript'):
            texts[loc] = ('JS', payload.decode('utf-8', errors='replace'))
        elif low.endswith('.css') or ctype == 'text/css':
            texts[loc] = ('CSS', payload.decode('utf-8', errors='replace'))

    if page is None:
        raise SystemExit('אין חלק HTML בקובץ ' + str(mht_path))

    def inline(doc, loc, uri):
        for cand in {loc, loc.replace('file:///', 'file://'), loc.lower(),
                     loc.replace('/', BS), loc.lower().replace('/', BS)}:
            if cand:
                doc = doc.replace(cand, uri)
        base = os.path.basename(loc.replace(BS, '/'))
        if base:
            pat = re.compile('(?i)(["' + chr(39) + '(])([^"' + chr(39) + ')>]*?' +
                             re.escape(base) + ')(["' + chr(39) + ')])')
            doc = pat.sub(lambda m: m.group(1) + uri + m.group(3), doc)
        return doc

    # 1. תמונות שהוטמעו בתוך ה-MHT
    for loc, uri in images.items():
        page = inline(page, loc, uri)

    # 2. תמונות חסרות — חיפוש בתיקיית pics/ לפי שם הקובץ
    missing, recovered = set(), 0
    for ref in re.findall('(?i)file:[^"' + chr(39) + ')>\\s]*', page):
        name = os.path.basename(ref.replace(BS, '/')).lower()
        if not name.endswith(IMG_EXT):
            continue
        if name in extra_pics:
            page = inline(page, ref, extra_pics.uri(name))
            recovered += 1
        else:
            missing.add(name)

    # 3. הטמעת JS ו-CSS
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

    # 4. ניטרול הפניות מקומיות מתות שנשארו (פונטים ב-D:, קבצים זמניים)
    page = re.sub('(?i)url\\(\\s*' + Q + '?file:[^)]*\\)', 'url(about:blank)', page)
    page = re.sub('(?is)<script[^>]*src\\s*=\\s*' + Q + '?file:[^>]*>\\s*</script>', '', page)
    page = re.sub('(?is)<link[^>]*(href|src)\\s*=\\s*' + Q + '?file:[^>]*>', '', page)

    if not re.search('(?i)<meta[^>]+charset', page):
        page = re.sub('(?i)(<head[^>]*>)',
                      lambda m: m.group(1) + chr(10) + '<meta charset="utf-8">', page, count=1)

    m = re.search('(?is)<title[^>]*>(.*?)</title>', page)
    title = re.sub(r'\s+', ' ', htmlmod.unescape(m.group(1))).strip() if m else ''

    return page, title, len(images) + recovered, sorted(missing)


def main():
    if not SRC_DIR.is_dir():
        raise SystemExit('לא נמצאה התיקייה branches/')

    pic_dirs = sorted(d for d in ROOT.rglob('*')
                      if d.is_dir() and d.name.lower() in PICS_NAMES
                      and '.git' not in d.parts)
    extra = PicIndex(pic_dirs)
    if extra:
        for d, n in extra.dirs:
            print('מאגר תמונות: ' + d.relative_to(ROOT).as_posix() + '/  (' + str(n) + ' קבצים)')
    else:
        print('לא נמצאה תיקיית pic/ או pics/ — תמונות חסרות יישארו שבורות')

    entries, all_missing = [], set()
    for mht in sorted(SRC_DIR.glob('*.mht')) + sorted(SRC_DIR.glob('*.mhtml')):
        name = mht.stem
        page, title, n_img, missing = convert(mht, extra)
        out_dir = ROOT / name
        out_dir.mkdir(exist_ok=True)
        (out_dir / 'index.html').write_text(page, encoding='utf-8')
        all_missing |= set(missing)
        entries.append((name, title, len(page)))
        status = 'תמונות: ' + str(n_img)
        if missing:
            status += '  | חסרות: ' + str(len(missing))
        print('  ' + name + '/index.html  (' + str(len(page) // 1024) + 'KB, ' + status + ')')

    (ROOT / 'index.html').write_text(build_menu(entries), encoding='utf-8')
    (ROOT / '.nojekyll').write_text('', encoding='utf-8')

    print('')
    print('נבנו ' + str(len(entries)) + ' עמודים + תפריט ראשי')
    if all_missing:
        print('')
        print(str(len(all_missing)) + ' תמונות חסרות. העתק אותן לתיקייה pics/ והרץ שוב:')
        for n in sorted(all_missing)[:40]:
            print('   ' + n)


def build_menu(entries):
    cards = []
    for name, title, size in entries:
        label = htmlmod.escape(title) if title else '&nbsp;'
        cards.append(
            '    <a class="card" href="./' + htmlmod.escape(name) + '/">'
            '<span class="num">' + htmlmod.escape(name) + '</span>'
            '<span class="ttl">' + label + '</span></a>')
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
  .wrap { max-width:860px; margin:0 auto; }
  h1 { font-size:1.6rem; margin:0 0 4px; }
  p.sub { color:var(--muted); margin:0 0 28px; font-size:.95rem; }
  .grid { display:grid; gap:12px; grid-template-columns:repeat(auto-fill,minmax(230px,1fr)); }
  .card { display:flex; flex-direction:column; gap:6px; padding:16px 18px; text-decoration:none;
          background:var(--card); border:1px solid var(--line); border-radius:10px; color:inherit;
          transition:border-color .15s, transform .15s; }
  .card:hover { border-color:var(--accent); transform:translateY(-2px); }
  .num { font-size:1.25rem; font-weight:600; color:var(--accent); }
  .ttl { font-size:.85rem; color:var(--muted); line-height:1.4; }
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


if __name__ == '__main__':
    main()

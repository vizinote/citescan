"""CiteScan : insere un bloc 'Derniers articles' dans chaque article du blog
(static/blog/*.html). Idempotent. Liens relatifs (meme dossier /blog/)."""
import glob, os, re, html as htmllib

DATE_RE = re.compile(r'"datePublished"\s*:\s*"(\d{4}-\d{2}-\d{2})"')
H1_RE = re.compile(r'<h1[^>]*>(.*?)</h1>', re.S)
TAG_RE = re.compile(r'<[^>]+>')

arts = {}
for path in sorted(glob.glob('static/blog/*.html')):
    fn = os.path.basename(path)
    if fn in ('index.html', '_template.html'):
        continue
    txt = open(path, encoding='utf-8').read()
    m = DATE_RE.search(txt)
    h = H1_RE.search(txt)
    if not m or not h:
        print('SKIP (pas de date/h1):', fn)
        continue
    title = htmllib.unescape(TAG_RE.sub('', h.group(1))).strip()
    arts[fn] = (m.group(1), title)

print(f'{len(arts)} articles dates')
recent = sorted(arts.items(), key=lambda kv: kv[1][0], reverse=True)[:7]

def block_for(fn):
    picks = [(f, t) for f, (d, t) in recent if f != fn][:6]
    links = ' · '.join(f'<a href="{f}">{htmllib.escape(t, quote=False)}</a>' for f, t in picks)
    return (f'    <hr class="recent-articles">\n'
            f'    <p><strong>Derniers articles :</strong> {links}</p>\n')

changed = []
for fn in arts:
    path = f'static/blog/{fn}'
    txt = open(path, encoding='utf-8').read()
    if 'recent-articles' in txt:
        continue
    if '</main>' not in txt:
        print('SKIP (pas de </main>):', fn)
        continue
    txt = txt.replace('</main>', block_for(fn) + '</main>', 1)
    open(path, 'w', encoding='utf-8').write(txt)
    changed.append(fn)

print(f'{len(changed)} modifies')
bad = []
for fn in changed:
    txt = open(f'static/blog/{fn}', encoding='utf-8').read()
    m = re.search(r'<hr class="recent-articles">\s*<p>(.*?)</p>', txt, re.S)
    for href in re.findall(r'href="([^"]+)"', m.group(1)):
        if not os.path.isfile(f'static/blog/{href}') or href == fn:
            bad.append((fn, href))
print('liens casses/auto:', bad or 'aucun')
assert not bad

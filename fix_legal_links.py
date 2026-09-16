"""CiteScan SEO : repointe les footers 'mentions legales' vers les pages
canoniques et supprime l'ancienne page courte /static/mentions-legales.html.
Idempotent. Affiche un compte-rendu."""
import os, glob

OLD = 'href="/static/mentions-legales.html"'
changed, skipped = [], []
for path in sorted(glob.glob('static/**/*.html', recursive=True)):
    html = open(path, encoding='utf-8').read()
    if OLD not in html:
        continue
    if path == 'static/index.html':  # home EN -> page legale EN
        new = html.replace(OLD, 'href="/en/legal.html"')
    else:  # pages FR (fr/, blog/, secteurs/)
        new = html.replace(OLD, 'href="/mentions-legales.html"')
    if new != html:
        open(path, 'w', encoding='utf-8').write(new)
        changed.append(path)

legacy = 'static/mentions-legales.html'
if os.path.isfile(legacy):
    os.remove(legacy)
    removed = True
else:
    removed = False

print(f'{len(changed)} fichiers modifies, legacy supprime: {removed}')
for p in changed:
    print(' ', p)
# verif : plus aucune reference
left = [p for p in glob.glob('static/**/*.html', recursive=True) if OLD in open(p, encoding='utf-8').read()]
print('references restantes:', left or 'aucune')
assert not left

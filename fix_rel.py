path = "/home/james/Downloads/vcard/src/vcard_normalizer/static/index.html"
txt = open(path).read()

old1 = "      const d = await (await fetch(`/api/search_cards?q=${encodeURIComponent(q)}`)).json();\n      renderRelPickerGrid(d.results||[], gridId, ctx);"
new1 = "      const d = await (await fetch(`/api/search_cards?q=${encodeURIComponent(q)}`)).json();\n      const filtered = (d.results||[]).filter(r => r.kind !== 'org');\n      renderRelPickerGrid(filtered, gridId, ctx);"
if old1 in txt:
    txt = txt.replace(old1, new1); print("OK: org filter")
else:
    print("WARN: org filter not found")

if 'jumpToLinkedCard' not in txt:
    fn = 'async function jumpToLinkedCard(globalIdx) {\n  closeEditModal();\n  try {\n    const d = await (await fetch(\'/api/cards?per_page=1000\')).json();\n    const pi = (d.cards || []).findIndex(c => c._idx === globalIdx);\n    if (pi >= 0) { _currentPageCards = d.cards; openEdit(pi); }\n    else { toast(\'Card not found\', true); }\n  } catch(e) { toast(\'Failed\', true); }\n}\n\n'
    txt = txt.replace('async function removeRelUid(', fn + 'async function removeRelUid(')
    print("OK: jumpToLinkedCard added")
else:
    print("OK: jumpToLinkedCard exists")

if 'ri-name-link' not in txt:
    txt = txt.replace(
        '.ri-name{flex:1;font-size:11px;color:var(--text)}',
        '.ri-name{flex:1;font-size:11px;color:var(--text)}\n.ri-name-link{cursor:pointer;text-decoration:underline;text-decoration-style:dotted;text-underline-offset:2px}\n.ri-name-link:hover{color:var(--bright)}'
    )
    print("OK: CSS added")

open(path, 'w').write(txt)
print("Done")

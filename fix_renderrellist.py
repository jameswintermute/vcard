path = "/home/james/Downloads/vcard/src/vcard_normalizer/static/index.html"
txt = open(path).read()

OLD = '''function renderRelList(ctx) {
  const list = ctx === 'add' ? _addRelated : _editRelated;
  const el = document.getElementById(`${ctx}-rel-list`);
  if (!list.length) { el.innerHTML = `<div style="color:var(--dim);font-size:10px;padding:3px 0 6px;">No linked people yet.</div>`; return; }
  el.innerHTML = list.map((r, i) => `
    <div class="rel-item">
      <span class="ri-type">${esc(r.rel_type)}</span>
      <span class="ri-name">${esc(r.text || r.uid || '?')}</span>
      ${r.uid ? `<span class="ri-uid" title="Linked by UID — bidirectional">⊕ linked</span>` : `<span class="ri-uid">text only</span>`}
      <button class="rel-remove" onmousedown="${r.uid && ctx==='edit' ? `removeRelUid('${ctx}','${r.uid}',${i})` : `removeRel('${ctx}',${i})`}">✕</button>
    </div>`).join('');
}'''

NEW = '''function renderRelList(ctx) {
  const list = ctx === 'add' ? _addRelated : _editRelated;
  const el = document.getElementById(`${ctx}-rel-list`);
  if (!list.length) { el.innerHTML = '<div style="color:var(--dim);font-size:10px;padding:3px 0 6px;">No linked people yet.</div>'; return; }
  el.innerHTML = list.map((r, i) => {
    const looksLikeUid = r.text && /^vcard-studio-/i.test(r.text);
    const resolved = r.uid ? (window._state_cards_by_uid || {})[r.uid] : null;
    const displayName = (!looksLikeUid && r.text) ? r.text
                      : (resolved ? (resolved.fn || resolved.org || r.uid) : (r.uid || '?'));
    const linkedIdx = resolved ? resolved._idx : null;
    const nameEl = (r.uid && linkedIdx != null)
      ? '<span class="ri-name ri-name-link" onclick="jumpToLinkedCard(' + linkedIdx + ')">' + esc(displayName) + ' \u2197</span>'
      : '<span class="ri-name">' + esc(displayName) + '</span>';
    return '<div class="rel-item">'
      + '<span class="ri-type">' + esc(r.rel_type) + '</span>'
      + nameEl
      + (r.uid ? '<span class="ri-uid" title="Linked by UID">⊕ linked</span>' : '<span class="ri-uid">text only</span>')
      + '<button class="rel-remove" onmousedown="' + (r.uid && ctx==='edit' ? 'removeRelUid(\'' + ctx + '\',\'' + r.uid + '\',' + i + ')' : 'removeRel(\'' + ctx + '\',' + i + ')') + '">✕</button>'
      + '</div>';
  }).join('');
}'''

if OLD in txt:
    txt = txt.replace(OLD, NEW)
    open(path, 'w').write(txt)
    print("OK: renderRelList fixed")
else:
    print("WARN: pattern not found - current renderRelList:")
    i = txt.index('function renderRelList')
    print(txt[i:i+500])

const byId = (id) => document.getElementById(id);
const label = (name) => name.replaceAll('_', ' ').replace(/\b\w/g, (c) => c.toUpperCase());
const status = (item) => item.raw < 40 ? 'red' : item.raw < 70 ? 'amber' : 'green';
const escapeHtml = (value) => String(value).replace(/[&<>'"]/g, (character) => ({
  '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;'
})[character]);
const safeHref = (value) => /^(https?:\/\/|evidence:\/\/|audit:\/\/)/.test(String(value)) ? value : '#';
const meterWidth = (value) => Math.max(0, Math.min(100, Number(value) || 0));

const renderPortfolio = (rows) => {
  const container = byId('portfolio');
  const sortedRows = [...rows].sort((left, right) => right.risk - left.risk || right.velocity - left.velocity);
  container.replaceChildren(...sortedRows.map((row) => {
    const card = document.createElement('article');
    card.className = 'portfolio-card';
    const evidence = row.evidence_uris[0] || '#';
    card.innerHTML = `<p class="eyebrow">${escapeHtml(row.vertical)} · RISK ${escapeHtml(row.risk)}</p>
      <h3>${escapeHtml(row.deployment_id)}</h3>
      <p><strong>Recommended action:</strong> ${escapeHtml(row.action)}</p>
      <p><strong>Confidence:</strong> ${escapeHtml(Math.round(row.confidence * 100))}% · <strong>Velocity:</strong> ${escapeHtml(row.velocity)}</p>
      <p><a href="${escapeHtml(safeHref(evidence))}">View evidence</a> · <a href="${escapeHtml(safeHref(row.audit_record))}">Audit record</a></p>`;
    return card;
  }));
};

fetch('readiness_score.json').then((response) => {
  if (!response.ok) throw new Error(`artifact request failed: ${response.status}`);
  return response.json();
}).then((data) => {
  const score = data.score.value;
  byId('score').textContent = score;
  byId('band').textContent = `${data.band} · ${data.score.confidence * 100}% evidence confidence`;
  byId('summary').textContent = `Bare-repo readiness scenario · rubric ${data.score.rubric_version}`;
  byId('interval').textContent = `${data.confidence.interval_low}–${data.confidence.interval_high} / 1000 · ${data.confidence.method}`;
  byId('range-fill').style.left = `${data.confidence.interval_low / 10}%`;
  byId('range-fill').style.width = `${(data.confidence.interval_high - data.confidence.interval_low) / 10}%`;
  byId('range-point').style.left = `${score / 10}%`;
  byId('drivers').replaceChildren(...data.confidence.drivers.map((driver) => Object.assign(document.createElement('li'), {textContent: driver.detail})));
  byId('dimensions').replaceChildren(...data.sub_scores.map((item) => {
    const card = document.createElement('article'); card.className = `dimension ${status(item)}`;
    card.innerHTML = `<div><h3>${escapeHtml(label(item.name))}</h3><span>${escapeHtml(item.raw.toFixed(0))} / 100 · weight ${escapeHtml((item.weight * 100).toFixed(0))}%</span></div><div class="meter"><i style="width:${meterWidth(item.raw)}%"></i></div><p><strong>Control:</strong> ${escapeHtml(item.control_clauses.join(' · '))}</p><p><strong>Evidence quality:</strong> ${escapeHtml(item.evidence_quality.source)} · ${escapeHtml(item.evidence_quality.freshness)} · ${escapeHtml((item.evidence_quality.confidence * 100).toFixed(0))}%</p><p class="evidence"><strong>Evidence:</strong> ${escapeHtml(item.evidence_uris.join(', '))}</p>`;
    return card;
  }));
  const total = data.counterfactual.reduce((sum, action) => sum + action.projected_score_delta, 0);
  byId('path-summary').textContent = `Complete these actions for an estimated +${total} points; the resulting score clears the next band.`;
  byId('actions').replaceChildren(...data.counterfactual.map((action, index) => { const item = document.createElement('li'); item.innerHTML = `<b>${index + 1}. ${escapeHtml(action.action)}</b><span>${escapeHtml(label(action.sub_score_affected))} · +${escapeHtml(action.projected_score_delta)} points · effort ${escapeHtml(action.cost)}/5</span>`; return item; }));
  byId('audit-record').textContent = JSON.stringify(data.audit, null, 2);
  byId('audit-button').onclick = () => byId('audit-dialog').showModal();
  byId('close-audit').onclick = () => byId('audit-dialog').close();
}).catch((error) => { byId('summary').textContent = `Artifact could not be loaded: ${error.message}`; });

fetch('portfolio.json').then((response) => {
  if (!response.ok) throw new Error(`artifact request failed: ${response.status}`);
  return response.json();
}).then(renderPortfolio).catch((error) => {
  byId('portfolio').textContent = `Portfolio artifact could not be loaded: ${error.message}`;
});

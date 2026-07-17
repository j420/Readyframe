const byId = (id) => document.getElementById(id);
const label = (name) => name.replaceAll('_', ' ').replace(/\b\w/g, (c) => c.toUpperCase());
const status = (item) => item.raw < 40 ? 'red' : item.raw < 70 ? 'amber' : 'green';

const renderPortfolio = (data) => {
  const rows = data.rows.sort((a, b) => b.risk.value - a.risk.value || b.velocity.value - a.velocity.value);
  byId('portfolio').replaceChildren(...rows.map((row) => {
    const item = document.createElement('p');
    const name = document.createElement('b');
    const evidence = document.createElement('a');
    evidence.href = row.evidence_uris[0]; evidence.textContent = 'evidence';
    name.textContent = row.deployment_id;
    item.append(name, ` · ${row.vertical} · risk ${row.risk.value} (${row.risk.confidence * 100}% confidence) · `, evidence, ` · action: ${row.action}`);
    return item;
  }));
};

const renderScore = (data) => {
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
    card.innerHTML = `<div><h3>${label(item.name)}</h3><span>${item.raw.toFixed(0)} / 100 · weight ${(item.weight * 100).toFixed(0)}%</span></div><div class="meter"><i style="width:${item.raw}%"></i></div><p><strong>Control:</strong> ${item.control_clauses.join(' · ')}</p><p><strong>Evidence quality:</strong> ${item.evidence_quality.source} · ${item.evidence_quality.freshness} · ${(item.evidence_quality.confidence * 100).toFixed(0)}%</p><p class="evidence"><strong>Evidence:</strong> ${item.evidence_uris.join(', ')}</p>`;
    return card;
  }));
  const total = data.counterfactual.reduce((sum, action) => sum + action.projected_score_delta, 0);
  byId('path-summary').textContent = `Complete these actions for an estimated +${total} points; the resulting score clears the next band.`;
  byId('actions').replaceChildren(...data.counterfactual.map((action, index) => { const item = document.createElement('li'); item.innerHTML = `<b>${index + 1}. ${action.action}</b><span>${label(action.sub_score_affected)} · +${action.projected_score_delta} points · effort ${action.cost}/5</span>`; return item; }));
  byId('audit-record').textContent = JSON.stringify(data.audit, null, 2);
  byId('audit-button').onclick = () => byId('audit-dialog').showModal();
  byId('close-audit').onclick = () => byId('audit-dialog').close();
};

fetch('readiness_score.json').then((response) => response.json()).then(renderScore)
  .catch((error) => { byId('summary').textContent = `Artifact could not be loaded: ${error.message}`; });

fetch('portfolio.json').then((response) => response.json()).then(renderPortfolio)
  .catch((error) => { byId('portfolio').textContent = `Portfolio artifact could not be loaded: ${error.message}`; });

byId('run-demo').addEventListener('click', async () => {
  const demoStatus = byId('demo-status');
  demoStatus.textContent = 'Discovering approved repository and compiling score-derived gates…';
  try {
    const response = await fetch(`/api/demo?profile=${encodeURIComponent(byId('demo-profile').value)}`);
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || 'demo workflow failed');
    renderScore(result.readiness_score);
    const rollback = result.blueprint.rollback_rules.map((rule) => `${rule.effect}: ${rule.when}`).join('; ');
    const before = result.flywheel.before?.score?.value;
    const after = result.flywheel.after?.score?.value;
    demoStatus.textContent = `Blueprint ready — ${rollback}. Flywheel ${result.flywheel.refit.rubric_version} published from ${result.flywheel.refit.accepted_records} accepted records: a separate anonymized target engagement score ${before} → ${after}.`;
  } catch (error) {
    demoStatus.textContent = `Demo workflow was stopped safely: ${error.message}`;
  }
});

byId('score-form').addEventListener('submit', async (event) => {
  event.preventDefault();
  const form = new FormData(event.currentTarget);
  const controls = Object.fromEntries(['access_control', 'rollback_plan', 'observability'].map((name) => [name, Number(form.get(name))]));
  const formStatus = byId('form-status');
  formStatus.textContent = 'Calculating an unverified deterministic preview…';
  try {
    const response = await fetch('/api/score', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({$schema: '../schemas/readiness-input.schema.json', rubric_version: form.get('rubric_version'), controls})});
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || 'score request failed');
    renderScore(result);
    formStatus.textContent = `Preview calculated: ${result.score.value} (${result.band}); it is not a deployment approval.`;
  } catch (error) {
    formStatus.textContent = `Score was not calculated: ${error.message}`;
  }
});

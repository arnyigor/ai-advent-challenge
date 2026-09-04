let eventSource = null;
let currentRunId = null;
let runData = null;

function setScene(id, caption) {
    document.body.dataset.scene = id;
    window.__caption = caption;
}

document.addEventListener('DOMContentLoaded', () => {
    loadReplayOptions();
    setupTabs();
    setupControls();
});

function setupTabs() {
    document.querySelectorAll('.tab').forEach(tab => {
        tab.addEventListener('click', () => {
            document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
            document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
            tab.classList.add('active');
            document.getElementById(`tab-${tab.dataset.tab}`).classList.add('active');
        });
    });
}

function setupControls() {
    document.getElementById('runButton').addEventListener('click', startRun);
    document.getElementById('stopButton').addEventListener('click', stopRun);
    document.getElementById('replaySelect').addEventListener('change', (e) => {
        if (e.target.value) loadReplay(e.target.value);
    });
}

async function loadReplayOptions() {
    try {
        const res = await fetch('/api/results');
        const items = await res.json();
        const select = document.getElementById('replaySelect');
        items.forEach(item => {
            const opt = document.createElement('option');
            opt.value = item.id;
            opt.textContent = `${item.name} (${item.model || 'unknown'})`;
            select.appendChild(opt);
        });
    } catch (e) {
        console.error('Failed to load replays', e);
    }
}

async function startRun() {
    document.getElementById('runButton').disabled = true;
    document.getElementById('stopButton').disabled = false;
    document.getElementById('statusLabel').textContent = 'RUNNING';
    document.getElementById('statusLabel').className = 'status RUNNING';
    document.body.classList.remove('replay-mode');

    clearUI();
    setScene('running', '3 температуры × 3 прогона = 9 вызовов');

    try {
        const res = await fetch('/api/run', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ repeats: 3, concurrency: 3 })
        });
        const data = await res.json();
        currentRunId = data.run_id;
        connectSSE(currentRunId);
    } catch (e) {
        console.error('Failed to start run', e);
        setStatus('FAILED');
    }
}

async function stopRun() {
    if (!currentRunId) return;
    document.getElementById('stopButton').disabled = true;
    setScene('stopped', 'Кнопка STOP: мгновенный разрыв стрима и отмена сессии');
    try {
        await fetch(`/api/runs/${currentRunId}/cancel`, { method: 'POST' });
    } catch (e) {
        console.error('Failed to stop', e);
    }
}

function connectSSE(runId) {
    eventSource = new EventSource(`/api/runs/${runId}/events`);
    eventSource.onmessage = (e) => {
        const event = JSON.parse(e.data);
        handleEvent(event);
    };
    eventSource.onerror = () => {
        eventSource.close();
        if (document.getElementById('statusLabel').textContent === 'RUNNING') {
            setStatus('FAILED');
        }
    };
}

function handleEvent(event) {
    const { type, data } = event;
    if (type === 'preflight_passed') {
        document.getElementById('lockedModel').textContent = data.model;
    } else if (type === 'sample_started') {
        addRunItem(data.temperature, data.repeat, 'running');
    } else if (type === 'sample_finished') {
        updateRunItem(data);
        bumpProgress(data.temperature);
    } else if (type === 'ExperimentFinished') {
        eventSource.close();
        runData = data.document;
        setStatus('DONE');
        document.getElementById('runButton').disabled = false;
        document.getElementById('stopButton').disabled = true;
        renderFullResults(runData);
        setScene('verdict', '0.0 факты · 0.7 объяснения · 1.2 брейншторм');
        loadReplayOptions();
    } else if (type === 'ExperimentFailed') {
        eventSource.close();
        setStatus('FAILED');
        document.getElementById('runButton').disabled = false;
        document.getElementById('stopButton').disabled = true;
        alert('Ошибка: ' + data.error);
    } else if (type === 'StreamClosed') {
        eventSource.close();
    }
}

function setStatus(status) {
    const el = document.getElementById('statusLabel');
    el.textContent = status;
    el.className = `status ${status}`;
}

function clearUI() {
    // Стринги, а не числа: `${0.0}` -> "0" и ID runs-0 в DOM не найдётся.
    ['0.0', '0.7', '1.2'].forEach(t => {
        document.getElementById(`runs-${t}`).innerHTML = '';
        document.getElementById(`sim-${t}`).textContent = '—';
        document.getElementById(`bar-${t}`).style.width = '0%';
    });
    document.getElementById('analogiesGrid').innerHTML = '';
    document.getElementById('metricsBody').innerHTML = '';
    document.getElementById('rawOutput').textContent = '';
}

function addRunItem(temp, repeat, state) {
    const t = Number(temp).toFixed(1); // 0 -> "0.0", чтобы совпадало с ID в HTML
    const container = document.getElementById(`runs-${t}`);
    const div = document.createElement('div');
    div.className = `run-item ${state}`;
    div.id = `run-t${t}-r${repeat}`;
    div.textContent = `Прогон ${repeat}...`;
    container.appendChild(div);
}

function updateRunItem(data) {
    const div = document.getElementById(`run-t${Number(data.temperature).toFixed(1)}-r${data.repeat}`);
    if (!div) return;
    const isDegraded = (data.degradations || []).length > 0 || data.finish_reason === 'MAX_TOKENS';
    div.className = `run-item ${isDegraded ? 'degraded' : 'done'}`;
    div.innerHTML = `<strong>Прогон ${data.repeat}</strong><br>
        Слов: ${data.words} · Токенов: ${data.output_tokens || '?'}<br>
        <span style="color: ${isDegraded ? 'var(--danger)' : 'var(--success)'}">${data.finish_reason}</span>`;
}

function bumpProgress(temp) {
    const t = Number(temp).toFixed(1);
    const container = document.getElementById(`runs-${t}`);
    const total = container.children.length || 3;
    const done = container.querySelectorAll('.run-item.done, .run-item.degraded').length;
    document.getElementById(`bar-${t}`).style.width = `${(done / total) * 100}%`;
    document.getElementById(`sim-${t}`).textContent = `${done}/${total} готово`;
}

function renderFullResults(doc) {
    document.getElementById('rawOutput').textContent = JSON.stringify(doc, null, 2);
    const promptEl = document.getElementById('analogyPrompt');
    if (promptEl && doc.locked?.prompt) {
        promptEl.textContent = doc.locked.prompt;
    }

    const grid = document.getElementById('analogiesGrid');
    grid.innerHTML = '';
    doc.samples.forEach(s => {
        const card = document.createElement('div');
        card.className = 'analogy-card';
        const title = document.createElement('h4');
        title.textContent = `T=${s.temperature} · Прогон ${s.repeat}`;
        const body = document.createElement('p');
        body.textContent = extractAnalogy(s.text || s.tail || '');
        card.append(title, body);
        grid.appendChild(card);
    });

    const tbody = document.getElementById('metricsBody');
    tbody.innerHTML = '';
    ['0.0', '0.7', '1.2'].forEach(t => {
        const m = doc.metrics[t];
        if (!m) return;
        const tr = document.createElement('tr');
        tr.innerHTML = `
            <td>${t}</td>
            <td>${m.self_similarity.toFixed(3)}</td>
            <td>${m.ttr.toFixed(2)}</td>
            <td>${m.len_cv.toFixed(2)}</td>
            <td>${m.checklist_mean.toFixed(1)}</td>
            <td>${m.degradations}</td>
            <td>${m.latency_ms_mean.toFixed(0)}</td>
        `;
        tbody.appendChild(tr);

        const sim = m.self_similarity;
        document.getElementById(`sim-${t}`).textContent = sim.toFixed(2);
        document.getElementById(`bar-${t}`).style.width = `${sim * 100}%`;
    });
}

function extractAnalogy(text) {
    const normalized = text.replace(/\r/g, '').trim();
    const headingMatch = normalized.match(/(?:^|\n)#{1,3}\s*.*аналог[^\n]*\n+([\s\S]*)$/i);
    if (headingMatch) return compactAnalogy(headingMatch[1]);

    const markerMatch = normalized.match(/(?:Бытов[а-яё\s]*аналог[а-яё]*|Аналогия)[:\s\n-]+([\s\S]*)$/i);
    if (markerMatch) return compactAnalogy(markerMatch[1]);

    const paragraphs = normalized.split(/\n{2,}/).map(cleanText).filter(Boolean);
    const analogyParagraph = [...paragraphs].reverse().find(p => /как|представь|это когда/i.test(p));
    return compactAnalogy(analogyParagraph || paragraphs.at(-1) || normalized);
}

function compactAnalogy(text) {
    const cleaned = cleanText(text);
    const merge = firstSentence(cleaned.match(/merge\s*[—-]\s*это как\s*([^.!?]+[.!?]?)/i)?.[0]);
    const rebase = firstSentence(cleaned.match(/rebase\s*[—-]\s*это как\s*([^.!?]+[.!?]?)/i)?.[0]);
    if (merge && rebase) return `${merge}\n${rebase}`;
    if (rebase) return rebase;

    const sentences = cleaned.split(/(?<=[.!?])\s+/).filter(Boolean);
    const picked = sentences.filter(s => /merge|rebase|как|представь/i.test(s)).slice(0, 2);
    return (picked.length ? picked : sentences.slice(0, 2)).join(' ');
}

function firstSentence(text) {
    if (!text) return '';
    return text.split(/(?<=[.!?])\s+/)[0].trim();
}

function cleanText(text) {
    return text
        .replace(/```[\s\S]*?```/g, '')
        .replace(/^[-*]\s+/gm, '')
        .replace(/\*\*/g, '')
        .replace(/`/g, '')
        .replace(/\s+/g, ' ')
        .trim();
}

async function loadReplay(fileId) {
    document.body.classList.add('replay-mode');
    clearUI();
    setScene('intro', 'REPLAY: сохранённый реальный прогон');
    try {
        const res = await fetch(`/api/result?id=${encodeURIComponent(fileId)}`);
        const doc = await res.json();
        runData = doc;
        renderFullResults(doc);
        setStatus('DONE');
        document.getElementById('lockedModel').textContent = doc.model_spec;
        document.getElementById('lockedSha').textContent = doc.locked.prompt_sha256;
        setScene('verdict', '0.0 факты · 0.7 объяснения · 1.2 брейншторм');
    } catch (e) {
        console.error('Failed to load replay', e);
    }
}

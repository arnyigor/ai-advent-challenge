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

function renderFullResults(doc) {
    document.getElementById('rawOutput').textContent = JSON.stringify(doc, null, 2);

    const grid = document.getElementById('analogiesGrid');
    grid.innerHTML = '';
    doc.samples.forEach(s => {
        const card = document.createElement('div');
        card.className = 'analogy-card';
        card.innerHTML = `<h4>T=${s.temperature} · Прогон ${s.repeat}</h4><p>${s.tail}</p>`;
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
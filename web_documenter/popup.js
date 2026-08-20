/*
 * popup.js - 확장 아이콘을 눌렀을 때 뜨는 조작 화면
 */
'use strict';

const $ = (id) => document.getElementById(id);

const MODE_HINT = {
  batch: '여러 페이지를 담아 두었다가 마지막에 한 번에 저장합니다.',
  single: '담는 즉시 페이지마다 파일 하나씩 바로 저장됩니다.'
};

let state = { settings: {}, items: [], tab: null };

function send(message) {
  return new Promise((resolve, reject) => {
    chrome.runtime.sendMessage(message, (res) => {
      if (chrome.runtime.lastError) return reject(new Error(chrome.runtime.lastError.message));
      if (!res || !res.ok) return reject(new Error((res && res.error) || '알 수 없는 오류'));
      resolve(res);
    });
  });
}

function status(text, isError) {
  const el = $('status');
  el.textContent = text || '';
  el.classList.toggle('error', !!isError);
}

async function refresh() {
  state = await send({ type: 'GET_STATE' });
  render();
}

function render() {
  const { settings, items, tab } = state;

  $('count').textContent = `${items.length}건`;
  $('pageTitle').textContent = (tab && tab.title) || '페이지 없음';
  $('pageUrl').textContent = (tab && tab.url) || '';

  const single = settings.mode === 'single';
  $('captureBtn').textContent = single ? '이 페이지 바로 저장' : '이 페이지 담기';
  $('captureBtn').disabled = !(tab && tab.capturable);
  $('captureHint').textContent = tab && tab.capturable
    ? '본문 전체를 한 번에 읽어옵니다. (단축키 Alt+Shift+S)'
    : '일반 웹페이지(http/https)에서만 사용할 수 있습니다.';

  document.querySelectorAll('#modeSeg button').forEach((b) => {
    b.classList.toggle('on', b.dataset.mode === settings.mode);
  });
  $('modeHint').textContent = MODE_HINT[settings.mode] || '';

  $('format').value = settings.format;
  $('autoCapture').checked = !!settings.autoCapture;
  $('autoScroll').checked = !!settings.autoScroll;
  $('skipDuplicates').checked = !!settings.skipDuplicates;

  $('listCard').style.display = single && items.length === 0 ? 'none' : '';
  $('empty').style.display = items.length ? 'none' : '';
  $('exportMerged').disabled = !items.length;
  $('exportSeparate').disabled = !items.length;
  $('clearBtn').style.display = items.length ? '' : 'none';

  const list = $('list');
  list.textContent = '';
  items.forEach((it) => {
    const li = document.createElement('li');

    const body = document.createElement('div');
    body.className = 'it-body';
    const title = document.createElement('div');
    title.className = 'it-title';
    title.textContent = it.title;
    title.title = it.url;
    const meta = document.createElement('div');
    meta.className = 'it-meta';
    meta.textContent = `${new URL(it.url).hostname} · 약 ${it.charCount.toLocaleString()}자`;
    body.append(title, meta);

    const del = document.createElement('button');
    del.className = 'it-del';
    del.textContent = '×';
    del.title = '목록에서 제거';
    del.addEventListener('click', async () => {
      await send({ type: 'REMOVE_ITEM', id: it.id });
      await refresh();
    });

    li.append(body, del);
    list.appendChild(li);
  });
}

async function withBusy(button, label, fn) {
  const original = button.textContent;
  button.disabled = true;
  button.textContent = label;
  try {
    await fn();
  } catch (err) {
    status(err.message, true);
  } finally {
    button.textContent = original;
    button.disabled = false;
  }
}

/* ---- 이벤트 연결 ---- */

$('captureBtn').addEventListener('click', () => {
  withBusy($('captureBtn'), '읽는 중...', async () => {
    const res = await send({ type: 'CAPTURE_CURRENT' });
    if (res.status === 'duplicate') status('이미 수집한 페이지입니다.', true);
    else if (res.status === 'saved') status(`저장 완료 · ${res.filename}`);
    else status(`담았습니다. (총 ${res.count}건)`);
    await refresh();
  });
});

document.querySelectorAll('#modeSeg button').forEach((b) => {
  b.addEventListener('click', async () => {
    await send({ type: 'SET_SETTINGS', patch: { mode: b.dataset.mode } });
    status('');
    await refresh();
  });
});

$('format').addEventListener('change', async (e) => {
  await send({ type: 'SET_SETTINGS', patch: { format: e.target.value } });
  await refresh();
});

['autoCapture', 'autoScroll', 'skipDuplicates'].forEach((key) => {
  $(key).addEventListener('change', async (e) => {
    await send({ type: 'SET_SETTINGS', patch: { [key]: e.target.checked } });
    if (key === 'autoCapture') {
      status(e.target.checked ? '자동 수집 켜짐 · 페이지를 열 때마다 자동으로 담깁니다.' : '자동 수집 꺼짐');
    }
    await refresh();
  });
});

$('exportMerged').addEventListener('click', () => {
  withBusy($('exportMerged'), '저장 중...', async () => {
    const res = await send({ type: 'EXPORT', style: 'merged' });
    status(`${res.count}건을 하나의 문서로 저장했습니다.\n${res.filename}`);
    await refresh();
  });
});

$('exportSeparate').addEventListener('click', () => {
  withBusy($('exportSeparate'), '저장 중...', async () => {
    const res = await send({ type: 'EXPORT', style: 'separate' });
    status(`${res.count}건을 각각의 파일로 저장했습니다.\n${res.filename}`);
    await refresh();
  });
});

$('clearBtn').addEventListener('click', async () => {
  if (!confirm(`수집 목록 ${state.items.length}건을 모두 지울까요?`)) return;
  await send({ type: 'CLEAR_ITEMS' });
  status('목록을 비웠습니다.');
  await refresh();
});

refresh().catch((err) => status(err.message, true));

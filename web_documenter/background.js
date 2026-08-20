/*
 * background.js - 수집 목록 관리 / 저장(다운로드) / 자동 수집 제어
 */
'use strict';

const DEFAULT_SETTINGS = {
  mode: 'batch',          // 'batch' = 일괄(모아뒀다 한 번에) / 'single' = 건 별(즉시 저장)
  format: 'md',           // md | txt | doc | html
  autoCapture: false,     // 페이지를 열 때마다 자동 수집
  autoScroll: true,       // 저장 전 페이지 끝까지 자동 스크롤(지연 로딩 대응)
  skipDuplicates: true,   // 같은 URL 중복 수집 방지
  folder: '웹문서화'
};

// 파일명에 한글을 쓸 수 없는 환경에서 사용할 폴더 이름
const ASCII_FOLDER = 'WebDocs';

const FORMATS = {
  md: { ext: 'md', mime: 'text/markdown' },
  txt: { ext: 'txt', mime: 'text/plain' },
  doc: { ext: 'doc', mime: 'application/msword' },
  html: { ext: 'html', mime: 'text/html' }
};

/* ---------------------------------------------------------------- */
/* 저장소                                                            */
/* ---------------------------------------------------------------- */

async function getSettings() {
  const { settings } = await chrome.storage.local.get('settings');
  return { ...DEFAULT_SETTINGS, ...(settings || {}) };
}

async function setSettings(patch) {
  const next = { ...(await getSettings()), ...patch };
  await chrome.storage.local.set({ settings: next });
  return next;
}

async function getItems() {
  const { items } = await chrome.storage.local.get('items');
  return Array.isArray(items) ? items : [];
}

async function setItems(items) {
  await chrome.storage.local.set({ items });
  await updateBadge(items.length);
  return items;
}

async function updateBadge(count) {
  await chrome.action.setBadgeText({ text: count ? String(count) : '' });
  await chrome.action.setBadgeBackgroundColor({ color: '#2d6cdf' });
}

/* ---------------------------------------------------------------- */
/* 페이지 수집                                                       */
/* ---------------------------------------------------------------- */

function isCapturable(url) {
  return typeof url === 'string' && /^https?:\/\//i.test(url);
}

async function ensureContentScript(tabId) {
  try {
    await chrome.tabs.sendMessage(tabId, { type: 'WD_PING' });
    return;
  } catch (_) {
    // 아직 주입되지 않음
  }
  await chrome.scripting.executeScript({ target: { tabId }, files: ['content.js'] });
}

async function toast(tabId, text, tone) {
  try {
    await chrome.tabs.sendMessage(tabId, { type: 'WD_TOAST', text, tone });
  } catch (_) { /* 알림 실패는 무시 */ }
}

/**
 * 탭 하나를 수집한다. (설정에 따라 목록에 담거나 즉시 저장)
 * @returns {Promise<{status:'saved'|'queued'|'duplicate', title?:string, count?:number, filename?:string}>}
 */
async function captureTab(tabId) {
  const tab = await chrome.tabs.get(tabId);
  if (!isCapturable(tab.url)) {
    throw new Error('이 페이지는 수집할 수 없습니다. (일반 웹페이지에서 사용해 주세요)');
  }

  const settings = await getSettings();

  if (settings.skipDuplicates) {
    const items = await getItems();
    if (items.some((it) => it.url === tab.url)) {
      await toast(tabId, '이미 수집한 페이지입니다.', 'error');
      return { status: 'duplicate' };
    }
  }

  await ensureContentScript(tabId);
  const res = await chrome.tabs.sendMessage(tabId, {
    type: 'WD_CAPTURE',
    options: { autoScroll: settings.autoScroll }
  });

  if (!res || !res.ok) throw new Error((res && res.error) || '본문을 읽지 못했습니다.');

  const item = { id: `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`, ...res.doc };

  if (settings.mode === 'single') {
    const filename = await saveOne(item, settings);
    await toast(tabId, `저장 완료 · ${filename}`);
    return { status: 'saved', title: item.title, filename };
  }

  const items = await getItems();
  items.push(item);
  await setItems(items);
  await toast(tabId, `담기 완료 (${items.length}건) · ${item.charCount.toLocaleString()}자`);
  return { status: 'queued', title: item.title, count: items.length };
}

/* ---------------------------------------------------------------- */
/* 문서 생성 및 저장                                                 */
/* ---------------------------------------------------------------- */

function pad(n) { return String(n).padStart(2, '0'); }

function stamp(date = new Date()) {
  return `${date.getFullYear()}${pad(date.getMonth() + 1)}${pad(date.getDate())}_${pad(date.getHours())}${pad(date.getMinutes())}${pad(date.getSeconds())}`;
}

function humanTime(iso) {
  const d = new Date(iso);
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

function safeName(name, max = 60) {
  const cleaned = (name || '무제')
    .replace(/[\\/:*?"<>|\x00-\x1f]/g, ' ')
    .replace(/\s+/g, ' ')
    .replace(/^[.\s]+|[.\s]+$/g, '')
    .trim();
  return (cleaned || '무제').slice(0, max);
}

/** 한글을 지원하지 않는 환경(일부 브라우저/OS)을 위한 ASCII 전용 이름 */
function asciiName(name, fallback, max = 60) {
  const cleaned = (name || '')
    .replace(/[^\x20-\x7E]/g, ' ')
    .replace(/[\\/:*?"<>|.]/g, ' ')
    .replace(/\s+/g, '_')
    .replace(/^[._]+|[._]+$/g, '');
  return (cleaned || fallback).slice(0, max);
}

/** 제목을 ASCII 로 옮길 수 없을 때 쓰는 주소 기반 이름 (예: portal_co_kr_view) */
function urlSlug(url) {
  try {
    const u = new URL(url);
    const seg = decodeURIComponent(u.pathname).split('/').filter(Boolean).pop() || '';
    return asciiName(`${u.hostname}_${seg.replace(/\.[a-z0-9]+$/i, '')}`, 'page', 50);
  } catch (_) {
    return 'page';
  }
}

function itemMarkdown(item) {
  return [
    `# ${item.title}`,
    '',
    `- 출처: ${item.url}`,
    `- 수집 시각: ${humanTime(item.capturedAt)}`,
    `- 분량: 약 ${item.charCount.toLocaleString()}자`,
    '',
    '---',
    '',
    item.markdown,
    ''
  ].join('\n');
}

function itemText(item) {
  return [
    item.title,
    '='.repeat(Math.min(60, Math.max(10, item.title.length * 2))),
    `출처: ${item.url}`,
    `수집 시각: ${humanTime(item.capturedAt)}`,
    '',
    item.text,
    ''
  ].join('\n');
}

const HTML_STYLE = `
body{font-family:"맑은 고딕","Malgun Gothic",system-ui,sans-serif;font-size:11pt;line-height:1.7;color:#111;margin:24px;}
h1{font-size:18pt;border-bottom:2px solid #2d6cdf;padding-bottom:6px;margin-top:32px;}
h2{font-size:15pt;margin-top:24px;} h3{font-size:13pt;margin-top:18px;}
.wd-meta{font-size:9pt;color:#555;background:#f4f6fa;border-left:3px solid #2d6cdf;padding:8px 12px;margin:8px 0 18px;}
.wd-meta a{color:#2d6cdf;word-break:break-all;}
table{border-collapse:collapse;margin:12px 0;} td,th{border:1px solid #999;padding:5px 8px;font-size:10pt;}
th{background:#eef2f8;} img{max-width:100%;} pre{background:#f5f5f5;padding:10px;overflow:auto;}
blockquote{border-left:3px solid #ccc;margin:8px 0;padding-left:12px;color:#444;}
.wd-toc{background:#fafafa;border:1px solid #ddd;padding:12px 20px;margin-bottom:24px;}
hr{border:none;border-top:1px dashed #bbb;margin:32px 0;}
`;

function escapeHtml(s) {
  return String(s).replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
}

function itemHtmlSection(item, index) {
  return [
    `<section id="doc${index}">`,
    `<h1>${escapeHtml(item.title)}</h1>`,
    '<div class="wd-meta">',
    `출처: <a href="${escapeHtml(item.url)}">${escapeHtml(item.url)}</a><br>`,
    `수집 시각: ${humanTime(item.capturedAt)} · 분량: 약 ${item.charCount.toLocaleString()}자`,
    '</div>',
    item.html,
    '</section>'
  ].join('\n');
}

// Word 가 HTML 문서를 자기 형식으로 인식하도록 붙이는 머리말
const WORD_HEAD = [
  '<meta name="ProgId" content="Word.Document">',
  '<meta name="Generator" content="Microsoft Word">',
  '<!--[if gte mso 9]><xml><w:WordDocument><w:View>Print</w:View><w:Zoom>100</w:Zoom></w:WordDocument></xml><![endif]-->'
].join('\n');

function htmlDocument(title, bodyParts, toc, forWord) {
  return [
    '<!DOCTYPE html>',
    forWord
      ? '<html lang="ko" xmlns:o="urn:schemas-microsoft-com:office:office" xmlns:w="urn:schemas-microsoft-com:office:word" xmlns="http://www.w3.org/TR/REC-html40"><head>'
      : '<html lang="ko"><head>',
    '<meta charset="utf-8">',
    forWord ? WORD_HEAD : '',
    `<title>${escapeHtml(title)}</title>`,
    `<style>${HTML_STYLE}</style>`,
    '</head><body>',
    toc || '',
    bodyParts.join('\n<hr>\n'),
    '</body></html>'
  ].join('\n');
}

/** 수집 항목들을 선택한 형식의 파일 내용으로 만든다. */
function buildContent(items, format, mergedTitle) {
  const merged = items.length > 1 || !!mergedTitle;

  if (format === 'md') {
    if (!merged) return itemMarkdown(items[0]);
    const toc = items.map((it, i) => `${i + 1}. ${it.title}  \n   ${it.url}`).join('\n');
    return [
      `# ${mergedTitle}`,
      '',
      `- 총 ${items.length}건`,
      `- 저장 시각: ${humanTime(new Date().toISOString())}`,
      '',
      '## 목차',
      '',
      toc,
      '',
      '---',
      '',
      items.map(itemMarkdown).join('\n\n---\n\n')
    ].join('\n');
  }

  if (format === 'txt') {
    if (!merged) return itemText(items[0]);
    return [
      mergedTitle,
      `총 ${items.length}건 · 저장 시각: ${humanTime(new Date().toISOString())}`,
      '',
      items.map((it, i) => `${i + 1}. ${it.title}`).join('\n'),
      '',
      items.map((it, i) => `\n\n${'-'.repeat(70)}\n[${i + 1}/${items.length}]\n${'-'.repeat(70)}\n\n${itemText(it)}`).join('')
    ].join('\n');
  }

  // html / doc (doc 은 Word 가 여는 HTML 문서)
  const forWord = format === 'doc';
  const sections = items.map(itemHtmlSection);
  if (!merged) return htmlDocument(items[0].title, sections, '', forWord);
  const toc = [
    '<div class="wd-toc"><b>목차</b><ol>',
    items.map((it, i) => `<li><a href="#doc${i}">${escapeHtml(it.title)}</a></li>`).join(''),
    `</ol><div style="font-size:9pt;color:#555">총 ${items.length}건 · 저장 시각 ${humanTime(new Date().toISOString())}</div></div>`
  ].join('');
  return htmlDocument(mergedTitle, sections, toc, forWord);
}

function utf8ToBase64(str) {
  const bytes = new TextEncoder().encode(str);
  let binary = '';
  const CHUNK = 0x8000;
  for (let i = 0; i < bytes.length; i += CHUNK) {
    binary += String.fromCharCode.apply(null, bytes.subarray(i, i + CHUNK));
  }
  return btoa(binary);
}

// 브라우저에 따라 다운로드 파일명에 한글을 허용하지 않는 경우가 있어,
// 한 번 실패하면 그 이후로는 ASCII 이름을 바로 사용한다.
let unicodeFilenameOk = true;

/**
 * 파일을 내려받는다.
 * @param {{dir:string, base:string, ext:string, asciiDir:string, asciiBase:string}} name
 * @returns {Promise<string>} 실제로 저장된 경로
 */
async function download(name, content, mime) {
  const url = `data:${mime};charset=utf-8;base64,${utf8ToBase64(content)}`;
  const primary = `${name.dir}/${name.base}.${name.ext}`;
  const fallback = `${name.asciiDir}/${name.asciiBase}.${name.ext}`;

  if (unicodeFilenameOk) {
    try {
      await chrome.downloads.download({ url, filename: primary, saveAs: false, conflictAction: 'uniquify' });
      return primary;
    } catch (err) {
      if (!/filename/i.test(String((err && err.message) || err))) throw err;
      unicodeFilenameOk = false;
    }
  }
  await chrome.downloads.download({ url, filename: fallback, saveAs: false, conflictAction: 'uniquify' });
  return fallback;
}

function itemName(item, settings, prefix) {
  const time = stamp();
  return {
    dir: settings.folder,
    asciiDir: ASCII_FOLDER,
    base: `${prefix || time}_${safeName(item.title)}`,
    asciiBase: `${prefix || time}_${asciiName(item.title, urlSlug(item.url))}`,
    ext: (FORMATS[settings.format] || FORMATS.md).ext
  };
}

async function saveOne(item, settings) {
  const fmt = FORMATS[settings.format] || FORMATS.md;
  return download(itemName(item, settings), buildContent([item], settings.format, ''), fmt.mime);
}

/** 일괄 저장: merged(하나로 합침) 또는 separate(건별 파일) */
async function exportAll(style) {
  const settings = await getSettings();
  const items = await getItems();
  if (!items.length) throw new Error('수집한 페이지가 없습니다.');

  const fmt = FORMATS[settings.format] || FORMATS.md;
  const time = stamp();

  if (style === 'separate') {
    let saved = '';
    for (let i = 0; i < items.length; i++) {
      const seq = String(i + 1).padStart(3, '0');
      const name = itemName(items[i], settings, seq);
      name.dir = `${settings.folder}/모음_${time}`;
      name.asciiDir = `${ASCII_FOLDER}/collection_${time}`;
      saved = await download(name, buildContent([items[i]], settings.format, ''), fmt.mime);
    }
    return { count: items.length, filename: saved.slice(0, saved.lastIndexOf('/') + 1) };
  }

  const title = `수집 문서 모음 (${items.length}건)`;
  const filename = await download({
    dir: settings.folder,
    asciiDir: ASCII_FOLDER,
    base: `모음_${time}_${items.length}건`,
    asciiBase: `collection_${time}_${items.length}items`,
    ext: fmt.ext
  }, buildContent(items, settings.format, title), fmt.mime);

  return { count: items.length, filename };
}

/* ---------------------------------------------------------------- */
/* 자동 수집 (페이지를 클릭해 이동할 때마다)                          */
/* ---------------------------------------------------------------- */

const autoTimers = new Map();   // tabId -> timeoutId
const lastAutoUrl = new Map();  // tabId -> url

function scheduleAutoCapture(tabId, url, delay) {
  clearTimeout(autoTimers.get(tabId));
  autoTimers.set(tabId, setTimeout(async () => {
    autoTimers.delete(tabId);
    try {
      const settings = await getSettings();
      if (!settings.autoCapture) return;
      const tab = await chrome.tabs.get(tabId);
      if (!isCapturable(tab.url) || tab.url !== url) return;
      if (lastAutoUrl.get(tabId) === tab.url) return;
      lastAutoUrl.set(tabId, tab.url);
      await captureTab(tabId);
    } catch (err) {
      console.warn('[웹 본문 문서화] 자동 수집 실패:', err);
    }
  }, delay));
}

chrome.tabs.onUpdated.addListener((tabId, changeInfo, tab) => {
  if (!isCapturable(tab.url)) return;
  if (changeInfo.status === 'complete') {
    scheduleAutoCapture(tabId, tab.url, 900);
  } else if (changeInfo.url) {
    // SPA(주소만 바뀌는 화면 전환) 대응
    scheduleAutoCapture(tabId, changeInfo.url, 1800);
  }
});

chrome.tabs.onRemoved.addListener((tabId) => {
  clearTimeout(autoTimers.get(tabId));
  autoTimers.delete(tabId);
  lastAutoUrl.delete(tabId);
});

/* ---------------------------------------------------------------- */
/* 메시지 / 단축키 / 설치                                            */
/* ---------------------------------------------------------------- */

const HANDLERS = {
  async GET_STATE() {
    const [settings, items] = await Promise.all([getSettings(), getItems()]);
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
    return {
      settings,
      items: items.map(({ id, title, url, charCount, capturedAt }) => ({ id, title, url, charCount, capturedAt })),
      tab: tab ? { id: tab.id, title: tab.title, url: tab.url, capturable: isCapturable(tab.url) } : null
    };
  },
  async SET_SETTINGS(msg) {
    return { settings: await setSettings(msg.patch || {}) };
  },
  async CAPTURE_CURRENT() {
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
    if (!tab) throw new Error('활성 탭을 찾을 수 없습니다.');
    return captureTab(tab.id);
  },
  async REMOVE_ITEM(msg) {
    const items = (await getItems()).filter((it) => it.id !== msg.id);
    await setItems(items);
    return { count: items.length };
  },
  async CLEAR_ITEMS() {
    await setItems([]);
    return { count: 0 };
  },
  async EXPORT(msg) {
    const result = await exportAll(msg.style);
    if (msg.clearAfter) await setItems([]);
    return result;
  }
};

chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
  const handler = msg && HANDLERS[msg.type];
  if (!handler) return;
  handler(msg)
    .then((data) => sendResponse({ ok: true, ...data }))
    .catch((err) => sendResponse({ ok: false, error: String((err && err.message) || err) }));
  return true;
});

chrome.commands.onCommand.addListener(async (command) => {
  if (command !== 'capture-page') return;
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  if (!tab) return;
  try {
    await captureTab(tab.id);
  } catch (err) {
    await toast(tab.id, String((err && err.message) || err), 'error');
  }
});

chrome.runtime.onInstalled.addListener(async () => {
  await setSettings({});
  await updateBadge((await getItems()).length);
});

chrome.runtime.onStartup.addListener(async () => {
  await updateBadge((await getItems()).length);
});

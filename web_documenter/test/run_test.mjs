/*
 * 확장 기능 검증 스크립트 (Playwright + Chromium)
 *
 * 실행:
 *   npm install --no-save playwright
 *   node test/run_test.mjs
 *
 * 실제 Chromium 에 확장을 로드해 수집 → 변환 → 저장까지 확인한다.
 */
import { chromium } from 'playwright';
import http from 'node:http';
import fs from 'node:fs';
import path from 'node:path';
import os from 'node:os';
import { fileURLToPath } from 'node:url';
import zlib from 'node:zlib';

/** .pptx(ZIP) 안의 파일을 읽는다. 중앙 디렉터리를 직접 훑어 외부 라이브러리를 쓰지 않는다. */
function readZip(buffer) {
  const end = buffer.lastIndexOf(Buffer.from([0x50, 0x4b, 0x05, 0x06]));
  const count = buffer.readUInt16LE(end + 10);
  let at = buffer.readUInt32LE(end + 16);
  const files = new Map();
  const order = [];

  for (let i = 0; i < count; i++) {
    const method = buffer.readUInt16LE(at + 10);
    const compressed = buffer.readUInt32LE(at + 20);
    const raw = buffer.readUInt32LE(at + 24);
    const nameLen = buffer.readUInt16LE(at + 28);
    const extraLen = buffer.readUInt16LE(at + 30);
    const commentLen = buffer.readUInt16LE(at + 32);
    const offset = buffer.readUInt32LE(at + 42);
    const name = buffer.toString('utf8', at + 46, at + 46 + nameLen);

    const localNameLen = buffer.readUInt16LE(offset + 26);
    const localExtraLen = buffer.readUInt16LE(offset + 28);
    const start = offset + 30 + localNameLen + localExtraLen;
    const body = buffer.subarray(start, start + compressed);
    const data = method === 8 ? zlib.inflateRawSync(body) : body;
    if (data.length !== raw) throw new Error(`${name}: 크기 불일치`);

    files.set(name, data);
    order.push(name);
    at += 46 + nameLen + extraLen + commentLen;
  }
  return { files, order };
}

const HERE = path.dirname(fileURLToPath(import.meta.url));
const SITE = path.join(HERE, 'fixtures');
const OUT = path.join(HERE, 'out');
const EXT = path.dirname(HERE);

const MIME = { '.html': 'text/html; charset=utf-8', '.png': 'image/png', '.jpg': 'image/jpeg', '.svg': 'image/svg+xml' };
const server = http.createServer((req, res) => {
  const file = path.join(SITE, decodeURIComponent(req.url.split('?')[0]).replace(/^\/+/, '') || 'board.html');
  fs.readFile(file, (err, data) => {
    if (err) { res.writeHead(404); res.end('nope'); return; }
    res.writeHead(200, { 'Content-Type': MIME[path.extname(file)] || 'application/octet-stream' });
    res.end(data);
  });
});
await new Promise((r) => server.listen(8931, r));
const base = 'http://localhost:8931';

const userDir = fs.mkdtempSync(path.join(os.tmpdir(), 'wd-profile-'));
const downloadDir = fs.mkdtempSync(path.join(os.tmpdir(), 'wd-dl-'));

const ctx = await chromium.launchPersistentContext(userDir, {
  channel: 'chromium',
  headless: true,
  downloadsPath: downloadDir,
  args: [`--disable-extensions-except=${EXT}`, `--load-extension=${EXT}`],
});

// 인쇄 대화상자는 자동 검증이 불가능하므로 호출만 가로채 기록한다.
await ctx.addInitScript(() => { window.print = () => { window.__wdPrinted = (window.__wdPrinted || 0) + 1; }; });

// service worker 준비 대기
let sw = ctx.serviceWorkers()[0];
if (!sw) sw = await ctx.waitForEvent('serviceworker', { timeout: 15000 });
console.log('service worker:', sw.url());

const fail = [];
const check = (name, cond, extra = '') => {
  console.log(`${cond ? '  PASS' : '  FAIL'}  ${name}${extra ? ' :: ' + extra : ''}`);
  if (!cond) fail.push(name);
};

const swCall = (fn, ...args) => sw.evaluate(fn, ...args);

// ---------------------------------------------------------------- 1. 게시판 페이지 수집
const page = await ctx.newPage();
await page.goto(`${base}/board.html`);
await page.waitForLoadState('networkidle');

const call = (type, extra = {}) => swCall(
  async ({ type, extra }) => {
    try { return { ok: true, ...(await HANDLERS[type]({ type, ...extra })) }; }
    catch (e) { return { ok: false, error: String(e && e.message || e) }; }
  }, { type, extra });
const capture = () => call('CAPTURE_CURRENT');

await call('SET_SETTINGS', { patch: { mode: 'batch', autoScroll: false, autoCapture: false, format: 'md', includeImages: false } });

const res1 = await capture();
check('게시판 수집 성공', res1 && res1.ok === true, JSON.stringify(res1).slice(0, 200));

const state1 = await call('GET_STATE');
check('목록 1건', state1.items.length === 1, `items=${state1.items.length}`);

const { items } = await swCall(() => chrome.storage.local.get('items'));
const doc = items[0];
console.log('\n----- 추출된 Markdown -----\n' + doc.markdown + '\n---------------------------\n');
console.log('제목:', doc.title, '| 글자수:', doc.charCount);

const md = doc.markdown;
check('제목 추출(og:title)', doc.title === '3분기 결산 프로세스 안내', doc.title);
check('본문 문단 포함', md.includes('결산 일정') && md.includes('협조에 감사드립니다'));
check('강조 변환', md.includes('**결산 일정**'));
check('표 변환', md.includes('| 구분 | 기간 | 담당 |') && md.includes('| 전표 마감 | 9/25 ~ 9/28 | 각 부서 |'));
check('중첩 목록 들여쓰기', /- 지출 결의서 원본/.test(md) && /\n {2}- 10만원 초과 건은 견적서 첨부/.test(md));
check('번호 목록', md.includes('1. ERP 접속 후'));
check('코드블록', md.includes('```') && md.includes('A: 승인완료'));
check('인라인 코드', md.includes('`일반전표`'));
check('인용문', md.includes('> 문의: 회계팀'));
check('링크 절대경로', md.includes('](http://localhost:8931/download/stock.xlsx)'));
check('내비게이션 제거', !md.includes('공지사항') && !md.includes('본문 바로가기'));
check('사이드바/배너 제거', !md.includes('동호회 모집 배너') && !md.includes('관련글 1'));
check('푸터 제거', !md.includes('Copyright 2026') && !md.includes('대표전화'));
check('댓글/페이징 제거', !md.includes('댓글 3') && !md.includes('확인했습니다'));
check('숨김 요소 제거', !md.includes('숨김 탭 내용'));
check('스크립트 제거', !md.includes('tracking'));

// ---------------------------------------------------------------- 2. 중복 방지
const res2 = await capture();
check('중복 수집 차단', res2.status === 'duplicate', JSON.stringify(res2));

// ---------------------------------------------------------------- 3. 자동 스크롤(지연 로딩)
await call('SET_SETTINGS', { patch: { autoScroll: true } });
await page.goto(`${base}/lazy.html`);
await page.waitForLoadState('networkidle');
const res3 = await capture();
check('지연 로딩 페이지 수집', res3.ok === true, JSON.stringify(res3).slice(0, 200));

const { items: items2 } = await swCall(() => chrome.storage.local.get('items'));
const lazy = items2[items2.length - 1];
check('자동 스크롤로 추가 문단 확보', lazy.markdown.includes('5번째 문단'), lazy.markdown.slice(-160).replace(/\n/g, ' '));
check('원래 스크롤 위치 복원', (await page.evaluate(() => window.scrollY)) === 0);

// ---------------------------------------------------------------- 4. 형식별 저장(일괄 병합)
// chrome.downloads 로 저장되므로 Playwright download 이벤트가 아니라 다운로드 기록을 확인한다.
const waitDownloads = async (sinceId) => {
  for (let i = 0; i < 40; i++) {
    const list = await swCall(async (since) => {
      const all = await chrome.downloads.search({});
      return all.filter((d) => d.id > since).map((d) => ({ id: d.id, state: d.state, filename: d.filename }));
    }, sinceId);
    if (list.length && list.every((d) => d.state === 'complete')) return list.sort((a, b) => a.id - b.id);
    await new Promise((r) => setTimeout(r, 250));
  }
  return [];
};
const lastDownloadId = async () => swCall(async () => {
  const all = await chrome.downloads.search({});
  return all.reduce((m, d) => Math.max(m, d.id), 0);
});

for (const f of ['md', 'doc', 'html', 'txt']) {
  await call('SET_SETTINGS', { patch: { format: f } });
  const since = await lastDownloadId();
  const exp = await call('EXPORT', { style: 'merged' });
  const dl = await waitDownloads(since);
  const body = dl.length ? fs.readFileSync(dl[0].filename, 'utf8') : '';
  fs.mkdirSync(OUT, { recursive: true });
  if (body) fs.writeFileSync(path.join(OUT, `sample.${f}`), body); // 눈으로 확인용 결과물
  check(`일괄(합침) 저장 .${f}`, exp.ok && exp.count === 2 && dl.length === 1 && body.length > 400,
    `${exp.filename || exp.error} / ${body.length}bytes`);
  // Playwright 는 다운로드 파일을 GUID 이름으로 보관하므로, 확장이 요청한 경로로 검증한다.
  check(`.${f} 저장 경로/본문 정상`, new RegExp(`(모음_|collection_)\\d{8}_\\d{6}_2(건|items)\\.${f}$`).test(exp.filename || '')
    && body.includes('결산') && body.includes('지연 로딩'), exp.filename);
  if (f === 'md') check('.md 목차 포함', body.includes('## 목차') && body.includes('1. 3분기 결산 프로세스 안내'));
  if (f === 'doc' || f === 'html') check(`.${f} HTML 구조`, body.startsWith('<!DOCTYPE html>') && body.includes('<table>'));
  if (f === 'txt') check('.txt 마크업 제거', !body.includes('**') && !body.includes('```') && !body.includes('# '));
}

// ---------------------------------------------------------------- 5. 건별 파일로 일괄 저장
await call('SET_SETTINGS', { patch: { format: 'md' } });
const since5 = await lastDownloadId();
const expSep = await call('EXPORT', { style: 'separate' });
const dl5 = await waitDownloads(since5);
check('건별 파일 저장', expSep.ok && dl5.length === 2, `downloads=${dl5.length} folder=${expSep.filename}`);
check('건별 저장 폴더 분리', /(모음_|collection_)\d{8}_\d{6}\/$/.test(expSep.filename || ''), expSep.filename);
check('건별 파일 내용', dl5.every((d) => fs.readFileSync(d.filename, 'utf8').includes('출처: http://localhost:8931')));

// ---------------------------------------------------------------- 6. 건 별 모드(수집 즉시 저장)
await call('SET_SETTINGS', { patch: { mode: 'single', skipDuplicates: false } });
const since6 = await lastDownloadId();
const res6 = await capture();
const dl6 = await waitDownloads(since6);
check('건 별 모드 즉시 저장', res6.status === 'saved' && dl6.length === 1, `${res6.filename || res6.error}`);
const stateAfter = await call('GET_STATE');
check('건 별 모드는 목록에 쌓지 않음', stateAfter.items.length === 2, `items=${stateAfter.items.length}`);

// ---------------------------------------------------------------- 7. 자동 수집
await call('SET_SETTINGS', { patch: { mode: 'batch', autoCapture: true, skipDuplicates: true, autoScroll: false } });
await call('CLEAR_ITEMS');
const page2 = await ctx.newPage();
await page2.goto(`${base}/board.html`);
await new Promise((r) => setTimeout(r, 4000));
const stateAuto = await call('GET_STATE');
check('자동 수집 동작', stateAuto.items.length === 1, `items=${stateAuto.items.length}`);
await page2.goto(`${base}/lazy.html`);
await new Promise((r) => setTimeout(r, 4000));
const stateAuto2 = await call('GET_STATE');
check('자동 수집 - 이동할 때마다 누적', stateAuto2.items.length === 2, `items=${stateAuto2.items.length}`);

// ---------------------------------------------------------------- 8. 팝업 화면
const popup = await ctx.newPage();
await popup.goto(`chrome-extension://${new URL(sw.url()).host}/popup.html`);
await popup.waitForTimeout(1000);
const p1 = await popup.evaluate(() => ({
  count: document.getElementById('count').textContent,
  items: document.querySelectorAll('#list li').length,
  btn: document.getElementById('captureBtn').textContent.trim(),
  mode: document.querySelector('#modeSeg button.on').dataset.mode,
  autoCapture: document.getElementById('autoCapture').checked,
  err: document.getElementById('status').classList.contains('error') ? document.getElementById('status').textContent : ''
}));
check('팝업 상태 반영', p1.items === 2 && p1.count === '2건' && p1.mode === 'batch' && p1.autoCapture && !p1.err, JSON.stringify(p1));
await popup.screenshot({ path: path.join(OUT, 'popup.png'), fullPage: true });

// 팝업에서 모드 전환이 저장되는지
await popup.click('#modeSeg button[data-mode="single"]');
await popup.waitForTimeout(600);
const p2 = await popup.evaluate(() => ({
  btn: document.getElementById('captureBtn').textContent.trim(),
  mode: document.querySelector('#modeSeg button.on').dataset.mode
}));
const savedMode = (await call('GET_STATE')).settings.mode;
check('팝업에서 저장 방식 전환', p2.mode === 'single' && savedMode === 'single' && p2.btn === '이 페이지 바로 저장', JSON.stringify(p2));

// 목록에서 개별 삭제
await popup.click('#modeSeg button[data-mode="batch"]');
await popup.waitForTimeout(400);
await popup.click('#list li:first-child .it-del');
await popup.waitForTimeout(600);
const p3 = await popup.evaluate(() => document.querySelectorAll('#list li').length);
check('팝업에서 개별 삭제', p3 === 1 && (await call('GET_STATE')).items.length === 1, `items=${p3}`);
await popup.close(); // 이후 검증은 일반 웹페이지 탭에서 진행한다

// ---------------------------------------------------------------- 9. 본문 그림 포함
await call('CLEAR_ITEMS');
await call('SET_SETTINGS', { patch: { autoCapture: false, includeImages: false, skipDuplicates: false, format: 'md' } });
await page.bringToFront();
await page.goto(`${base}/board.html`);
await page.waitForLoadState('networkidle');

// (1) 그림 포함 끔 → 원본 주소 유지
await capture();
let stored = (await swCall(() => chrome.storage.local.get('items'))).items || [];
if (!stored.length) { console.log('  (수집 실패)', JSON.stringify(await capture())); }
const noImg = stored[stored.length - 1] || { markdown: '', html: '', text: '' };
check('그림 포함 끔 - 원본 주소 유지',
  noImg.markdown.includes(`![ERP 전표입력 화면](${base}/photo.png)`) && !noImg.html.includes('data:image'),
  `data URI 없음=${!noImg.html.includes('data:image')}`);

// (2) 그림 포함 켬 → 문서 안에 그림 데이터가 들어감
await call('SET_SETTINGS', { patch: { includeImages: true } });
await capture();
stored = (await swCall(() => chrome.storage.local.get('items'))).items;
const withImg = stored[stored.length - 1];
const dataUris = (withImg.html.match(/data:image\/[a-z+]+;base64,/g) || []);
check('그림 포함 켬 - 문서에 그림 데이터 포함', dataUris.length === 1 && withImg.imageCount === 1,
  `data URI ${dataUris.length}개, imageCount=${withImg.imageCount}`);
check('큰 그림은 줄여서 압축', dataUris[0] === 'data:image/jpeg;base64,', dataUris[0]);
check('아이콘·추적픽셀 제외', !withImg.markdown.includes('작은 아이콘') && !withImg.markdown.includes('pixel.png'));
check('markdown 에도 그림 포함', withImg.markdown.includes('![ERP 전표입력 화면](data:image/jpeg;base64,'));
check('그림 설명(figcaption) 유지', withImg.markdown.includes('[그림 1] ERP 전표입력 화면'));
check('txt 는 그림 데이터 없이 설명만', !withImg.text.includes('data:image') && withImg.text.includes('[ERP 전표입력 화면]'),
  withImg.text.slice(0, 60).replace(/\n/g, ' '));

const withImgSize = withImg.html.length;
check('그림 크기 조절됨(원본 809KB → 문서 내 500KB 미만)', withImgSize < 500 * 1024,
  `${Math.round(withImgSize / 1024)}KB`);

// 그림이 포함된 HTML 문서 저장
await call('SET_SETTINGS', { patch: { format: 'html' } });
const sinceImg = await lastDownloadId();
const expImg = await call('EXPORT', { style: 'merged' });
const dlImg = await waitDownloads(sinceImg);
const bodyImg = dlImg.length ? fs.readFileSync(dlImg[0].filename, 'utf8') : '';
fs.writeFileSync(path.join(OUT, 'sample_with_image.html'), bodyImg);
check('그림 포함 HTML 저장', expImg.ok && bodyImg.includes('<img src="data:image/jpeg;base64,'),
  `${Math.round(bodyImg.length / 1024)}KB`);

// ---------------------------------------------------------------- 10. PDF (인쇄 창으로 저장)
await call('CLEAR_ITEMS');
await call('SET_SETTINGS', { patch: { format: 'pdf', mode: 'batch', includeImages: true } });
await page.goto(`${base}/board.html`);
await page.waitForLoadState('networkidle');
await capture();
await page.goto(`${base}/lazy.html`);
await page.waitForLoadState('networkidle');
await capture();

const before = ctx.pages().length;
const expPdf = await call('EXPORT', { style: 'merged' });
await new Promise((r) => setTimeout(r, 2500));
const printPages = ctx.pages().filter((p) => p.url().includes('print.html'));
check('PDF - 인쇄 탭 열림', expPdf.ok && expPdf.printing === true && printPages.length === 1,
  `${expPdf.filename} / 탭 ${ctx.pages().length - before}개`);

const printPage = printPages[0];
await printPage.waitForLoadState('networkidle');
await printPage.waitForTimeout(1200);
const pdfInfo = await printPage.evaluate(() => ({
  title: document.title,
  printed: window.__wdPrinted || 0,
  images: document.images.length,
  loaded: Array.from(document.images).every((i) => i.complete && i.naturalWidth > 0),
  tables: document.querySelectorAll('table').length,
  sections: document.querySelectorAll('section').length,
  toc: !!document.querySelector('.wd-toc'),
  pageBreak: getComputedStyle(document.querySelectorAll('section')[1]).pageBreakBefore,
  barHidden: getComputedStyle(document.getElementById('wd-bar')).display
}));
check('PDF - 파일 이름이 문서 제목으로 지정됨', /^모음_\d{8}_\d{6}_2건$/.test(pdfInfo.title), pdfInfo.title);
check('PDF - 인쇄 창 자동 호출', pdfInfo.printed === 1, `print() ${pdfInfo.printed}회`);
check('PDF - 그림이 모두 로드된 뒤 인쇄', pdfInfo.images === 1 && pdfInfo.loaded, JSON.stringify(pdfInfo.images));
check('PDF - 목차/문서별 쪽 나눔', pdfInfo.toc && pdfInfo.sections === 2 && pdfInfo.pageBreak === 'always', pdfInfo.pageBreak);
check('PDF - 표 유지', pdfInfo.tables === 1);
check('PDF - 안내 막대는 화면에만 표시', pdfInfo.barHidden !== 'none');
await printPage.screenshot({ path: path.join(OUT, 'print_preview.png'), fullPage: true });
await printPage.close();

// 저장된 인쇄 데이터는 한 번 쓰고 지워진다
const leftover = await swCall(async () => Object.keys(await chrome.storage.local.get(null)).filter((k) => k.startsWith('print_')).length);
check('PDF - 임시 데이터 정리', leftover === 0, `남은 항목 ${leftover}개`);

// 건별 PDF: 문서 수만큼 탭이 열리고, 보이는 탭만 인쇄된다
const beforeSep = ctx.pages().length;
const expPdfSep = await call('EXPORT', { style: 'separate' });
await new Promise((r) => setTimeout(r, 2500));
const sepPages = ctx.pages().filter((p) => p.url().includes('print.html'));
check('PDF - 건별 저장은 문서마다 탭', expPdfSep.printing && sepPages.length === 2,
  `탭 ${ctx.pages().length - beforeSep}개`);
const printedCounts = await Promise.all(sepPages.map((p) => p.evaluate(() => window.__wdPrinted || 0)));
check('PDF - 첫 탭만 인쇄 창 호출(나머지는 탭을 볼 때)', printedCounts.filter((n) => n > 0).length === 1,
  printedCounts.join(', '));
for (const p of sepPages) await p.close();

// ---------------------------------------------------------------- 11. 자동 수집 중에는 인쇄 창을 띄우지 않음
await call('CLEAR_ITEMS');
await call('SET_SETTINGS', { patch: { mode: 'single', format: 'pdf', autoCapture: true, skipDuplicates: false, includeImages: false } });
const page3 = await ctx.newPage();
await page3.goto(`${base}/board.html`);
await new Promise((r) => setTimeout(r, 4000));
const autoPdf = await call('GET_STATE');
const autoPrintTabs = ctx.pages().filter((p) => p.url().includes('print.html')).length;
check('자동 수집 + PDF - 인쇄 창 대신 목록에 담김', autoPdf.items.length === 1 && autoPrintTabs === 0,
  `목록 ${autoPdf.items.length}건 / 인쇄탭 ${autoPrintTabs}개`);
await page3.close();
await call('SET_SETTINGS', { patch: { autoCapture: false, mode: 'batch', format: 'md' } });

// ---------------------------------------------------------------- 12. 버전이 어긋난 상태(확장 새로고침 안 함) 방어
const st = await call('GET_STATE');
check('실행 중인 코드의 버전/지원 형식 제공', !!st.build && Array.isArray(st.formats) && st.formats.includes('pdf'),
  `build=${st.build} formats=${(st.formats || []).join(',')}`);

const badFormat = await call('SET_SETTINGS', { patch: { format: 'pdfx' } });
check('알 수 없는 형식은 조용히 다른 파일로 저장하지 않음',
  badFormat.ok === false && /새로고침/.test(badFormat.error || ''), badFormat.error);
const keptFormat = (await call('GET_STATE')).settings.format;
check('잘못된 형식은 설정에 저장되지 않음', keptFormat !== 'pdfx', `format=${keptFormat}`);

// ---------------------------------------------------------------- 13. 팝업 화면으로 PDF 저장까지 (실사용 경로)
await call('CLEAR_ITEMS');
await call('SET_SETTINGS', { patch: { mode: 'batch', format: 'md', includeImages: false, autoCapture: false } });
await page.bringToFront();
await page.goto(`${base}/board.html`);
await page.waitForLoadState('networkidle');
await capture();

const ui = await ctx.newPage();
await ui.goto(`chrome-extension://${new URL(sw.url()).host}/popup.html`);
await ui.waitForTimeout(700);
await ui.selectOption('#format', 'pdf');
await ui.waitForTimeout(500);
check('팝업에서 PDF 선택이 저장됨', (await call('GET_STATE')).settings.format === 'pdf');
check('팝업에 PDF 안내 문구 표시',
  /PDF로 저장/.test(await ui.$eval('#formatHint', (e) => e.textContent)));

const beforeUi = ctx.pages().length;
await ui.click('#exportMerged');
await ui.waitForTimeout(2500);
const uiPrintTabs = ctx.pages().filter((p) => p.url().includes('print.html'));
check('팝업 버튼으로 PDF 저장 시 인쇄 탭 열림', uiPrintTabs.length === 1,
  `탭 ${ctx.pages().length - beforeUi}개 / 상태: ${await ui.$eval('#status', (e) => e.textContent.replace(/\n/g, ' '))}`);
for (const p of uiPrintTabs) await p.close();

// 버전이 어긋나면 팝업이 새로고침 안내를 띄운다
await ui.evaluate(() => { state.build = '0.0.0'; render(); });
const warn = await ui.evaluate(() => ({
  shown: getComputedStyle(document.getElementById('stale')).display !== 'none',
  text: document.getElementById('stale').textContent
}));
check('버전 불일치 시 새로고침 안내 표시', warn.shown && /새로고침/.test(warn.text),
  warn.text.slice(0, 40));
await ui.close();

// ---------------------------------------------------------------- 14. PowerPoint(.pptx) 저장
await call('CLEAR_ITEMS');
await call('SET_SETTINGS', { patch: { mode: 'batch', format: 'pptx', includeImages: true, autoScroll: false } });
await page.bringToFront();
await page.goto(`${base}/board.html`);
await page.waitForLoadState('networkidle');
await capture();
await page.goto(`${base}/lazy.html`);
await page.waitForLoadState('networkidle');
await capture();

const sincePptx = await lastDownloadId();
const expPptx = await call('EXPORT', { style: 'merged' });
const dlPptx = await waitDownloads(sincePptx);
check('pptx 저장', expPptx.ok && /\.pptx$/.test(expPptx.filename || '') && dlPptx.length === 1,
  expPptx.filename || expPptx.error);

if (dlPptx.length) {
  const target = path.join(OUT, 'sample.pptx');
  fs.copyFileSync(dlPptx[0].filename, target);
  const size = fs.statSync(target).size;
  check('pptx 파일 생성 (그림 포함)', size > 50 * 1024, `${Math.round(size / 1024)}KB`);
}

// ---------------------------------------------------------------- 15. pptx 파일 구조 검증
if (fs.existsSync(path.join(OUT, 'sample.pptx'))) {
  const buf = fs.readFileSync(path.join(OUT, 'sample.pptx'));
  const { files, order } = readZip(buf);
  const text = (name) => (files.get(name) || Buffer.alloc(0)).toString('utf8');

  check('pptx - [Content_Types].xml 이 첫 항목', order[0] === '[Content_Types].xml', order[0]);

  const required = ['[Content_Types].xml', '_rels/.rels', 'ppt/presentation.xml',
    'ppt/_rels/presentation.xml.rels', 'ppt/theme/theme1.xml',
    'ppt/slideMasters/slideMaster1.xml', 'ppt/slideMasters/_rels/slideMaster1.xml.rels',
    'ppt/slideLayouts/slideLayout1.xml', 'ppt/slideLayouts/_rels/slideLayout1.xml.rels'];
  const missing = required.filter((f) => !files.has(f));
  check('pptx - 필수 구성 파일 모두 존재', missing.length === 0, missing.join(', '));

  const slideNames = order.filter((n) => /^ppt\/slides\/slide\d+\.xml$/.test(n));
  const sldIds = (text('ppt/presentation.xml').match(/<p:sldId /g) || []).length;
  const overrides = (text('[Content_Types].xml').match(/presentationml\.slide\+xml/g) || []).length;
  check('pptx - 슬라이드 수가 목록/형식 선언과 일치',
    slideNames.length > 4 && slideNames.length === sldIds && sldIds === overrides,
    `슬라이드 ${slideNames.length} / 목록 ${sldIds} / 형식선언 ${overrides}`);

  // 모든 XML 이 올바른 형식인지 브라우저 파서로 확인한다.
  const xmlNames = order.filter((n) => n.endsWith('.xml') || n.endsWith('.rels'));
  const badXml = await page.evaluate((docs) => docs.filter(([, body]) => {
    const doc = new DOMParser().parseFromString(body, 'application/xml');
    return doc.getElementsByTagName('parsererror').length > 0;
  }).map(([name]) => name), xmlNames.map((n) => [n, text(n)]));
  check('pptx - 모든 XML 이 올바른 형식', badXml.length === 0, badXml.join(', '));

  // 슬라이드마다 레이아웃 연결이 있어야 PowerPoint 가 연다
  const noLayout = slideNames.filter((n) => {
    const rels = text(n.replace('ppt/slides/', 'ppt/slides/_rels/') + '.rels');
    return !rels.includes('slideLayout1.xml');
  });
  check('pptx - 슬라이드마다 레이아웃 연결', noLayout.length === 0, noLayout.join(', '));

  // 그림: 슬라이드가 참조하는 media 파일이 실제로 들어 있어야 한다
  const mediaFiles = order.filter((n) => n.startsWith('ppt/media/'));
  const brokenImage = slideNames.some((n) => {
    const rels = text(n.replace('ppt/slides/', 'ppt/slides/_rels/') + '.rels');
    return Array.from(rels.matchAll(/Target="\.\.\/media\/([^"]+)"/g))
      .some((m) => !files.has(`ppt/media/${m[1]}`));
  });
  check('pptx - 그림이 파일 안에 포함됨', mediaFiles.length === 1 && !brokenImage,
    mediaFiles.join(', '));

  const allSlides = slideNames.map(text).join('');
  check('pptx - 표가 표 개체로 들어감', allSlides.includes('<a:tbl>') && allSlides.includes('전표 마감'));
  check('pptx - 그림 개체 포함', allSlides.includes('<p:pic>'));
  check('pptx - 한글 본문 유지', allSlides.includes('결산 일정') && allSlides.includes('재고 실사표'));
  check('pptx - 그림 설명 중복 없음',
    (allSlides.match(/ERP 전표입력 화면/g) || []).length === 1,
    `${(allSlides.match(/ERP 전표입력 화면/g) || []).length}회 등장`);

  // 도형이 슬라이드 밖으로 나가지 않는지 (13.333 x 7.5인치 = 12192000 x 6858000 EMU)
  const overflow = [];
  slideNames.forEach((n) => {
    const body = text(n);
    for (const m of body.matchAll(/<a:off x="(-?\d+)" y="(-?\d+)"\/><a:ext cx="(\d+)" cy="(\d+)"\/>/g)) {
      const [x, y, cx, cy] = m.slice(1).map(Number);
      if (cx === 0 && cy === 0) continue;                       // 그룹 기준점
      if (x < 0 || y < 0 || x + cx > 12192000 || y + cy > 6858000) overflow.push(`${n} ${x},${y} ${cx}x${cy}`);
    }
  });
  check('pptx - 모든 개체가 슬라이드 안에 배치됨', overflow.length === 0, overflow.slice(0, 2).join(' / '));
}

// ---------------------------------------------------------------- 마무리
await ctx.close();
server.close();

console.log(`\n결과: ${fail.length ? 'FAIL(' + fail.length + ') -> ' + fail.join(', ') : '전체 통과'}`);
process.exit(fail.length ? 1 : 0);

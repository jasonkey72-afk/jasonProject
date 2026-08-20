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

const HERE = path.dirname(fileURLToPath(import.meta.url));
const SITE = path.join(HERE, 'fixtures');
const OUT = path.join(HERE, 'out');
const EXT = path.dirname(HERE);

const server = http.createServer((req, res) => {
  const file = path.join(SITE, decodeURIComponent(req.url.split('?')[0]).replace(/^\/+/, '') || 'board.html');
  fs.readFile(file, (err, data) => {
    if (err) { res.writeHead(404); res.end('nope'); return; }
    res.writeHead(200, { 'Content-Type': 'text/html; charset=utf-8' });
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

await call('SET_SETTINGS', { patch: { mode: 'batch', autoScroll: false, autoCapture: false, format: 'md' } });

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

// ---------------------------------------------------------------- 마무리
await ctx.close();
server.close();

console.log(`\n결과: ${fail.length ? 'FAIL(' + fail.length + ') -> ' + fail.join(', ') : '전체 통과'}`);
process.exit(fail.length ? 1 : 0);

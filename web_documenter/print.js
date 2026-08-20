/*
 * print.js - 수집한 문서를 인쇄용으로 펼쳐 놓고 인쇄 대화상자를 연다.
 *
 * 확장에서 PDF 를 직접 만들려면 한글 글꼴 전체를 넣어야 해 파일이 매우 커지고
 * 표·그림 배치도 브라우저와 달라진다. 브라우저의 인쇄 기능을 쓰면 화면에 보이는
 * 그대로, 한글도 깨지지 않고 PDF 로 저장된다.
 */
'use strict';

(async () => {
  const key = new URLSearchParams(location.search).get('k');
  const bar = document.getElementById('wd-bar');
  const content = document.getElementById('wd-content');

  const fail = (message) => {
    content.textContent = message;
    content.style.cssText = 'font-family:system-ui,sans-serif;color:#c0392b;padding:24px';
  };

  if (!key) return fail('인쇄할 문서를 찾지 못했습니다. 확장 팝업에서 다시 저장해 주세요.');

  const stored = (await chrome.storage.local.get(key))[key];
  if (!stored) return fail('인쇄할 문서가 만료되었습니다. 확장 팝업에서 다시 저장해 주세요.');
  await chrome.storage.local.remove(key); // 한 번 열면 지운다 (저장 공간 절약)

  // 인쇄 대화상자의 기본 파일 이름으로 쓰인다.
  document.title = stored.title;
  document.getElementById('wd-doc-style').textContent = stored.style;
  content.innerHTML = stored.body;

  document.getElementById('wd-print').addEventListener('click', () => window.print());

  // 그림이 다 그려진 뒤에 인쇄해야 PDF 에 빠짐없이 들어간다.
  const images = Array.from(document.images);
  await Promise.all(images.map((img) => (img.complete ? Promise.resolve() : img.decode().catch(() => {}))));
  await new Promise((r) => setTimeout(r, 150));

  // 여러 건을 건별 PDF 로 저장할 때는 뒤쪽 탭이 화면에 보이는 순간에 인쇄 창을 띄운다.
  // (탭마다 인쇄 창이 한꺼번에 뜨면 어느 문서인지 알 수 없다)
  if (stored.autoPrint) {
    window.print();
  } else {
    bar.querySelector('.wd-hint').textContent = '이 탭이 화면에 보이면 인쇄 창이 열립니다.';
    document.addEventListener('visibilitychange', function once() {
      if (document.visibilityState !== 'visible') return;
      document.removeEventListener('visibilitychange', once);
      setTimeout(() => window.print(), 300);
    });
  }
})();

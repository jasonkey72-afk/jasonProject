/*
 * content.js - 페이지 안에서 실행되어 "본문"을 찾아내고 문서 형태로 변환한다.
 *
 * 스크롤로 눈에 보이는 부분만 긁는 방식이 아니라, 페이지의 DOM 전체를 대상으로
 * 본문 영역을 판정한 뒤 한 번에 변환하므로 스크롤바를 움직일 필요가 없다.
 * (무한 스크롤/더보기 방식으로 나중에 로딩되는 페이지를 위해 자동 스크롤 옵션 제공)
 */
(() => {
  'use strict';

  if (window.__webDocumenterLoaded) return;
  window.__webDocumenterLoaded = true;

  const MAX_SCROLL_MS = 15000;   // 자동 스크롤 최대 시간
  const HIDDEN_MARK = 'data-wd-hidden';
  const IMG_SRC = 'data-wd-src';
  const IMG_DROP = 'data-wd-drop';

  chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
    if (!msg || typeof msg.type !== 'string') return;

    if (msg.type === 'WD_PING') {
      sendResponse({ ok: true });
      return;
    }
    if (msg.type === 'WD_CAPTURE') {
      capture(msg.options || {})
        .then((doc) => sendResponse({ ok: true, doc }))
        .catch((err) => sendResponse({ ok: false, error: String((err && err.message) || err) }));
      return true; // 비동기 응답
    }
    if (msg.type === 'WD_TOAST') {
      showToast(msg.text, msg.tone);
      sendResponse({ ok: true });
    }
  });

  /* ------------------------------------------------------------------ */
  /* 수집 진입점                                                         */
  /* ------------------------------------------------------------------ */

  async function capture(options) {
    if (options.autoScroll) await scrollThroughPage();

    const title = pickTitle();
    const root = buildCleanRoot();
    dropDuplicateHeading(root, title);
    const markdown = normalizeBlank(blocksToMarkdown(root));
    if (!markdown.trim()) throw new Error('본문으로 인식할 내용을 찾지 못했습니다.');

    const html = root.innerHTML;
    const text = markdownToText(markdown);

    return {
      title,
      url: location.href,
      site: location.hostname,
      capturedAt: new Date().toISOString(),
      markdown,
      html,
      text,
      charCount: text.length,
      images: collectImages(root)   // 문서에 넣을 그림 주소 (중복 제거)
    };
  }

  // 문서 머리말에 제목을 따로 붙이므로, 본문 첫 줄의 같은 제목은 중복이라 제거한다.
  function dropDuplicateHeading(root, title) {
    const h = root.querySelector('h1,h2,h3,h4');
    if (!h) return;
    const norm = (t) => (t || '').replace(/\s+/g, '').trim();
    if (norm(h.textContent) && norm(h.textContent) === norm(title)) h.remove();
  }

  function pickTitle() {
    const og = document.querySelector('meta[property="og:title"]');
    const cands = [
      og && og.getAttribute('content'),
      document.querySelector('h1') && document.querySelector('h1').innerText,
      document.title
    ];
    for (const c of cands) {
      const t = (c || '').replace(/\s+/g, ' ').trim();
      if (t) return t;
    }
    return location.hostname;
  }

  /* ------------------------------------------------------------------ */
  /* 지연 로딩 대응: 페이지 끝까지 훑고 원래 위치로 복귀                  */
  /* ------------------------------------------------------------------ */

  async function scrollThroughPage() {
    const startY = window.scrollY;
    const started = Date.now();
    let lastHeight = -1;
    let stable = 0;

    while (Date.now() - started < MAX_SCROLL_MS) {
      window.scrollTo(0, document.documentElement.scrollHeight);
      await sleep(300);
      const h = document.documentElement.scrollHeight;
      if (h === lastHeight) {
        if (++stable >= 2) break;
      } else {
        stable = 0;
        lastHeight = h;
      }
    }
    window.scrollTo(0, startY);
    await sleep(120);
  }

  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

  /* ------------------------------------------------------------------ */
  /* 본문 영역 추출                                                      */
  /* ------------------------------------------------------------------ */

  // 화면에 렌더링되지 않는(숨김 탭, 팝업 등) 요소를 원본에서 표시해 두고 복제한다.
  function markHiddenNodes() {
    const all = document.body.querySelectorAll('*');
    const limit = Math.min(all.length, 12000);
    for (let i = 0; i < limit; i++) {
      const el = all[i];
      if (!el.textContent || !el.textContent.trim()) continue;
      if (el.getClientRects().length === 0) el.setAttribute(HIDDEN_MARK, '1');
    }
  }

  function unmarkHiddenNodes() {
    document.body.querySelectorAll('[' + HIDDEN_MARK + ']').forEach((el) => el.removeAttribute(HIDDEN_MARK));
  }

  // 본문에 넣을 만한 그림인지 원본 DOM 에서 판단해 표시해 둔다.
  // (복제본에서는 naturalWidth 를 알 수 없고, lazy-loading 으로 src 가 비어 있을 수 있다)
  const MIN_IMAGE_PX = 40;

  function markImages() {
    for (const img of Array.from(document.images)) {
      const w = img.naturalWidth || 0;
      const h = img.naturalHeight || 0;
      // 아이콘·버튼·추적용 1x1 픽셀은 문서에 넣지 않는다.
      if ((w && h && w < MIN_IMAGE_PX && h < MIN_IMAGE_PX) || (w === 1 && h === 1)) {
        img.setAttribute(IMG_DROP, '1');
        continue;
      }
      const src = img.currentSrc || img.src; // srcset·lazy-loading 이 적용된 실제 주소
      if (src) img.setAttribute(IMG_SRC, src);
    }
  }

  function unmarkImages() {
    document.querySelectorAll('[' + IMG_SRC + '],[' + IMG_DROP + ']').forEach((el) => {
      el.removeAttribute(IMG_SRC);
      el.removeAttribute(IMG_DROP);
    });
  }

  function collectImages(root) {
    const seen = new Set();
    root.querySelectorAll('img[src]').forEach((img) => {
      const src = img.getAttribute('src');
      if (src && /^https?:/i.test(src)) seen.add(src);
    });
    return Array.from(seen);
  }

  const DROP_TAGS = [
    'script', 'style', 'noscript', 'iframe', 'svg', 'canvas', 'template',
    'link', 'meta', 'button', 'input', 'select', 'textarea', 'video',
    'audio', 'object', 'embed', 'map', 'dialog'
  ].join(',');

  const DROP_ROLES = 'nav,[role="navigation"],[role="banner"],[role="complementary"],[role="search"],[aria-hidden="true"]';

  // 클래스/ID에 흔히 쓰이는 부속 영역 이름
  const JUNK_RE = new RegExp(
    '(^|[\\s_-])(' +
      'ad|ads|advert|banner|popup|layer-?pop|modal|cookie|gnb|lnb|snb|nav|navi|navigation|' +
      'breadcrumb|sidebar|side-?bar|aside|footer|foot|header(?!ing)|comment|reply|share|sns|' +
      'related|recommend|toolbar|pagination|paging|skip|floating|sticky|widget|utility|util|' +
      'quick|top-?btn|go-?top|copyright|login|search-?box|tag-?list|social' +
    ')([\\s_-]|$)',
    'i'
  );

  // 흔한 본문 컨테이너 (국내 게시판/CMS 포함)
  const PREFERRED = [
    'article', '[role="main"]', 'main',
    '.article-body', '.article_body', '#articleBody', '#article-body', '#article_body',
    '.post-content', '.entry-content', '.post_content', '.board-view', '.view-content',
    '.board_view', '#bo_v_con', '.xe-content', '.se-main-container', '#dic_area',
    '#newsct_article', '.news_end', '.tt_article_useless_p_margin', '.wiki-content',
    '.markdown-body', '.doc-content', '#content', '.content', '#contents', '.contents',
    '#container .view', '.detail-content', '.cont_view', '#viewContent'
  ];

  function buildCleanRoot() {
    markHiddenNodes();
    markImages();
    const clone = document.body.cloneNode(true);
    unmarkHiddenNodes();
    unmarkImages();

    stripNoise(clone);
    const best = pickBestBlock(clone);
    cleanAttributes(best);
    return best;
  }

  function stripNoise(clone) {
    clone.querySelectorAll(DROP_TAGS).forEach(remove);
    clone.querySelectorAll('[' + HIDDEN_MARK + ']').forEach(remove);
    clone.querySelectorAll('img[' + IMG_DROP + ']').forEach(remove);
    clone.querySelectorAll(DROP_ROLES).forEach(remove);

    const total = textLen(clone) || 1;
    clone.querySelectorAll('div,section,ul,ol,aside,header,footer,span,p').forEach((el) => {
      if (!clone.contains(el)) return; // 상위 요소가 이미 제거된 경우
      const key = (el.className && typeof el.className === 'string' ? el.className : '') + ' ' + (el.id || '');
      if (!key.trim() || !JUNK_RE.test(key.replace(/[_-]/g, ' '))) return;
      // 본문 자체가 이런 이름을 쓰는 경우가 있으므로, 페이지 텍스트의 큰 비중을 차지하면 남긴다.
      if (textLen(el) / total > 0.4) return;
      remove(el);
    });
  }

  function remove(el) {
    if (el && el.parentNode) el.parentNode.removeChild(el);
  }

  function textLen(el) {
    return (el.textContent || '').replace(/\s+/g, ' ').trim().length;
  }

  function linkDensity(el) {
    const total = textLen(el);
    if (!total) return 1;
    let linked = 0;
    el.querySelectorAll('a').forEach((a) => { linked += textLen(a); });
    return Math.min(1, linked / total);
  }

  function pickBestBlock(clone) {
    const total = textLen(clone);

    // 1) 알려진 본문 컨테이너 우선
    for (const sel of PREFERRED) {
      let el;
      try { el = clone.querySelector(sel); } catch (_) { continue; }
      if (!el) continue;
      const len = textLen(el);
      if (len >= 200 && len >= total * 0.25 && linkDensity(el) < 0.5) return el;
    }

    // 2) 점수 기반 판정 (문단이 많이 모여 있는 블록을 본문으로 본다)
    const scores = new Map();
    const add = (el, v) => {
      if (!el || el.nodeType !== 1) return;
      scores.set(el, (scores.get(el) || 0) + v);
    };

    clone.querySelectorAll('p,pre,blockquote,li,td,h2,h3,h4,dd').forEach((el) => {
      const t = (el.textContent || '').replace(/\s+/g, ' ').trim();
      if (t.length < 25) return;
      const base = 1 + Math.min(3, (t.match(/[,，.。]/g) || []).length) + Math.min(3, Math.floor(t.length / 100));
      add(el.parentElement, base);
      add(el.parentElement && el.parentElement.parentElement, base / 2);
      add(el.parentElement && el.parentElement.parentElement && el.parentElement.parentElement.parentElement, base / 3);
    });

    let best = null;
    let bestScore = 0;
    scores.forEach((score, el) => {
      const adjusted = score * (1 - linkDensity(el));
      if (adjusted > bestScore) {
        bestScore = adjusted;
        best = el;
      }
    });

    // 3) 본문이라기엔 너무 짧으면 페이지 전체를 사용
    if (!best || textLen(best) < 250 || textLen(best) < total * 0.1) return clone;
    return best;
  }

  const KEEP_ATTRS = new Set(['href', 'src', 'alt', 'colspan', 'rowspan', 'title']);

  function cleanAttributes(root) {
    const walk = (el) => {
      if (el.nodeType !== 1) return;
      if (el.tagName === 'IMG') {
        const real = el.getAttribute(IMG_SRC);
        if (real) el.setAttribute('src', real);
      }
      for (const attr of Array.from(el.attributes || [])) {
        if (!KEEP_ATTRS.has(attr.name)) {
          el.removeAttribute(attr.name);
          continue;
        }
        if (attr.name === 'href' || attr.name === 'src') {
          const abs = toAbsolute(attr.value);
          if (abs) el.setAttribute(attr.name, abs);
          else el.removeAttribute(attr.name);
        }
      }
      Array.from(el.children).forEach(walk);
    };
    walk(root);
  }

  function toAbsolute(url) {
    if (!url) return '';
    const v = url.trim();
    if (!v || /^(javascript|data|about|#)/i.test(v)) return '';
    try { return new URL(v, location.href).href; } catch (_) { return ''; }
  }

  /* ------------------------------------------------------------------ */
  /* DOM -> Markdown                                                     */
  /* ------------------------------------------------------------------ */

  const HEADINGS = { H1: '#', H2: '##', H3: '###', H4: '####', H5: '#####', H6: '######' };

  function blocksToMarkdown(root) {
    const out = [];
    walkBlock(root, { indent: '', list: null, index: 0 }, out);
    return out.join('\n');
  }

  function walkBlock(node, ctx, out) {
    for (const child of Array.from(node.childNodes)) {
      if (child.nodeType === 3) {
        const t = child.nodeValue.replace(/\s+/g, ' ').trim();
        if (t) push(out, ctx.indent + escapeMd(t));
        continue;
      }
      if (child.nodeType !== 1) continue;

      const tag = child.tagName;

      if (HEADINGS[tag]) {
        const t = inline(child).trim();
        if (t) push(out, '', ctx.indent + HEADINGS[tag] + ' ' + t.replace(/\n+/g, ' '), '');
        continue;
      }

      switch (tag) {
        case 'HR':
          push(out, '', ctx.indent + '---', '');
          break;

        case 'PRE': {
          const code = (child.textContent || '').replace(/\s+$/, '');
          if (code.trim()) push(out, '', ctx.indent + '```', ...code.split('\n').map((l) => ctx.indent + l), ctx.indent + '```', '');
          break;
        }

        case 'BLOCKQUOTE': {
          const inner = [];
          walkBlock(child, { ...ctx, indent: '' }, inner);
          const body = normalizeBlank(inner.join('\n')).split('\n');
          if (body.join('').trim()) push(out, '', ...body.map((l) => ctx.indent + '> ' + l), '');
          break;
        }

        case 'UL':
        case 'OL': {
          const items = Array.from(child.children).filter((c) => c.tagName === 'LI');
          if (!items.length) { walkBlock(child, ctx, out); break; }
          push(out, '');
          items.forEach((li, i) => {
            const marker = tag === 'OL' ? `${i + 1}.` : '-';
            renderListItem(li, ctx, marker, out);
          });
          push(out, '');
          break;
        }

        case 'DL': {
          push(out, '');
          Array.from(child.children).forEach((c) => {
            const t = inline(c).trim();
            if (!t) return;
            push(out, ctx.indent + (c.tagName === 'DT' ? '**' + t + '**' : '- ' + t));
          });
          push(out, '');
          break;
        }

        case 'TABLE':
          push(out, '', ...renderTable(child, ctx.indent), '');
          break;

        case 'FIGURE':
        case 'FIGCAPTION':
        case 'DIV':
        case 'SECTION':
        case 'ARTICLE':
        case 'MAIN':
        case 'HEADER':
        case 'FOOTER':
        case 'ASIDE':
        case 'FORM':
        case 'ADDRESS':
        case 'DETAILS':
        case 'SUMMARY':
          if (hasBlockChild(child)) {
            walkBlock(child, ctx, out);
          } else {
            const t = inline(child).trim();
            if (t) push(out, '', ...t.split('\n').map((l) => ctx.indent + l), '');
          }
          break;

        case 'P': {
          const t = inline(child).trim();
          if (t) push(out, '', ...t.split('\n').map((l) => ctx.indent + l), '');
          break;
        }

        case 'LI':
          renderListItem(child, ctx, '-', out);
          break;

        case 'BR':
          break;

        default: {
          if (hasBlockChild(child)) {
            walkBlock(child, ctx, out);
          } else {
            const t = inline(child).trim();
            if (t) push(out, ctx.indent + t);
          }
        }
      }
    }
  }

  function renderListItem(li, ctx, marker, out) {
    const childCtx = { ...ctx, indent: ctx.indent + '  ' };
    const head = [];
    const nested = [];

    for (const node of Array.from(li.childNodes)) {
      if (node.nodeType === 1 && (node.tagName === 'UL' || node.tagName === 'OL')) {
        nested.push(node);
      } else {
        head.push(node);
      }
    }

    const text = head.map((n) => inlineNode(n)).join('').replace(/\s+/g, ' ').trim();
    if (text) push(out, ctx.indent + marker + ' ' + text);

    nested.forEach((list) => {
      const items = Array.from(list.children).filter((c) => c.tagName === 'LI');
      items.forEach((sub, i) => {
        renderListItem(sub, childCtx, list.tagName === 'OL' ? `${i + 1}.` : '-', out);
      });
    });
  }

  function renderTable(table, indent) {
    const rows = Array.from(table.querySelectorAll('tr'))
      .map((tr) => Array.from(tr.children)
        .filter((c) => c.tagName === 'TD' || c.tagName === 'TH')
        .map((c) => inline(c).replace(/\s*\n\s*/g, ' ').replace(/\|/g, '\\|').trim()))
      .filter((cells) => cells.length && cells.some((c) => c));

    if (!rows.length) return [];

    const width = Math.max(...rows.map((r) => r.length));
    const pad = (r) => { while (r.length < width) r.push(''); return r; };
    const line = (cells) => indent + '| ' + pad(cells).join(' | ') + ' |';

    const hasHead = table.querySelector('th') !== null;
    const header = hasHead ? rows[0] : new Array(width).fill('');
    const body = hasHead ? rows.slice(1) : rows;

    return [
      line(header.slice()),
      indent + '|' + new Array(width).fill(' --- ').join('|') + '|',
      ...body.map((r) => line(r.slice()))
    ];
  }

  function hasBlockChild(el) {
    return el.querySelector('p,div,section,article,ul,ol,table,pre,blockquote,h1,h2,h3,h4,h5,h6,li,figure,dl,form,main,header,footer,aside') !== null;
  }

  /* ---- 인라인 변환 ---- */

  function inline(el) {
    return Array.from(el.childNodes).map(inlineNode).join('');
  }

  function inlineNode(node) {
    if (node.nodeType === 3) return escapeMd(node.nodeValue.replace(/\s+/g, ' '));
    if (node.nodeType !== 1) return '';

    const tag = node.tagName;
    if (tag === 'BR') return '\n';
    if (tag === 'IMG') {
      const src = node.getAttribute('src');
      const alt = (node.getAttribute('alt') || '이미지').replace(/[\[\]]/g, '');
      return src ? `![${alt}](${src})` : '';
    }
    if (tag === 'HR') return '\n';

    const inner = inline(node);
    const trimmed = inner.trim();
    if (!trimmed) return inner;

    switch (tag) {
      case 'STRONG':
      case 'B':
      case 'TH':
        return tag === 'TH' ? inner : `**${trimmed}**`;
      case 'EM':
      case 'I':
        return `*${trimmed}*`;
      case 'DEL':
      case 'S':
      case 'STRIKE':
        return `~~${trimmed}~~`;
      case 'CODE':
      case 'KBD':
      case 'SAMP':
        return '`' + trimmed.replace(/`/g, '') + '`';
      case 'A': {
        const href = node.getAttribute('href');
        return href ? `[${trimmed}](${href})` : inner;
      }
      default:
        return inner;
    }
  }

  function escapeMd(t) {
    return t.replace(/([*_`])/g, '\\$1');
  }

  function push(out, ...lines) {
    lines.forEach((l) => out.push(l));
  }

  function normalizeBlank(md) {
    return md
      .split('\n')
      .map((l) => l.replace(/\s+$/, ''))
      .join('\n')
      .replace(/\n{3,}/g, '\n\n')
      .trim();
  }

  // 텍스트(.txt) 저장용: 마크다운 기호를 걷어내고 표는 탭으로 구분한다.
  function markdownToText(md) {
    const out = [];
    let inCode = false;

    for (const raw of md.split('\n')) {
      if (/^\s*```/.test(raw)) { inCode = !inCode; continue; }
      if (inCode) { out.push(raw); continue; }

      let line = raw;
      if (/^\s*\|/.test(line)) {
        if (/^\s*\|[\s|:-]+$/.test(line)) continue; // 표 구분선
        line = line.replace(/^\s*\|/, '').replace(/\|\s*$/, '')
          .split('|').map((c) => c.trim().replace(/\\\|/g, '|')).join('\t');
      }
      if (/^\s*---+\s*$/.test(line)) { out.push(''); continue; }

      line = line
        .replace(/!\[([^\]]*)\]\([^)]*\)/g, '[$1]')
        .replace(/\[([^\]]*)\]\([^)]*\)/g, '$1')
        .replace(/^\s*#{1,6}\s+/, '')
        .replace(/^\s*>\s?/, '')
        .replace(/\*\*([^*]+)\*\*/g, '$1')
        .replace(/(^|[^\\])\*([^*\n]+)\*/g, '$1$2')
        .replace(/~~([^~]+)~~/g, '$1')
        .replace(/`([^`]+)`/g, '$1')
        .replace(/\\([*_`])/g, '$1');

      out.push(line);
    }

    return out.join('\n').replace(/\n{3,}/g, '\n\n').trim();
  }

  /* ------------------------------------------------------------------ */
  /* 화면 우측 하단 알림                                                  */
  /* ------------------------------------------------------------------ */

  function showToast(text, tone) {
    const id = '__wd_toast';
    document.getElementById(id) && document.getElementById(id).remove();
    const box = document.createElement('div');
    box.id = id;
    box.textContent = text;
    box.style.cssText = [
      'position:fixed', 'right:16px', 'bottom:16px', 'z-index:2147483647',
      'padding:10px 14px', 'border-radius:8px', 'font-size:13px',
      'font-family:"맑은 고딕","Malgun Gothic",system-ui,sans-serif',
      'color:#fff', 'box-shadow:0 4px 16px rgba(0,0,0,.25)', 'pointer-events:none',
      'background:' + (tone === 'error' ? '#c0392b' : '#2d6cdf')
    ].join(';');
    document.documentElement.appendChild(box);
    setTimeout(() => box.remove(), 2200);
  }
})();

/**
 * 解析逻辑单元测试（Node 可运行）
 * 用法：node test-parse.js
 */

function coerceJson(obj) {
  if (typeof obj !== 'string') return obj;
  const s = obj.trim();
  if (!s || (s[0] !== '{' && s[0] !== '[')) return obj;
  try { return coerceJson(JSON.parse(s)); } catch { return obj; }
}

function deepCoerce(obj) {
  if (Array.isArray(obj)) return obj.map(deepCoerce);
  if (obj && typeof obj === 'object') {
    const out = {};
    for (const [k, v] of Object.entries(obj)) out[k] = deepCoerce(v);
    return out;
  }
  return coerceJson(obj);
}

function extractNextData(html) {
  const m = html.match(/<script id="__NEXT_DATA__"[^>]*>([\s\S]*?)<\/script>/i);
  if (!m) throw new Error('未找到 __NEXT_DATA__');
  return JSON.parse(m[1]);
}

function extractMessages(nextData) {
  const node = nextData?.props?.pageProps?.data;
  const ci = node.conversation_info || {};
  const meta = { conversationId: ci.conversationId, status: ci.status };
  let data = ci.data || node;
  data = deepCoerce(data);
  let rawMsgs = null;
  if (data && typeof data === 'object') {
    if (data.extra) rawMsgs = data.extra;
    else if (data.dataObj) {
      const dobj = deepCoerce(data.dataObj);
      if (dobj && typeof dobj === 'object') {
        rawMsgs = dobj.mergedQuestion;
        meta.hasThinking = dobj.hasThinking;
      }
    }
  }
  rawMsgs = deepCoerce(rawMsgs);
  if (!Array.isArray(rawMsgs)) rawMsgs = rawMsgs ? [rawMsgs] : [];
  return { rawMsgs, meta };
}

const TEXT_FIELDS = ['content', 'text', 'answer', 'thinkText', 'reasoningContent'];
const SKIP_SPEECH = new Set(['[视频号消息]', '[图片]', '[视频]', '[文件]', '[链接]', '[语音]']);

function parseMessage(msg) {
  if (!msg || typeof msg !== 'object') return null;
  const speaker = msg.speaker || msg.role || 'unknown';
  const parts = [];
  const media = [];
  const speechesV2 = msg.speechesV2;
  if (Array.isArray(speechesV2)) {
    for (const s of speechesV2) {
      const c = s && typeof s === 'object' ? s.content : null;
      if (Array.isArray(c)) {
        for (const it of c) {
          if (it && typeof it === 'object') {
            const txt = TEXT_FIELDS.map(f => it[f]).filter(Boolean).join(' ').trim();
            if (txt) parts.push(txt);
            if (it.coverUrl || it.author || it.title) {
              media.push({ title: it.title, author: it.author, coverUrl: it.coverUrl });
            }
          } else if (typeof it === 'string') parts.push(it);
        }
      } else if (typeof c === 'string') parts.push(c);
    }
  }
  if (!parts.length) {
    if (typeof msg.content === 'string') parts.push(msg.content);
    const sp = msg.speech;
    if (typeof sp === 'string' && !SKIP_SPEECH.has(sp)) parts.push(sp);
  }
  return { speaker, text: parts.filter(Boolean).join('\n').trim(), media };
}

function parseShareHtml(html) {
  const nextData = extractNextData(html);
  const pageData = nextData?.props?.pageProps?.data;
  if (pageData && typeof pageData === 'object' && pageData.err_code) {
    const hint = pageData.err_code === 'notInWX'
      ? '该分享页返回 notInWX：内容需在微信客户端内打开后才能获取。请按「如何获取 HTML 源码？」步骤，在微信内打开并复制完整页面源码。'
      : `分享页返回错误码 "${pageData.err_code}"，无法解析对话内容。`;
    throw new Error(hint);
  }
  const { rawMsgs, meta } = extractMessages(nextData);
  const messages = rawMsgs.map(parseMessage).filter(Boolean);
  if (!messages.length) {
    throw new Error('未解析出任何消息。请确认粘贴的是「分享页完整 HTML 源码」（含 __NEXT_DATA__ 对话数据），而非微信外抓取的拦截页。');
  }
  return { meta, messages, _raw: nextData };
}

function assert(cond, msg) {
  if (!cond) throw new Error('ASSERT FAIL: ' + msg);
}

// ---- 构造测试 HTML ----
const nextData = {
  props: {
    pageProps: {
      data: {
        conversation_info: {
          conversationId: 'demo-123',
          status: 1,
          data: JSON.stringify({
            extra: [
              {
                speaker: 'human',
                speechesV2: [{ content: [{ text: '帮我总结 AI 编程工具趋势' }] }]
              },
              {
                speaker: 'ai',
                speechesV2: [{
                  content: [{
                    text: '当前 AI 编程工具正从 Copilot 向 Agent 演进',
                    coverUrl: 'https://example.com/cover.jpg',
                    author: '示例号'
                  }]
                }]
              }
            ]
          })
        }
      }
    }
  }
};

const sampleHtml = `<!doctype html>
<html><head></head><body>
<script id="__NEXT_DATA__" type="application/json">${JSON.stringify(nextData)}</script>
</body></html>`;

const conv = parseShareHtml(sampleHtml);
assert(conv.meta.conversationId === 'demo-123', 'conversationId 解析错误');
assert(conv.meta.status === 1, 'status 解析错误');
assert(conv.messages.length === 2, '消息数量应为 2');
assert(conv.messages[0].speaker === 'human', '第一条说话人应为 human');
assert(conv.messages[0].text === '帮我总结 AI 编程工具趋势', '第一条文本错误');
assert(conv.messages[1].speaker === 'ai', '第二条说话人应为 ai');
assert(conv.messages[1].text === '当前 AI 编程工具正从 Copilot 向 Agent 演进', '第二条文本错误');
assert(conv.messages[1].media.length === 1, '第二条应含 1 个媒体');
assert(conv.messages[1].media[0].author === '示例号', '媒体作者错误');

// ---- notInWX 拦截样本（微信外抓取的真实壳，来自 yb.tencent.com/wx/ct/YFqCyYcybNOfQA）----
const blockedNextData = {
  props: { pageProps: { data: { err_code: 'notInWX', err_msg: '' } } }
};
const blockedHtml = `<!doctype html><html><body>
<script id="__NEXT_DATA__" type="application/json">${JSON.stringify(blockedNextData)}</script>
</body></html>`;
let blockedThrew = false;
try { parseShareHtml(blockedHtml); }
catch (e) { blockedThrew = /notInWX/.test(e.message); }
assert(blockedThrew, 'notInWX 拦截样本应抛出友好错误');

console.log('✅ 所有测试通过');
console.log(`   消息数: ${conv.messages.length}`);
console.log(`   Meta: ${JSON.stringify(conv.meta)}`);

// ---- 端到端入口：node test-parse.js <样本html路径> ----
if (process.argv[2]) {
  const fs = require('fs');
  const html = fs.readFileSync(process.argv[2], 'utf8');
  try {
    const c = parseShareHtml(html);
    console.log(`\n[E2E] 解析成功 → 消息数: ${c.messages.length}, meta: ${JSON.stringify(c.meta)}`);
  } catch (e) {
    console.log(`\n[E2E] 解析拦截 → ${e.message}`);
  }
  process.exit(0);
}

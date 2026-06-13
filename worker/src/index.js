// 주식 뉴스 텔레그램 봇 — Cloudflare Worker
//
// fetch    : 텔레그램 웹훅 → 명령 즉시 처리
// scheduled: 10분마다 → 브리핑(설정 시간) + 속보 체크(설정 주기)
//
// 필요한 secrets: TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, WEBHOOK_SECRET
// KV 키: settings(사용자 설정), state(브리핑 날짜·속보 시각), seen(보낸 기사 기록)

const MIN_PERIOD = 10; // 크론 주기(분) — 이보다 짧은 속보 주기는 불가능
const SEEN_TTL_MS = 7 * 24 * 3600 * 1000;
const MAX_MSG = 4000;
const WEEKDAYS = ["일", "월", "화", "수", "목", "금", "토"];

const DEFAULT_SETTINGS = {
  stocks: {
    "삼성전자": "삼성전자",
    "현대차": "현대차",
    "네이버": "네이버",
    "LG전자": "LG전자",
    "SK하이닉스": "SK하이닉스",
  },
  briefing_hour: 7,
  briefing_limit: 5,
  breaking_keywords: ["속보", "단독", "특징주", "공시", "급등", "급락", "어닝"],
  breaking_window_hours: 2,
  breaking_period_minutes: 10,
  paused: false,
  codes: {
    "삼성전자": "005930",
    "현대차": "005380",
    "네이버": "035420",
    "LG전자": "066570",
    "SK하이닉스": "000660",
  },
};

const HELP = `🤖 <b>사용 가능한 명령어</b>

/list — 현재 설정 보기
/news — 등록 종목 최신 뉴스 (지금 바로)
/news 종목명 — 특정 종목 최신 뉴스 (예: /news 카카오)
/price — 등록 종목 현재가 조회
/price 종목명 — 특정 종목 현재가 (예: /price 카카오)
/add 종목명 — 종목 추가 (예: /add 카카오)
/del 종목명 — 종목 삭제
/time 시간 — 브리핑 시간 변경, 24시 기준 (예: /time 8)
/period 분 — 속보 체크 주기 변경, 최소 ${MIN_PERIOD}분
/pause — 브리핑·속보 일시정지
/resume — 재개
/kw — 속보 키워드 보기
/kw_add 단어 — 속보 키워드 추가
/kw_del 단어 — 속보 키워드 삭제
/help — 이 도움말

⚡ 명령은 즉시 처리됩니다.`;

export default {
  async fetch(request, env, ctx) {
    const url = new URL(request.url);

    // 텔레그램 웹훅 (setWebhook의 secret_token으로 검증)
    if (request.method === "POST" && url.pathname === "/webhook") {
      if (request.headers.get("X-Telegram-Bot-Api-Secret-Token") !== env.WEBHOOK_SECRET) {
        return new Response("forbidden", { status: 403 });
      }
      const update = await request.json();
      ctx.waitUntil(handleUpdate(update, env).catch((e) => console.error("webhook:", e)));
      return new Response("ok");
    }

    // 수동 테스트용: /run?key=시크릿 → 한 사이클 강제 실행, /briefing?key=시크릿 → 브리핑 강제 전송
    if (url.searchParams.get("key") === env.WEBHOOK_SECRET) {
      if (url.pathname === "/run") {
        await runCycle(env);
        return new Response("cycle done");
      }
      if (url.pathname === "/briefing") {
        const s = await loadSettings(env);
        await sendMessage(env, await buildBriefing(s));
        return new Response("briefing sent");
      }
      if (url.pathname === "/news") {
        const s = await loadSettings(env);
        return new Response(await buildNewsReport(s, url.searchParams.get("q")), {
          headers: { "Content-Type": "text/plain; charset=utf-8" },
        });
      }
    }

    return new Response("stock-news-bot");
  },

  async scheduled(event, env, ctx) {
    ctx.waitUntil(runCycle(env).catch((e) => console.error("cron:", e)));
  },
};

// ---------- 공통 유틸 ----------

function esc(s) {
  return String(s).replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;");
}

function decodeEntities(s) {
  return s
    .replaceAll("&lt;", "<")
    .replaceAll("&gt;", ">")
    .replaceAll("&quot;", '"')
    .replaceAll("&#39;", "'")
    .replaceAll("&apos;", "'")
    .replaceAll("&amp;", "&");
}

function nowKST() {
  return new Date(Date.now() + 9 * 3600 * 1000); // KST = UTC+9 (서머타임 없음)
}

async function kvGetJSON(env, key, fallback) {
  const raw = await env.KV.get(key);
  return raw === null ? fallback : JSON.parse(raw);
}

async function loadSettings(env) {
  const s = await kvGetJSON(env, "settings", {});
  return { ...DEFAULT_SETTINGS, ...s };
}

async function tg(env, method, payload) {
  const r = await fetch(`https://api.telegram.org/bot${env.TELEGRAM_BOT_TOKEN}/${method}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!r.ok) console.error(`telegram ${method}:`, r.status, await r.text());
  return r;
}

async function sendMessage(env, text) {
  for (const chunk of splitMessage(text)) {
    await tg(env, "sendMessage", {
      chat_id: env.TELEGRAM_CHAT_ID,
      text: chunk,
      parse_mode: "HTML",
      disable_web_page_preview: true,
    });
  }
}

function splitMessage(text) {
  if (text.length <= MAX_MSG) return [text];
  const chunks = [];
  let current = "";
  for (const line of text.split("\n")) {
    if (current.length + line.length + 1 > MAX_MSG) {
      chunks.push(current.trimEnd());
      current = "";
    }
    current += line + "\n";
  }
  if (current.trim()) chunks.push(current.trimEnd());
  return chunks;
}

// ---------- 뉴스 (네이버 금융 종목 뉴스, 종목코드 기반) ----------
//
// 구글 뉴스 RSS는 ① 데이터센터 IP에서 요청이 몰리면 rate-limit으로 빈 응답을 주고
// ② 본문 매칭이라 무관한 종목이 섞이는 문제가 있어, 시세와 같은 네이버 서버를 쓴다.

async function fetchStockNews(code, limit) {
  const r = await fetch(
    `https://api.stock.naver.com/news/stock/${code}?pageSize=${Math.max(limit, 10)}&page=1`,
    { headers: NAVER_HEADERS },
  );
  if (!r.ok) throw new Error(`news ${r.status}`);
  const groups = await r.json();

  const items = [];
  for (const g of groups) {
    const it = (g.items || [])[0]; // 묶음의 대표 기사 1건
    if (!it) continue;
    items.push({
      id: it.id,
      title: decodeEntities((it.titleFull || it.title || "").trim()),
      source: it.officeName || "",
      link:
        it.mobileNewsUrl ||
        `https://n.news.naver.com/mnews/article/${it.officeId}/${it.articleId}`,
      datetime: it.datetime || "", // "YYYYMMDDHHMM" (KST)
    });
    if (items.length >= limit) break;
  }
  return items;
}

// 등록 종목의 종목코드를 얻는다. 없으면 조회해서 settings에 캐시한다.
async function resolveCode(s, name) {
  s.codes = s.codes || {};
  if (s.codes[name]) return s.codes[name];
  const code = await lookupCode(name).catch(() => null);
  if (code) s.codes[name] = code;
  return code;
}

// KST 기준 "YYYYMMDDHHMM" 문자열 (네이버 datetime과 비교용)
function kstStamp(date) {
  const k = new Date(date.getTime() + 9 * 3600 * 1000);
  const p = (n) => String(n).padStart(2, "0");
  return (
    `${k.getUTCFullYear()}${p(k.getUTCMonth() + 1)}${p(k.getUTCDate())}` +
    `${p(k.getUTCHours())}${p(k.getUTCMinutes())}`
  );
}

// ---------- 시세 (네이버 금융 공개 데이터) ----------

const NAVER_HEADERS = { "User-Agent": "Mozilla/5.0" };

async function lookupCode(name) {
  const r = await fetch(
    `https://ac.stock.naver.com/ac?q=${encodeURIComponent(name)}&target=stock`,
    { headers: NAVER_HEADERS },
  );
  if (!r.ok) return null;
  const items = ((await r.json()).items || []).filter((it) => it.nationCode === "KOR");
  const exact = items.find((it) => it.name === name);
  return (exact || items[0])?.code || null;
}

async function getPrice(code) {
  const r = await fetch(`https://m.stock.naver.com/api/stock/${code}/basic`, {
    headers: NAVER_HEADERS,
  });
  if (!r.ok) throw new Error(`price ${r.status}`);
  const d = await r.json();
  return {
    name: d.stockName || code,
    price: d.closePrice || "?",
    diff: d.compareToPreviousClosePrice || "",
    rate: d.fluctuationsRatio || "",
    direction: d.compareToPreviousPrice?.name || "",
    tradedAt: d.localTradedAt || "",
  };
}

function priceArrow(direction) {
  if (direction.includes("RISING") || direction.includes("UPPER")) return "🔺";
  if (direction.includes("FALLING") || direction.includes("LOWER")) return "🔻";
  return "➖";
}

async function priceLine(name, code) {
  try {
    const p = await getPrice(code);
    return {
      line: `${priceArrow(p.direction)} <b>${esc(p.name)}</b> ${p.price}원 (${p.diff}, ${p.rate}%)`,
      tradedAt: p.tradedAt,
    };
  } catch {
    return { line: `➖ ${esc(name)}: 시세 조회 실패`, tradedAt: "" };
  }
}

async function buildPriceReport(s, target) {
  if (target) {
    const code = await lookupCode(target).catch(() => null);
    if (!code) return { reply: `❌ '${esc(target)}' 종목을 찾지 못했습니다.`, changed: false };
    const { line } = await priceLine(target, code);
    return { reply: `💰 <b>현재가</b>\n${line}`, changed: false };
  }

  const lines = ["💰 <b>현재가</b>"];
  let tradedAt = "";
  let changed = false;
  s.codes = s.codes || {};
  for (const name of Object.keys(s.stocks)) {
    let code = s.codes[name];
    if (!code) {
      code = await lookupCode(name).catch(() => null);
      if (code) {
        s.codes[name] = code;
        changed = true;
      }
    }
    if (!code) {
      lines.push(`➖ ${esc(name)}: 종목코드를 찾지 못함`);
      continue;
    }
    const r = await priceLine(name, code);
    lines.push(r.line);
    if (!tradedAt) tradedAt = r.tradedAt;
  }
  if (tradedAt.length >= 16) {
    lines.push("", `🕐 ${tradedAt.slice(5, 10)} ${tradedAt.slice(11, 16)} 기준`);
  }
  return { reply: lines.join("\n"), changed };
}

// ---------- 명령 처리 ----------

function formatSettings(s) {
  const status = s.paused ? "⏸ 일시정지 중 (/resume 으로 재개)" : "▶️ 동작 중";
  const lines = [
    "📋 <b>현재 설정</b>",
    "",
    `상태: ${status}`,
    `⏰ 브리핑: 매일 ${s.briefing_hour}시`,
    `🔄 속보 체크 주기: ${s.breaking_period_minutes}분`,
    "",
    "📈 종목:",
  ];
  for (const name of Object.keys(s.stocks)) {
    lines.push(` • ${esc(name)}`);
  }
  lines.push("", `🚨 속보 키워드: ${esc(s.breaking_keywords.join(", "))}`);
  return lines.join("\n");
}

async function handleCommand(text, s) {
  const parts = text.split(/\s+/);
  const cmd = parts[0].toLowerCase().split("@")[0];
  const args = parts.slice(1);

  if (cmd === "/start" || cmd === "/help") return { reply: HELP, changed: false };

  if (cmd === "/list") return { reply: formatSettings(s), changed: false };

  if (cmd === "/news") {
    const reply = await buildNewsReport(s, args[0] || null);
    return { reply, changed: false };
  }

  if (cmd === "/price") return buildPriceReport(s, args[0] || null);

  if (cmd === "/add") {
    if (!args.length) return { reply: "사용법: /add 종목명 (예: /add 카카오)", changed: false };
    const name = args[0];
    const code = await lookupCode(name).catch(() => null);
    if (!code) {
      return { reply: `❌ '${esc(name)}' 종목을 찾지 못했습니다. 정확한 종목명을 입력해주세요.`, changed: false };
    }
    s.stocks[name] = name;
    s.codes = s.codes || {};
    s.codes[name] = code;
    return {
      reply: `✅ <b>${esc(name)}</b> 추가 완료 (총 ${Object.keys(s.stocks).length}종목)`,
      changed: true,
    };
  }

  if (cmd === "/del") {
    if (!args.length) return { reply: "사용법: /del 종목명", changed: false };
    const name = args[0];
    if (!(name in s.stocks)) {
      return {
        reply: `❌ '${esc(name)}' 종목이 없습니다.\n현재: ${esc(Object.keys(s.stocks).join(", "))}`,
        changed: false,
      };
    }
    delete s.stocks[name];
    if (s.codes) delete s.codes[name];
    return {
      reply: `🗑 <b>${esc(name)}</b> 삭제 완료 (총 ${Object.keys(s.stocks).length}종목)`,
      changed: true,
    };
  }

  if (cmd === "/time") {
    const h = Number(args[0]);
    if (!args.length || !Number.isInteger(h) || h < 0 || h > 23) {
      return { reply: "사용법: /time 시간 (0~23, 예: /time 8 → 매일 8시)", changed: false };
    }
    s.briefing_hour = h;
    return { reply: `⏰ 브리핑 시간을 매일 <b>${h}시</b>로 변경했습니다.`, changed: true };
  }

  if (cmd === "/period" || cmd === "/priod") {
    let m = Number(args[0]);
    if (!args.length || !Number.isInteger(m) || m < 1) {
      return { reply: `사용법: /period 분 (최소 ${MIN_PERIOD}분, 예: /period 30)`, changed: false };
    }
    let note = "";
    if (m < MIN_PERIOD) {
      m = MIN_PERIOD;
      note = `\n(최소 주기인 ${MIN_PERIOD}분으로 설정했습니다)`;
    }
    s.breaking_period_minutes = m;
    return { reply: `🔄 속보 체크 주기를 <b>${m}분</b>으로 변경했습니다.${note}`, changed: true };
  }

  if (cmd === "/pause") {
    if (s.paused) return { reply: "이미 일시정지 상태입니다. /resume 으로 재개할 수 있습니다.", changed: false };
    s.paused = true;
    return {
      reply: "⏸ 일시정지했습니다. 브리핑과 속보 알림이 중단됩니다.\n/resume 을 보내면 재개됩니다.",
      changed: true,
    };
  }

  if (cmd === "/resume") {
    if (!s.paused) return { reply: "이미 동작 중입니다.", changed: false };
    s.paused = false;
    return { reply: "▶️ 재개했습니다. 브리핑과 속보 알림이 다시 동작합니다.", changed: true };
  }

  if (cmd === "/kw") {
    return { reply: `🚨 속보 키워드: ${esc(s.breaking_keywords.join(", "))}`, changed: false };
  }

  if (cmd === "/kw_add") {
    if (!args.length) return { reply: "사용법: /kw_add 단어", changed: false };
    if (!s.breaking_keywords.includes(args[0])) s.breaking_keywords.push(args[0]);
    return { reply: `✅ 키워드 추가: ${esc(s.breaking_keywords.join(", "))}`, changed: true };
  }

  if (cmd === "/kw_del") {
    if (!args.length) return { reply: "사용법: /kw_del 단어", changed: false };
    const i = s.breaking_keywords.indexOf(args[0]);
    if (i < 0) return { reply: `❌ '${esc(args[0])}' 키워드가 없습니다.`, changed: false };
    s.breaking_keywords.splice(i, 1);
    return { reply: `🗑 키워드 삭제: ${esc(s.breaking_keywords.join(", "))}`, changed: true };
  }

  if (cmd.startsWith("/")) {
    return { reply: "알 수 없는 명령입니다. /help 를 입력해보세요.", changed: false };
  }

  return { reply: null, changed: false }; // 일반 메시지는 무시
}

async function handleUpdate(update, env) {
  const msg = update.message;
  if (!msg || String(msg.chat?.id) !== String(env.TELEGRAM_CHAT_ID)) return;
  const text = (msg.text || "").trim();
  if (!text) return;

  const s = await loadSettings(env);
  const { reply, changed } = await handleCommand(text, s);
  if (changed) await env.KV.put("settings", JSON.stringify(s));
  if (reply) await sendMessage(env, reply);
}

// ---------- 뉴스 (브리핑 / 온디맨드) ----------

// 종목코드로 뉴스 줄 목록을 만든다.
async function newsLinesForCode(code, limit) {
  let items;
  try {
    items = await fetchStockNews(code, limit);
  } catch (e) {
    return [`  (뉴스 조회 실패: ${esc(e.message)})`];
  }
  if (!items.length) return ["  최근 뉴스 없음"];
  return items.map((item, i) => {
    const suffix = item.source ? ` — ${esc(item.source)}` : "";
    return `${i + 1}. <a href="${item.link}">${esc(item.title)}</a>${suffix}`;
  });
}

// /news : 등록 종목(또는 지정 종목)의 최신 뉴스를 즉시 조회
async function buildNewsReport(s, target) {
  const stamp = nowKST().toISOString().slice(11, 16);

  if (target) {
    const code = await resolveCode(s, target);
    const lines = [`📰 <b>${esc(target)} 최신 뉴스</b> (${stamp} 기준)`, ""];
    if (!code) lines.push(`  '${esc(target)}' 종목을 찾지 못했습니다.`);
    else lines.push(...(await newsLinesForCode(code, 5)));
    return lines.join("\n");
  }

  const lines = [`📰 <b>최신 뉴스</b> (${stamp} 기준)`, ""];
  for (const name of Object.keys(s.stocks)) {
    lines.push(`🏢 <b>${esc(name)}</b>`);
    const code = await resolveCode(s, name);
    if (!code) lines.push("  종목코드를 찾지 못함");
    else lines.push(...(await newsLinesForCode(code, 3)));
    lines.push("");
  }
  return lines.join("\n").trim();
}

// ---------- 브리핑 ----------

async function buildBriefing(s) {
  const kst = nowKST();
  const date = kst.toISOString().slice(0, 10);
  const lines = ["📊 <b>주식 뉴스 브리핑</b>", `${date} (${WEEKDAYS[kst.getUTCDay()]})`, ""];

  for (const name of Object.keys(s.stocks)) {
    lines.push(`🏢 <b>${esc(name)}</b>`);
    const code = await resolveCode(s, name);
    if (!code) lines.push("  종목코드를 찾지 못함");
    else lines.push(...(await newsLinesForCode(code, s.briefing_limit)));
    lines.push("");
  }
  return lines.join("\n").trim();
}

// ---------- 속보 ----------

async function checkBreaking(env, s) {
  let seen = await kvGetJSON(env, "seen", null);
  const firstRun = seen === null;
  seen = seen || {};
  const now = Date.now();
  const cutoff = kstStamp(new Date(now - s.breaking_window_hours * 3600 * 1000));

  for (const name of Object.keys(s.stocks)) {
    const code = await resolveCode(s, name);
    if (!code) continue;
    let items;
    try {
      items = await fetchStockNews(code, 20);
    } catch (e) {
      console.error(`${name} 뉴스 조회 실패:`, e);
      continue;
    }
    for (const item of items) {
      if (item.id in seen) continue;
      seen[item.id] = now;
      if (firstRun) continue; // 최초 실행은 기록만 (과거 기사 폭주 방지)
      if (item.datetime && item.datetime < cutoff) continue; // 설정 시간창 밖
      if (s.breaking_keywords.length && !s.breaking_keywords.some((k) => item.title.includes(k))) {
        continue;
      }
      const suffix = item.source ? ` — ${esc(item.source)}` : "";
      await sendMessage(env, `🚨 <b>${esc(name)}</b> 속보\n<a href="${item.link}">${esc(item.title)}</a>${suffix}`);
    }
  }

  for (const [k, v] of Object.entries(seen)) {
    if (now - v > SEEN_TTL_MS) delete seen[k];
  }
  await env.KV.put("seen", JSON.stringify(seen));
}

// ---------- 메인 사이클 (크론) ----------

async function runCycle(env) {
  const s = await loadSettings(env);
  if (s.paused) {
    console.log("일시정지 상태");
    return;
  }

  const state = await kvGetJSON(env, "state", {});
  const kst = nowKST();
  const today = kst.toISOString().slice(0, 10);
  let changed = false;

  if (kst.getUTCHours() >= s.briefing_hour && state.last_briefing_date !== today) {
    await sendMessage(env, await buildBriefing(s));
    state.last_briefing_date = today;
    changed = true;
  }

  const periodMs = Math.max(s.breaking_period_minutes, MIN_PERIOD) * 60000;
  if (Date.now() - (state.last_breaking_ts || 0) >= periodMs - 60000) {
    await checkBreaking(env, s);
    state.last_breaking_ts = Date.now();
    changed = true;
  }

  if (changed) await env.KV.put("state", JSON.stringify(state));
}

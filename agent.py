#!/usr/bin/env python3
"""AI ops agent in Telegram.
Free NVIDIA model triages every message: quick status answers itself (0 cost).
Real tasks go to Claude Opus 5.5 via OpenRouter with a shell tool on this server.
Falls back to the free model for tasks if OpenRouter refuses (402) or the daily budget is spent."""
import threading, os, re, json, time, subprocess, urllib.request, urllib.error, datetime, traceback
H = os.path.expanduser
D = os.path.dirname(os.path.abspath(__file__))
def envf(p):
    d = {}
    try:
        for l in open(H(p)):
            l = l.strip()
            if "=" in l and not l.startswith("#"):
                k, v = l.split("=", 1); d[k.replace("export ", "").strip()] = v.strip().strip('"').strip("'")
    except Exception: pass
    return d
ENV = {**envf(D + "/.env"), **os.environ}; TG = OR = NV = CFG = ENV
TOKEN, CHAT = TG["TG_TOKEN"], str(TG["TG_CHAT"])
OR_KEY = OR.get("OPENROUTER_API_KEY", ""); NV_KEY = NV.get("NVIDIA_API_KEY", "")
BIG = CFG.get("BIG_MODEL", "anthropic/claude-opus-5.5")
FREE = CFG.get("FREE_MODEL", "meta/llama-3.3-70b-instruct")
BUDGET = float(CFG.get("DAILY_BUDGET_USD", "3"))
MAX_STEPS = int(CFG.get("MAX_STEPS", "14"))
DENY = re.compile(r"(live_secrets|wallet\.json|private.?key|PRIVATE_KEY|PK=|mnemonic|seed.?phrase|withdraw|transfer\(|send_transaction|sendTransaction|\.cos/|\.env\b|secrets/|printenv|\benv\b\s*$|aws-bot\.pem|post_order|create_and_post|day_loss_cap|kill_pnl|pmbot/\S*\.(env|json)|cat\s+\S*pem|rm\s+-rf\s+/(\s|$)|shutdown|reboot|mkfs|:\(\)\s*\{)", re.I)

def log(s):
    open(D + "/agent.log", "a").write(f"{datetime.datetime.now():%m-%d %H:%M:%S} {s}\n")
def tg(method, **p):
    data = urllib.parse.urlencode(p).encode()
    return json.load(urllib.request.urlopen(f"https://api.telegram.org/bot{TOKEN}/{method}", data, timeout=70))
import urllib.parse
TL = threading.local()
def send(text, reply_to=None):
    text = (text or "").strip() or "(порожньо)"
    rid = reply_to or getattr(TL, "mid", None)
    for i in range(0, len(text), 3900):
        kw = {"reply_to_message_id": rid, "allow_sending_without_reply": True} if rid else {}
        try: tg("sendMessage", chat_id=CHAT, text=text[i:i+3900], **kw)
        except Exception as e: log(f"send err {e}")
def typing():
    try: tg("sendChatAction", chat_id=CHAT, action="typing")
    except Exception: pass
def tail(p, n):
    try: return "".join(open(H(p), errors="ignore").readlines()[-n:])
    except Exception: return ""
def hist_add(role, text):
    open(D + "/history.jsonl", "a").write(json.dumps({"t": time.time(), "role": role, "text": text[:4000]}, ensure_ascii=False) + "\n")
def hist(n=16):
    out = []
    for l in tail(D + "/history.jsonl", n).splitlines():
        try: j = json.loads(l); out.append(f"{j['role']}: {j['text'][:1200]}")
        except Exception: pass
    return "\n".join(out)
def spent_today():
    day = datetime.date.today().isoformat(); tot = 0.0
    for l in tail(D + "/spend.jsonl", 2000).splitlines():
        try:
            j = json.loads(l)
            if j["day"] == day: tot += j["usd"]
        except Exception: pass
    return tot
def add_spend(usd, model):
    open(D + "/spend.jsonl", "a").write(json.dumps({"day": datetime.date.today().isoformat(), "usd": usd, "model": model}) + "\n")

ZAI_KEY = ENV.get("ZAI_API_KEY", "")
CHAIN = [m.strip() for m in CFG.get("CHAIN","moonshotai/kimi-k3,z-ai/glm-5.3,deepseek-ai/deepseek-v4.1-flash,moonshotai/kimi-k2.6,or:deepseek/deepseek-v4,or:deepseek/deepseek-chat").split(",") if m.strip()]
COOL = {}  # model -> unix time until which it is skipped
def chat_one(model, messages, max_tokens):
    if model.startswith("zai:"):
        url, key, model, extra = "https://api.z.ai/api/coding/paas/v4/chat/completions", ZAI_KEY, model[4:], {"thinking": {"type": "enabled"}}
        max_tokens = max(max_tokens, 32000)
    elif model.startswith("or:"):
        url, key, model, extra = "https://openrouter.ai/api/v1/chat/completions", OR_KEY, model[3:], {"usage": {"include": True}}
    else:
        url, key, extra = "https://integrate.api.nvidia.com/v1/chat/completions", NV_KEY, {}
        if "kimi-k3" in model or "glm" in model or "deepseek" in model: extra = {"reasoning_effort": "high"}
    body = dict(model=model, messages=messages, max_tokens=max_tokens, temperature=0.4, **extra)
    req = urllib.request.Request(url, json.dumps(body).encode(), {"Authorization": "Bearer " + key, "Content-Type": "application/json"})
    j = json.load(urllib.request.urlopen(req, timeout=int(CFG.get('CALL_TIMEOUT','240'))))
    out = j["choices"][0]["message"].get("content") or ""
    out = re.sub(r"<think>.*?</think>", "", out, flags=re.S).strip()
    if not out: raise RuntimeError("empty")
    cost = float((j.get("usage") or {}).get("cost") or 0)
    if cost: add_spend(cost, model)
    return out
LAST_MODEL = [""]
SUBDEPTH = [0]
def chat(_model_ignored, messages, max_tokens):
    errs = []
    for rnd in range(2):
        for m in CHAIN:
            if COOL.get(m, 0) > time.time(): continue
            try:
                out = chat_one(m, messages, max_tokens); LAST_MODEL[0] = m; log(f"model ok {m}"); return out
            except urllib.error.HTTPError as e:
                cd = 900 if e.code in (402, 429) else 300; COOL[m] = time.time() + cd; errs.append(f"{m}:{e.code}")
            except Exception as e:
                COOL[m] = time.time() + 300; errs.append(f"{m}:{type(e).__name__}")
            log(f"model fail {errs[-1]}")
        COOL.clear(); time.sleep(20)
    raise RuntimeError("усі моделі недоступні: " + ", ".join(errs[-6:]))

def score_digest():
    try: t = open(H("~/bridge/paper_v2_scorecard.md"), errors="ignore").read()
    except Exception: return "(нема скоркарду)"
    i = t.rfind("## Scorecard"); t = t[i:] if i >= 0 else t
    L = t.splitlines(); out = L[:2]
    for k, l in enumerate(L):
        if l.startswith("### RANKING"):
            out += ["Колонки: rank|market|variant|windows|resolution $|$ за вікно|worst|best|sd|t|positive windows"] + L[k+1:k+13]
    out += [l for l in L if re.match(r"^\| (V4|V4X|V5) \| \d+ \| [+-]", l)][-3:]
    out += [l for l in L if l.startswith(("TOTAL", "LIVE PICK"))]
    return "\n".join(out)

def status_ctx():
    return ("MEMORY:\n" + tail(D + "/MEMORY.md", 200) +
            "\n\nSNIPE5 STATUS (AWS):\n" + tail("~/claude_tg/snipe5_status.txt", 60) +
            "\n\nПАПІР, ОСТАННІЙ СКОРКАРД (вгорі найкращі пари; старі варіанти CTRL/H/M/V3 вимкнені, їхні мінуси в TOTAL історичні):\n" + score_digest() +
            "\n\nEDGE RESEARCH NOTES:\n" + tail("~/edge/NOTES.md", 30))

TRIAGE = ("Ти диспетчер повідомлень Володимира. Відповідай українською. Якщо це просте питання про статус, "
          "на яке можна точно відповісти з наведеного контексту, або просто балачка, відповідай одразу коротко (1-5 речень), "
          "цифри бери тільки з контексту, нічого не вигадуй. Якщо потрібна дія, перевірка на сервері, код, дослідження, "
          "рішення, свіжі дані, або ти не впевнений, відповідай рівно одним словом TASK.")

AGENT = open(D + "/SYSTEM_PROMPT.md").read() + "\n\nINFO PACK:\n" + (open(D + "/INFO_PACK.md").read() if os.path.exists(D + "/INFO_PACK.md") else "")

def run_sh(cmd):
    if DENY.search(cmd): return "BLOCKED: ця команда заборонена правилами (живі гроші/ключі/небезпечне)."
    try:
        import signal
        p = subprocess.Popen(["bash", "-lc", cmd], stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, cwd=ENV.get("WORKDIR", D), start_new_session=True)
        try: o, _ = p.communicate(timeout=180)
        except subprocess.TimeoutExpired:
            os.killpg(p.pid, signal.SIGKILL)
            try: o, _ = p.communicate(timeout=5)
            except Exception: o = ""
            return "TIMEOUT 180s (команду вбито; розбий на менші кроки)\n" + (o or "")[-1500:]
        return f"exit={p.returncode}\n" + (o[:3500] + ("\n...[обрізано]" if len(o) > 3500 else ""))
    except Exception as e:
        return f"ERR {e}"

def agent_task(user_text):
    model = BIG
    if spent_today() >= BUDGET:
        model = FREE; log("budget reached, free model")
    msgs = [{"role": "system", "content": AGENT + "\n\nКОНТЕКСТ:\n" + status_ctx() + "\n\nОСТАННЯ РОЗМОВА:\n" + hist()},
            {"role": "user", "content": user_text}]
    fell = False
    for step in range(MAX_STEPS):
        typing()
        try:
            out = chat(model, msgs, 16000)
        except urllib.error.HTTPError as e:
            if model != FREE:
                log(f"{model} http {e.code}, fallback free"); model = FREE; fell = True; continue
            raise
        msgs.append({"role": "assistant", "content": out})
        if time.time() - LASTPROG[0] > 1200 and SUBDEPTH[0] == 0:
            msgs.append({"role": "user", "content": "Час вийшов (20 хв). Зупинись і дай короткий підсумок у <reply>."})
            LASTPROG[0] = time.time() + 10**6
        r = re.search(r"<reply>(.*?)(</reply>|$)", out, re.S)
        cmds = re.findall(r"<sh>(.*?)</sh>", out, re.S)
        subs = re.findall(r"<sub>(.*?)</sub>", out, re.S)
        if subs and not r and SUBDEPTH[0] == 0:
            NOW[0] = f"запустив {len(subs[:4])} підагентів"
            import concurrent.futures as cf
            def one(t):
                SUBDEPTH[0] += 1
                try: return agent_task("ПІДЗАДАЧА від оператора (не пиши Володимиру, просто дай результат у <reply>):\n" + t.strip())
                finally: SUBDEPTH[0] -= 1
            with cf.ThreadPoolExecutor(4) as ex: res = list(ex.map(one, subs[:4]))
            msgs.append({"role": "user", "content": "РЕЗУЛЬТАТИ ПІДАГЕНТІВ:\n" + "\n\n".join(f"[{i+1}] {x[:3000]}" for i, x in enumerate(res))})
            continue
        if cmds and not r:
            res = "\n\n".join(f"$ {c.strip()}\n{run_sh(c.strip())}" for c in cmds[:3])
            log(f"sh: {' | '.join(c.strip()[:120] for c in cmds[:3])}")
            NOW[0] = "виконую: " + cmds[0].strip()[:150]

            msgs.append({"role": "user", "content": "ВИВІД:\n" + res})
            continue
        final = r.group(1).strip() if r else re.sub(r"<note>.*?</note>", "", out, flags=re.S).strip()
        if not final:
            msgs.append({"role": "user", "content": "Відповідь порожня. Напиши Володимиру конкретний підсумок: що зробив, що знайшов, цифри, наступний крок. Тільки у <reply>...</reply>."}); continue
        
        return final
    return "Зупинився після ліміту кроків. Напиши, чи продовжувати."

NOW = ["нічого, чекаю повідомлень"]; LASTPROG = [0]; BUSY = threading.Lock()
def handle_bg(text, mid=None):
    TL.mid = mid
    with BUSY:
        NOW[0] = "думаю над: " + text[:100]; LASTPROG[0] = time.time()
        try: handle(text)
        except Exception as e:
            log("handle err " + traceback.format_exc()[-800:]); send(f"Помилка: {e}")
        finally: NOW[0] = "нічого, чекаю повідомлень"
def handle(text):
    hist_add("Володимир", text)
    typing()
    ans = None
    if NV_KEY and not text.startswith("/claude"):
        try:
            t = chat(FREE, [{"role": "system", "content": TRIAGE + "\n\nКОНТЕКСТ:\n" + status_ctx() + "\n\nОСТАННЯ РОЗМОВА:\n" + hist(8)},
                            {"role": "user", "content": text}], 4000)
            if t and "TASK" not in t.upper()[:20] and t.upper() != "TASK": ans = t
        except Exception as e: log(f"triage err {e}")
    if ans is None:
        ans = agent_task(text.replace("/claude", "", 1).strip())
        who = LAST_MODEL[0]
    else: who = LAST_MODEL[0]
    if ans.strip().upper().startswith("SKIP"): log("auto skip"); return
    if text.startswith("АВТОЦИКЛ") and ans.strip().startswith("Зупинився після ліміту кроків"): log("auto steplimit muted"); return
    log("REPLY: " + ans.replace("\n", " ")[:3000]); send(ans); hist_add(f"асистент({who})", ans); log(f"answered via {who}, spent today ${spent_today():.3f}")

def watcher():
    seen_f = D + "/seen_settled.txt"
    while True:
        try:
            p = subprocess.run(["bash","-c","./remote.sh 'cat ~/snipe5/status.json; echo; echo ---LAST_SETTLED; tail -n 400 ~/snipe5/live_settled.jsonl; echo ---LOG; tail -n 15 ~/snipe5/log.txt'"],capture_output=True,text=True,timeout=60)
            txt = p.stdout
            if "---LAST_SETTLED" in txt:
                st, rest = txt.split("---LAST_SETTLED",1); sett, lg = rest.split("---LOG",1)
                lines = [l for l in sett.splitlines() if l.strip()]
                open(D + "/snipe5_status.txt","w").write(st[:6000] + "\nLAST LIVE SETTLED:\n" + "\n".join(lines[-8:]) + "\nLOG:\n" + lg[-2500:])
                try: seen = set(open(seen_f).read().split("\n"))
                except Exception: seen = None
                new = [l for l in lines if seen is not None and l not in seen]
                open(seen_f,"w").write("\n".join(lines))
                for l in new[-3:]:
                    try: pnl = float(json.loads(l).get("pnl", 0))
                    except Exception: continue
                    if pnl < 0:
                        log("loss audit " + l[:200])
                        ans = agent_task("АВТОАУДИТ (не повідомлення від Володимира): щойно закрилась збиткова live-угода snipe5:\n" + l + "\nРозберись у коді і логах на AWS чому, і дай Володимиру коротку нотатку (2-4 речення): причина + чи треба щось міняти. Якщо зміна безпечна і очевидна, зроби її з бекапом.")
                        send("🔎 Аудит збитку: " + ans); hist_add("асистент(audit)", ans)
                if seen is not None and '"kill": true' in st and not os.path.exists(D + "/kill_reported"):
                    open(D + "/kill_reported","w").write("1"); send("⛔ snipe5: спрацював KILL, лайв зупинено.")
        except Exception as e: log(f"watch err {e}")
        time.sleep(30)

def console_in():
    f = D + "/console_in.txt"
    while True:
        try:
            if os.path.exists(f) and os.path.getsize(f):
                t = open(f).read().strip(); open(f, "w").close()
                if t:
                    log("console> " + t[:200]); send("💻 З консолі: " + t)
                    threading.Thread(target=handle_bg, args=(t, None), daemon=True).start()
        except Exception as e: log(f"console err {e}")
        time.sleep(1)
def improver():
    time.sleep(30)
    while True:
        if not BUSY.locked():
            handle_bg("АВТОЦИКЛ (не повідомлення Володимира): зроби ВІЧНИЙ ЦИКЛ ПОКРАЩЕННЯ — перевір snipe5 і зроби одне покращення. Якщо нічого вартого — відповідь лише слово SKIP.")
        time.sleep(60)
LASTPOLL = [time.time()]
def watchdog():
    while True:
        time.sleep(20)
        if time.time() - LASTPOLL[0] > 180:
            log("watchdog: poll stuck, restarting"); os._exit(3)
        if BUSY.locked() and time.time() - LASTPROG[0] > 1800 and LASTPROG[0] < time.time():
            log("watchdog: task stuck >30m, restarting"); send("Задача зависла, перезапускаюсь."); os._exit(4)
def main():
    threading.Thread(target=watchdog, daemon=True).start()
    threading.Thread(target=improver, daemon=True).start()
    threading.Thread(target=watcher, daemon=True).start()
    threading.Thread(target=console_in, daemon=True).start()
    off_f = D + "/tg_offset"
    try: off = int(open(off_f).read().strip())
    except Exception: off = 0
    log("started")
    while True:
        try:
            r = tg("getUpdates", offset=off, timeout=25); LASTPOLL[0] = time.time()
            for u in r.get("result", []):
                off = u["update_id"] + 1; open(off_f, "w").write(str(off))
                m = u.get("message") or {}
                if str(m.get("chat", {}).get("id")) != CHAT: continue
                t = m.get("text") or m.get("caption")
                if not t: send("Поки розумію тільки текст."); continue
                ts = datetime.datetime.utcfromtimestamp(m.get("date", 0)).strftime("%Y-%m-%d %H:%M UTC")
                open(H("~/bridge/tg_inbox.md"), "a").write(f"- [{ts}] {t}\n")
                if t.strip() in ("/spend", "/витрати"):
                    send(f"Сьогодні витрачено ${spent_today():.3f} з ліміту ${BUDGET}."); continue
                if t.strip().lower() in ("/status", "що робиш", "що робиш?", "статус"):
                    send("Зараз: " + NOW[0], reply_to=m.get("message_id")); continue
                send(reply_to=m.get("message_id"), text="👌 Прийняв" + (", доробляю попереднє і візьмусь" if BUSY.locked() else ", працюю"))
                threading.Thread(target=handle_bg, args=(t, m.get("message_id")), daemon=True).start()
        except Exception as e:
            log(f"poll err {e}"); time.sleep(5)

if __name__ == "__main__": main()

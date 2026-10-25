import http.server, json, os, html
D=os.path.dirname(os.path.abspath(__file__))
PAGE='''<!doctype html><meta charset=utf-8><title>GLM-5.3</title><style>
body{margin:0;font:15px system-ui;background:#0f1117;color:#e6e6e6;display:flex;height:100vh}
#chat{flex:3;display:flex;flex-direction:column}#msgs{flex:1;overflow:auto;padding:16px}
.m{max-width:75%;margin:8px 0;padding:10px 14px;border-radius:14px;white-space:pre-wrap}
.u{background:#2b5cff;margin-left:auto}.a{background:#1f2430}.t{font-size:11px;opacity:.6}
form{display:flex;padding:10px;background:#161a22}textarea{flex:1;background:#0f1117;color:#fff;border:1px solid #333;border-radius:10px;padding:10px;font:15px system-ui;height:60px}
button{margin-left:8px;background:#2b5cff;color:#fff;border:0;border-radius:10px;padding:0 20px;font-size:15px}
#log{flex:2;background:#0a0c10;font:12px monospace;overflow:auto;padding:10px;white-space:pre-wrap;border-left:1px solid #222}
#st{padding:8px 16px;background:#161a22;font-size:13px}</style>
<div id=chat><div id=st>GLM-5.3 оператор (Z.ai)</div><div id=msgs></div>
<form onsubmit="s();return false"><textarea id=i placeholder="Напиши Кімі... (Enter надіслати, Shift+Enter новий рядок)"></textarea><button>Надіслати</button></form></div><pre id=log></pre>
<script>
i.onkeydown=e=>{if(e.key=="Enter"&&!e.shiftKey){e.preventDefault();s()}}
async function s(){let t=i.value.trim();if(!t)return;i.value="";await fetch("/send",{method:"POST",body:t});r()}
let n=0;async function r(){let j=await (await fetch("/data")).json();
if(j.h.length!=n){n=j.h.length;msgs.innerHTML=j.h.map(m=>`<div class="m ${m.role.startsWith("Вол")?"u":"a"}"><div class=t>${m.role} · ${new Date(m.t*1000).toLocaleTimeString()}</div>${m.text}</div>`).join("");msgs.scrollTop=1e9}
let b=log.scrollTop+log.clientHeight>=log.scrollHeight-20;log.textContent=j.l;if(b)log.scrollTop=1e9}
r();setInterval(r,2000)</script>'''
class H(http.server.BaseHTTPRequestHandler):
    def log_message(s,*a):pass
    def do_GET(s):
        if s.path=="/data":
            h=[]
            for l in open(D+"/history.jsonl"):
                try:j=json.loads(l);j["text"]=html.escape(j.get("text") or "");j["role"]=html.escape(j["role"]);h.append(j)
                except:pass
            lg=open(D+"/agent.log").read()[-20000:]
            b=json.dumps({"h":h[-200:],"l":lg}).encode();ct="application/json"
        else:b=PAGE.encode();ct="text/html; charset=utf-8"
        s.send_response(200);s.send_header("Content-Type",ct);s.end_headers();s.wfile.write(b)
    def do_POST(s):
        t=s.rfile.read(int(s.headers["Content-Length"])).decode()
        open(D+"/console_in.txt","a").write(t+"\n");s.send_response(200);s.end_headers()
http.server.ThreadingHTTPServer(("127.0.0.1",18793),H).serve_forever()

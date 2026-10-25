# telegram-ai-ops-agent

A Telegram bot that acts as an operations assistant for a server running trading bots.

**What:** a cheap/free LLM (NVIDIA NIM) triages each message and answers status questions itself;
real tasks go to a stronger model (OpenRouter or Z.ai) that can run shell commands in a loop
(tool use, up to `MAX_STEPS`) and replies with a summary. It also watches bot logs and reports events.

**Why:** to monitor and debug bots from a phone while keeping LLM cost under a daily budget.

**Stack:** Python 3 standard library only (urllib, threading, subprocess), Telegram Bot API,
OpenAI-compatible chat APIs (OpenRouter, NVIDIA NIM, Z.ai).

## Architecture
```
Telegram long-poll ─> triage (free model) ─┬─> quick answer
                                           └─> agent loop (big model) ─> shell tool (deny-list) ─> reply
watcher thread: tails bot logs -> alerts      spend.jsonl: daily USD budget, fallback to free model on 402
ui.py: local web console (127.0.0.1)          console.sh: terminal console
```
Safety: a regex deny-list blocks commands touching keys, `.env`, wallets, withdrawals or order placement;
only the configured chat id is answered; budget cap with fallback.

## Run
```bash
cp .env.example .env   # fill TG_TOKEN, TG_CHAT and at least one model key
python3 agent.py
python3 ui.py          # optional web console at http://127.0.0.1:18793
```
Prompts in the code are in Ukrainian (the bot's language).

_Code written with AI coding agents under my direction; I designed the flow, safety rules and tested it in daily use._

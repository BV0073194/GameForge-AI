#!/usr/bin/env python3
"""GameForge Codex auth deep diagnostics.

Produces one aggressively redacted text report. It NEVER prints credential
values, auth.json token contents, cookies, or API-key values.
"""
from __future__ import annotations
import json, os, platform, re, shutil, subprocess, sys, tempfile, time
from pathlib import Path

OUT = Path.cwd() / f"gameforge-codex-auth-diagnostics-{time.strftime('%Y%m%d-%H%M%S')}.txt"
SENSITIVE = re.compile(r'(?i)(authorization|access[_ -]?token|refresh[_ -]?token|id[_ -]?token|api[_ -]?key|cookie|secret)')
ENV_NAMES = [
    "CODEX_HOME","OPENAI_BASE_URL","OPENAI_API_BASE","OPENAI_API_KEY","CODEX_API_KEY",
    "CODEX_ACCESS_TOKEN","HTTP_PROXY","HTTPS_PROXY","ALL_PROXY","NO_PROXY",
]
lines=[]

def emit(x=""): lines.append(str(x))
def run(args, env=None, cwd=None, timeout=90):
    try:
        p=subprocess.run(args, env=env, cwd=cwd, capture_output=True, text=True,
                         errors="replace", timeout=timeout)
        return p.returncode, redact((p.stdout or "")+("\n" if p.stdout and p.stderr else "")+(p.stderr or ""))
    except Exception as e: return -999, f"{type(e).__name__}: {e}"

def redact(text):
    text=re.sub(r'(?i)Bearer\s+[A-Za-z0-9._~+/-]+', 'Bearer <REDACTED>', text)
    text=re.sub(r'(?i)\b(sk-[A-Za-z0-9_-]{8,})\b', '<REDACTED_KEY>', text)
    text=re.sub(r'(?i)(access_token|refresh_token|id_token|api_key)(["\' ]*[:=]["\' ]*)([^\s,"\'}]+)', r'\1\2<REDACTED>', text)
    return text

def section(name): emit("\n"+"="*78); emit(name); emit("="*78)

section("GAMEFORGE / CODEX AUTH DEEP DIAGNOSTICS")
emit(f"time_local: {time.strftime('%Y-%m-%d %H:%M:%S %z')}")
emit(f"platform: {platform.platform()}")
emit(f"python: {sys.version}")
emit(f"cwd: {Path.cwd()}")
emit(f"executable: {sys.executable}")

section("EXECUTABLE RESOLUTION")
for name in ("codex","node","git","python","py"):
    emit(f"{name}: {shutil.which(name) or '<not found>'}")
if os.name=="nt":
    for cmd in (["where","codex"],["where","node"],["where","git"]):
        rc,out=run(cmd,timeout=15); emit(f"$ {' '.join(cmd)}\nexit={rc}\n{out}")

section("ENVIRONMENT PRESENCE (VALUES NEVER PRINTED)")
for n in ENV_NAMES:
    v=os.environ.get(n)
    if n.endswith("_PROXY") and v:
        # Proxy URLs may contain credentials; report presence only.
        emit(f"{n}: SET")
    elif n in ("CODEX_HOME","OPENAI_BASE_URL","OPENAI_API_BASE") and v:
        emit(f"{n}: SET (value intentionally redacted)")
    else:
        emit(f"{n}: {'SET' if v else 'unset'}")

codex=shutil.which("codex")
if not codex:
    section("FATAL"); emit("Codex is not resolvable."); OUT.write_text("\n".join(lines),encoding="utf-8"); print(OUT); raise SystemExit(2)

section("CODEX VERSION / LOGIN STATUS")
for args in ([codex,"--version"],[codex,"login","status"]):
    rc,out=run(args,timeout=30); emit(f"$ {' '.join(args[1:])}\nexit={rc}\n{out}")

section("CODEX DOCTOR JSON (CODEX'S OWN REDACTION + SECONDARY REDACTION)")
rc,doctor=run([codex,"doctor","--json"],timeout=120)
emit(f"exit={rc}\n{doctor}")

home=Path(os.environ.get("CODEX_HOME") or (Path.home()/".codex"))
section("CODEX HOME / AUTH METADATA (NO CREDENTIAL VALUES)")
emit(f"CODEX_HOME effective path: {home}")
auth=home/"auth.json"
emit(f"auth.json exists: {auth.exists()}")
if auth.exists():
    try:
        data=json.loads(auth.read_text(encoding="utf-8"))
        emit(f"auth.json top-level keys: {sorted(data.keys())}")
        def shape(obj,prefix=""):
            if isinstance(obj,dict):
                for k,v in obj.items():
                    p=f"{prefix}.{k}" if prefix else k
                    if SENSITIVE.search(k):
                        emit(f"{p}: <present:{type(v).__name__}>")
                    elif isinstance(v,(dict,list)): shape(v,p)
                    else: emit(f"{p}: <{type(v).__name__}>")
            elif isinstance(obj,list): emit(f"{prefix}: <list length={len(obj)}>")
        shape(data)
    except Exception as e: emit(f"auth.json metadata read error: {type(e).__name__}: {e}")

section("CONFIG ROUTING (SECRET-LIKE LINES REDACTED)")
cfg=home/"config.toml"; emit(f"config: {cfg} exists={cfg.exists()}")
if cfg.exists():
    for n,line in enumerate(cfg.read_text(encoding="utf-8",errors="replace").splitlines(),1):
        if SENSITIVE.search(line): emit(f"{n}: <REDACTED SECRET-LIKE CONFIG LINE>")
        elif re.search(r'(?i)(model_provider|base_url|openai_base_url|wire_api|preferred_auth|responses_websocket|credential|sandbox|approval)',line):
            emit(f"{n}: {line}")

section("REAL INFERENCE A/B TEST")
prompt="Reply with exactly GAMEFORGE_AUTH_OK. Do not inspect or modify files."
base=[codex,"exec","--json","--skip-git-repo-check","--sandbox","read-only",prompt]
tests=[("A inherited environment",os.environ.copy())]
clean=os.environ.copy()
for n in ("OPENAI_BASE_URL","OPENAI_API_BASE"): clean.pop(n,None)
tests.append(("B routing overrides removed; credentials preserved",clean))
for label,env in tests:
    emit(f"\n--- {label} ---")
    emit("env presence: "+", ".join(f"{n}={'SET' if env.get(n) else 'unset'}" for n in ENV_NAMES))
    rc,out=run(base,env=env,cwd=Path.cwd(),timeout=90)
    emit(f"exit={rc}\n{out}")

section("GAMEFORGE LOG INVENTORY")
roots=[
    Path(os.environ.get("LOCALAPPDATA",""))/"GameForgeAI",
    Path.home()/".gameforge-ai", Path.home()/".gameforge_ai",
]
seen=set()
for root in roots:
    if not str(root) or root in seen: continue
    seen.add(root); emit(f"root: {root} exists={root.exists()}")
    if root.exists():
        for p in list(root.rglob("codex-iteration-*.jsonl"))[-5:]+list(root.rglob("codex-iteration-*.final.txt"))[-5:]:
            try:
                emit(f"\nFILE {p}\n{redact(p.read_text(encoding='utf-8',errors='replace')[-12000:])}")
            except Exception as e: emit(f"read error {p}: {e}")

section("INTERPRETATION HINTS")
emit("If doctor says stored auth mode=chatgpt but A/B both fail missing bearer, suspect Codex runtime/auth transport.")
emit("If A fails and B succeeds, an inherited base-URL/provider environment override is the cause.")
emit("If direct diagnostics succeed but GameForge still fails, compare executable path/CODEX_HOME/environment with GameForge.")
emit("Do not upload auth.json. Upload only this generated report.")

OUT.write_text("\n".join(lines),encoding="utf-8")
print(f"Diagnostic report written to: {OUT}")

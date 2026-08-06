# Local Dev Setup (macOS)

Quick reference for running the app locally in dev mode (frontend with hot-reload via
Vite, not the `docker compose` / production build path described in the main
[README](README.md)). Copy commands straight out of the code blocks into your terminal.

## One-time setup

**1. Homebrew + Node.js** (skip if `node -v` already works)

```bash
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
eval "$(/opt/homebrew/bin/brew shellenv zsh)"
brew install node
```

**2. Python virtualenv + backend deps**

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

**3. API key**

```bash
cp .env.example .env
```

Open `.env` and set `ANTHROPIC_API_KEY=` to your real key (line ~15). Leave
`OPENAI_API_KEY` as-is if you don't have one — `LLM_PROVIDER=anthropic` is already the
default. The app works without any key too (deterministic fallback mode), just without
LLM summaries or image interpretation.

**4. Frontend deps**

```bash
npm --prefix frontend install
```

## Every time you want to run the app

Two terminals, both from the repo root.

**Terminal 1 — backend**

```bash
.venv/bin/uvicorn app.main:app --reload
```

**Terminal 2 — frontend**

```bash
npm --prefix frontend run dev
```

Vite prints a local URL, typically `http://localhost:5173` — open that in your browser.

## Notes / gotchas hit so far

- `eval "$(/opt/homebrew/bin/brew shellenv zsh)"` only affects the shell it's run in.
  If a fresh terminal tab can't find `brew`/`node`/`npm`, either re-run that line or make
  sure the Homebrew installer's PATH lines ended up in `~/.zprofile`.
- The app starting cleanly does **not** prove your API key is loaded — it also starts
  fine with zero key (fallback mode). Check the key made it into `.env` itself (not
  `local.env` or any other filename — the app only reads `.env`).
- If `vite: command not found` when running `npm --prefix frontend run dev`, it means
  `npm --prefix frontend install` was never run (no `frontend/node_modules`).

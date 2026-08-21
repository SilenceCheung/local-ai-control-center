#!/bin/bash
# Local AI Control Center installer.
# - creates the Python venv and installs dependencies
# - builds the web dashboard
# - links the local-ai CLI into ~/.local/bin
# - optionally installs launchd services (asks first)
# It never touches LM Studio, Ollama, system Python, or agent configs.
set -euo pipefail
cd "$(dirname "$0")/.."
ROOT="$PWD"
DFLASH_MLX_REF="${DFLASH_MLX_REF:-60803233af4589e18588b9bacbb03880801c828a}"
DFLASH_MLX_URL="git+https://github.com/bstnxbt/dflash-mlx.git@${DFLASH_MLX_REF}"

echo "== Local AI Control Center installer =="

if [ ! -f config/config.yaml ]; then
  cp config/config.example.yaml config/config.yaml
  echo "created local config/config.yaml from the public example"
fi

PY=""
for cand in python3.12 python3.11 python3.13; do
  if command -v "$cand" >/dev/null 2>&1; then PY="$cand"; break; fi
done
[ -z "$PY" ] && { echo "error: need python 3.11–3.13 (brew install python@3.12)"; exit 1; }
echo "using $($PY --version)"

if [ ! -x .venv/bin/python ]; then
  "$PY" -m venv .venv
fi
.venv/bin/pip install -q --upgrade pip
.venv/bin/pip install -q "$DFLASH_MLX_URL" mlx-lm fastapi "uvicorn[standard]" httpx pyyaml psutil pytest pytest-asyncio huggingface_hub
echo "python deps ok (dflash-mlx ref: $DFLASH_MLX_REF)"

if command -v pnpm >/dev/null 2>&1; then
  (cd frontend && pnpm install --silent && pnpm build >/dev/null)
  echo "frontend built"
elif command -v npm >/dev/null 2>&1; then
  (cd frontend && npm install --silent && npm run build >/dev/null)
  echo "frontend built (npm)"
else
  echo "warning: node/pnpm not found — dashboard will run API-only until you build frontend/"
fi

mkdir -p "$HOME/.local/bin"
cat > "$HOME/.local/bin/local-ai" <<EOF
#!/bin/bash
exec "$ROOT/.venv/bin/python" "$ROOT/cli/local_ai.py" "\$@"
EOF
chmod +x "$HOME/.local/bin/local-ai"
echo "CLI installed: ~/.local/bin/local-ai (ensure ~/.local/bin is in PATH)"

.venv/bin/python -c "from backend.services.launchd import write_plists; print('plists:', [str(p) for p in write_plists()])"

read -r -p "Install launchd services (dashboard + API gateway auto-start at login)? [y/N] " yn
if [[ "$yn" =~ ^[Yy]$ ]]; then
  .venv/bin/python - <<'PYEOF'
from backend.services.launchd import install
for svc in ("backend", "gateway"):
    r = install(svc)
    print(svc, "->", "ok" if r["ok"] else f"failed: {r['output']}")
PYEOF
fi

echo
echo "Done. Next:"
echo "  local-ai start                 # start everything"
echo "  open http://127.0.0.1:8787     # web dashboard"
echo "  bash scripts/build_app.sh      # native menu bar app (ad-hoc signed)"
echo "  local-ai app                   # open Local AI.app after building"

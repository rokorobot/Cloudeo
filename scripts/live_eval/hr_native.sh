#!/usr/bin/env bash
# Run the pinned HarnessRouter CE natively in a Cloudroom cloud sandbox (EVAL-01 live trials).
#
# Cloudroom sandboxes cannot run containers (no mount namespaces, chroot or mknod), so this
# installs the image's contents directly: the same source commit, the same pinned Claude Code
# and Codex versions, the same environment and the same three processes (runner as root,
# gateway and console as the 'agent' user) as docker/entrypoint.sh of that commit.
#
# Deliberate deviations from the image entrypoint, recorded in docs/EVAL-01_LIVE.md:
#   - it does not chown/chmod the machine's /tmp, /var/tmp or /dev/shm (shared with everything
#     else in the sandbox);
#   - only the claude and codex backends are installed;
#   - Node.js is the sandbox's (the image installs Node 22).
#
# Usage: hr_native.sh install | start ENV_FILE | stop | status
# ENV_FILE holds ANTHROPIC_API_KEY and OPENAI_API_KEY (never printed).
set -euo pipefail

HR_COMMIT=809392d602e34e36f0468943035c54d3350af885   # HarnessRouter CE v0.23.7
HR_REPO=https://github.com/HarnessRouter/harnessrouter.git
CLAUDE_CODE_VERSION=2.1.280
CODEX_VERSION=0.154.0
ROOT=/opt/harnessrouter
SRC=$ROOT/src
APP=$ROOT/app
VENV=$ROOT/venv
DATA=$ROOT/data
TOOLS=$DATA/agent-tools
RUN=$ROOT/run
PORT=18810

log() { echo "[hr-native] $*"; }

install() {
  sudo mkdir -p "$ROOT" && sudo chown "$(id -u):$(id -g)" "$ROOT"
  if [ ! -d "$SRC/.git" ]; then
    git clone -q --filter=blob:none "$HR_REPO" "$SRC"
  fi
  git -C "$SRC" fetch -q origin "$HR_COMMIT" 2>/dev/null || true
  git -C "$SRC" checkout -q "$HR_COMMIT"
  log "source at $(git -C "$SRC" rev-parse HEAD)"
  id agent >/dev/null 2>&1 || sudo useradd -m -u 10001 agent

  # A Python under $ROOT, not the installing user's home: the gateway and console run as
  # 'agent' and must be able to execute it.
  if [ ! -x "$VENV/bin/python" ] || ! sudo -u agent "$VENV/bin/python" -c "" 2>/dev/null; then
    sudo rm -rf "$VENV"   # the root runner may have left bytecode in it
    UV_PYTHON_INSTALL_DIR="$ROOT/python" uv python install -q 3.12
    uv venv -q --python "$(UV_PYTHON_INSTALL_DIR="$ROOT/python" uv python find 3.12)" "$VENV"
    sudo chmod -R a+rX "$ROOT/python" "$VENV"
  fi
  grep -viE "^(azure-|azure_)" "$SRC/gateway/requirements.txt" > "$ROOT/gateway-req.local.txt"
  uv pip install -q --python "$VENV/bin/python" -r "$ROOT/gateway-req.local.txt" \
    -r "$SRC/runner/requirements.txt"
  sudo chmod -R a+rX "$VENV" "$ROOT/python"   # some bytecode is root-owned (written by the runner)
  log "python dependencies installed"

  if [ ! -f "$APP/ui/server.js" ]; then
    ( cd "$SRC/ui" && (npm ci --no-audit --no-fund >/dev/null 2>&1 || npm install --no-audit --no-fund >/dev/null) \
      && NEXT_TELEMETRY_DISABLED=1 NEXT_PUBLIC_HR_EDITION=selfhost npm run build >/dev/null )
    mkdir -p "$APP/ui/.next"
    cp -a "$SRC/ui/.next/standalone/." "$APP/ui/"
    cp -a "$SRC/ui/.next/static" "$APP/ui/.next/static"
    cp -a "$SRC/ui/public" "$APP/ui/public"
    log "console built"
  fi
  sudo rm -rf "$APP/gateway" "$APP/runner"   # may hold root-owned bytecode from the runner
  cp -a "$SRC/gateway" "$APP/gateway"
  cp -a "$SRC/runner" "$APP/runner"
  sudo chmod -R a+rX "$APP"

  sudo mkdir -p "$DATA/workspaces" "$TOOLS" "$RUN"
  sudo chown agent:agent "$DATA" "$DATA/workspaces"
  sudo chmod 751 "$DATA" "$DATA/workspaces"
  # As the entrypoint's install_backends(): version-pinned npm installs into the data volume.
  if [ "$("$TOOLS/bin/claude" --version 2>/dev/null | grep -oE '[0-9]+\.[0-9]+\.[0-9]+' | head -1)" != "$CLAUDE_CODE_VERSION" ]; then
    sudo npm install -g -q --prefix "$TOOLS" --no-audit --no-fund "@anthropic-ai/claude-code@$CLAUDE_CODE_VERSION" >/dev/null
  fi
  if [ "$("$TOOLS/bin/codex" --version 2>/dev/null | awk '{print $2}')" != "$CODEX_VERSION" ]; then
    sudo npm install -g -q --prefix "$TOOLS" --no-audit --no-fund "@openai/codex@$CODEX_VERSION" >/dev/null
  fi
  log "claude $("$TOOLS/bin/claude" --version 2>/dev/null | head -1); codex $("$TOOLS/bin/codex" --version 2>/dev/null | head -1)"
}

start() {
  env_file=$1
  [ -f "$APP/ui/server.js" ] || { log "not installed: run '$0 install' first"; exit 1; }
  stop >/dev/null 2>&1 || true
  # Values are read into this process only; nothing is echoed.
  set -a; . "$env_file"; set +a
  export HR_AUTH_PASSWORD="$(openssl rand -hex 24)"
  umask 077
  sudo mkdir -p "$RUN" && sudo chown "$(id -u)" "$RUN"
  printf '%s' "$HR_AUTH_PASSWORD" > "$RUN/console-password"

  # Environment exactly as docker/entrypoint.sh at the pinned commit sets it; every value
  # shell-quoted, because the provider connections are JSON.
  DATA=$DATA TOOLS=$TOOLS VENV=$VENV PORT=$PORT CLAUDE_CODE_VERSION=$CLAUDE_CODE_VERSION \
  CODEX_VERSION=$CODEX_VERSION "$VENV/bin/python" - "$RUN/hr.env" <<'PY'
import json, os, secrets, shlex, sys
e = os.environ
conn = lambda name, key: json.dumps({"name": name, "provider": name, "api_key": e[key]})
values = {
    "HR_BACKING": "local", "HR_DATA_DIR": e["DATA"], "HARNESS_WORKSPACE": f"{e['DATA']}/workspaces",
    "HR_IDENTITY_MODE": "off", "HR_CREDIT_GATE": "off",
    "POOL_MGMT_ENDPOINT": "http://127.0.0.1:8081", "HR_POOL_AUTH": "none",
    "HR_SANDBOX_TRUST": "owner", "HR_BROKER_IMAGES": "1", "HARNESS_CODEX_APPSERVER": "1",
    "HARNESS_INTERNAL_KEY": secrets.token_hex(32), "HARNESS_GATEWAY_URL": "http://127.0.0.1:8080",
    "NEXT_PUBLIC_HR_EDITION": "selfhost", "NEXT_TELEMETRY_DISABLED": "1",
    "CLAUDE_CODE_VERSION": e["CLAUDE_CODE_VERSION"], "HR_CODEX_VERSION": e["CODEX_VERSION"],
    "HR_BACKENDS": "claude,codex", "HR_AUTH_USER": "cloudeo",
    "HR_AUTH_PASSWORD": e["HR_AUTH_PASSWORD"], "HR_AUTH_STORE": f"{e['DATA']}/selfhost-auth.json",
    "PORT": e["PORT"], "HOSTNAME": "127.0.0.1", "HOME": "/home/agent", "PYTHONUNBUFFERED": "1",
    "PATH": f"{e['TOOLS']}/bin:{e['VENV']}/bin:/usr/local/bin:/usr/bin:/bin",
    "NODE_PATH": f"{e['TOOLS']}/lib/node_modules",
    "HR_SECRET_GLOBAL_HARNESS_CONN_ANTHROPIC": conn("anthropic", "ANTHROPIC_API_KEY"),
    "HR_SECRET_GLOBAL_HARNESS_POLICY_CLAUDE": json.dumps({"chain": ["anthropic"]}),
    "HR_SECRET_GLOBAL_HARNESS_CONN_OPENAI": conn("openai", "OPENAI_API_KEY"),
    "HR_SECRET_GLOBAL_HARNESS_POLICY_CODEX": json.dumps({"chain": ["openai"]}),
}
with open(sys.argv[1], "w") as f:
    f.write("".join(f"{k}={shlex.quote(v)}\n" for k, v in values.items()))
PY
  sudo chown root:root "$RUN/hr.env" && sudo chmod 600 "$RUN/hr.env"

  # The three processes, as the entrypoint starts them. The runner keeps root (it allocates a
  # uid per session); gateway and console run as 'agent'. Logs never contain the env file.
  sudo bash -c "set -a; . '$RUN/hr.env'; set +a
    cd '$APP/runner' && env -u HR_AUTH_USER -u HR_AUTH_PASSWORD -u HR_AUTH_STORE -u HR_SECRET_KEY \
      HR_SESSION_UIDS=1 nohup '$VENV/bin/python' -m uvicorn server:app --host 127.0.0.1 --port 8081 \
      --log-level warning > '$RUN/runner.log' 2>&1 & echo \$! > '$RUN/runner.pid'
    cd '$APP/gateway' && nohup setpriv --reuid=agent --regid=agent --init-groups sh -c 'umask 077; exec \"\$0\" -m uvicorn app:app --host 127.0.0.1 --port 8080 --log-level warning' '$VENV/bin/python' \
      > '$RUN/gateway.log' 2>&1 & echo \$! > '$RUN/gateway.pid'"
  for _ in $(seq 1 90); do curl -fsS http://127.0.0.1:8080/healthz >/dev/null 2>&1 && break; sleep 1; done
  sudo bash -c "set -a; . '$RUN/hr.env'; set +a
    export HR_SESSION_KEY=\"\$HR_AUTH_USER:\$HR_AUTH_PASSWORD\"
    cd '$APP/ui' && nohup setpriv --reuid=agent --regid=agent --init-groups sh -c 'umask 077; exec node server.js' \
      > '$RUN/console.log' 2>&1 & echo \$! > '$RUN/console.pid'"
  for _ in $(seq 1 90); do
    curl -fsS "http://127.0.0.1:$PORT/api/harness/v1/uhp" >/dev/null 2>&1 && { log "ready on 127.0.0.1:$PORT"; return 0; }
    sleep 1
  done
  log "not ready; see $RUN/*.log"; exit 1
}

stop() {
  pids=""
  for p in console gateway runner; do
    [ -f "$RUN/$p.pid" ] && pids="$pids $(sudo cat "$RUN/$p.pid")"
    sudo rm -f "$RUN/$p.pid"
  done
  # Also any listener on our ports, but only processes started from $ROOT (by PID).
  for port in 8080 8081 "$PORT"; do
    for pid in $(sudo lsof -t -iTCP:"$port" -sTCP:LISTEN -n -P 2>/dev/null); do
      sudo grep -q "$ROOT" "/proc/$pid/cmdline" 2>/dev/null && pids="$pids $pid"
    done
  done
  for pid in $pids; do sudo kill "$pid" 2>/dev/null || true; done
  # Gateway and console run as 'agent', a user this script created for them only. The sandbox's
  # root cannot signal another uid, so they are stopped as 'agent', by PID.
  for pid in $(ps -u agent -o pid= 2>/dev/null); do sudo -u agent kill "$pid" 2>/dev/null || true; done
  sudo rm -f "$RUN/hr.env" "$RUN/console-password"
  log "stopped"
}

status() {
  for p in runner gateway console; do
    if [ -f "$RUN/$p.pid" ] && sudo kill -0 "$(sudo cat "$RUN/$p.pid")" 2>/dev/null; then echo "$p running"; else echo "$p stopped"; fi
  done
}

case "${1:-}" in
  install) install ;;
  start) start "${2:?ENV_FILE}" ;;
  stop) stop ;;
  status) status ;;
  *) echo "usage: $0 install | start ENV_FILE | stop | status"; exit 64 ;;
esac

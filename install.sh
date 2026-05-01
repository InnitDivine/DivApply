#!/usr/bin/env bash
set -euo pipefail

dev=0
recreate=0
skip_jobspy=0
skip_browsers=0
skip_doctor=0
run_init=0
python_cmd="${DIVAPPLY_PYTHON:-}"
venv_dir=".venv"
browsers="chromium,firefox"

usage() {
  cat <<'EOF'
DivApply installer

Usage:
  ./install.sh [options]

Options:
  --dev                 Install editable development dependencies.
  --recreate            Delete and recreate the virtual environment.
  --skip-jobspy         Skip python-jobspy install.
  --skip-browsers       Skip Playwright browser downloads.
  --skip-doctor         Skip divapply doctor after install.
  --init                Run the interactive divapply init wizard.
  --python PATH         Python interpreter to use. Python 3.12 recommended; JobSpy needs 3.11 or 3.12.
                        Python 3.13/3.14 may fail with python-jobspy/numpy pins.
  --venv DIR            Virtual environment directory. Default: .venv
  --browsers LIST       Playwright browsers: chromium,firefox,webkit,all,none.
  -h, --help            Show this help.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --dev) dev=1 ;;
    --recreate) recreate=1 ;;
    --skip-jobspy) skip_jobspy=1 ;;
    --skip-browsers) skip_browsers=1 ;;
    --skip-doctor) skip_doctor=1 ;;
    --init) run_init=1 ;;
    --python) python_cmd="${2:?Missing value for --python}"; shift ;;
    --venv) venv_dir="${2:?Missing value for --venv}"; shift ;;
    --browsers) browsers="${2:?Missing value for --browsers}"; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown option: $1" >&2; usage; exit 2 ;;
  esac
  shift
done

step() {
  printf '\n==> %s\n' "$1"
}

warn() {
  printf 'WARN: %s\n' "$1" >&2
}

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$repo_root"

if [[ -z "$python_cmd" ]]; then
  if command -v python3 >/dev/null 2>&1; then
    python_cmd="python3"
  elif command -v python >/dev/null 2>&1; then
    python_cmd="python"
  else
    echo "No Python interpreter found. Install Python 3.11+ or set DIVAPPLY_PYTHON." >&2
    exit 1
  fi
fi

venv_python="$repo_root/$venv_dir/bin/python"

echo "DivApply installer"
echo "Repository: $repo_root"

if [[ "$recreate" -eq 1 && -d "$venv_dir" ]]; then
  step "Recreating virtual environment"
  rm -rf "$venv_dir"
fi

if [[ ! -x "$venv_python" ]]; then
  step "Creating virtual environment at $venv_dir"
  "$python_cmd" -m venv "$venv_dir"
fi

step "Checking Python version"
"$venv_python" -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 'DivApply requires Python 3.11+')"

if [[ "$skip_jobspy" -eq 0 ]]; then
  "$venv_python" -c "import sys; raise SystemExit(0 if (3, 11) <= sys.version_info[:2] < (3, 13) else 'Full JobSpy setup requires Python 3.11 or 3.12 because python-jobspy pins numpy==1.26.3. Use Python 3.12, set DIVAPPLY_PYTHON, pass --python, or rerun with --skip-jobspy.')"
fi

step "Upgrading pip"
"$venv_python" -m pip install --upgrade pip setuptools wheel

if [[ "$dev" -eq 1 ]]; then
  step "Installing DivApply in editable development mode"
  "$venv_python" -m pip install -e ".[dev,full]"
else
  step "Installing DivApply"
  "$venv_python" -m pip install ".[full]"
fi

if [[ "$skip_jobspy" -eq 0 ]]; then
  step "Installing python-jobspy"
  "$venv_python" -m pip install --no-deps python-jobspy
else
  warn "Skipped python-jobspy. Discovery will miss major job boards until you install it."
fi

resolve_browsers() {
  local spec="$1"
  local item
  IFS=',' read -ra parts <<<"$spec"
  for item in "${parts[@]}"; do
    item="$(echo "$item" | tr '[:upper:]' '[:lower:]' | xargs)"
    [[ -z "$item" ]] && continue
    case "$item" in
      none) return 0 ;;
      all) printf '%s\n' chromium firefox webkit; return 0 ;;
      chromium|firefox|webkit) printf '%s\n' "$item" ;;
      *) echo "Unsupported Playwright browser '$item'. Use chromium, firefox, webkit, all, or none." >&2; return 1 ;;
    esac
  done
}

if [[ "$skip_browsers" -eq 0 ]]; then
  mapfile -t browser_list < <(resolve_browsers "$browsers")
  if [[ "${#browser_list[@]}" -gt 0 ]]; then
    step "Installing Playwright browsers: ${browser_list[*]}"
    if ! "$venv_python" -m playwright install "${browser_list[@]}"; then
      warn "Playwright browser download failed. You can rerun: ./install.sh --browsers $browsers"
      warn "PDF export needs chromium. Auto-apply defaults to firefox."
    fi
  fi
fi

step "Preparing ~/.divapply"
"$venv_python" -c "from divapply.config import ensure_dirs; ensure_dirs()"
mkdir -p "$HOME/.divapply"
[[ -f ".env.example" && ! -f "$HOME/.divapply/.env" ]] && cp ".env.example" "$HOME/.divapply/.env"
[[ -f "profile.example.json" && ! -f "$HOME/.divapply/profile.example.json" ]] && cp "profile.example.json" "$HOME/.divapply/profile.example.json"
[[ -f "src/divapply/config/searches.example.yaml" && ! -f "$HOME/.divapply/searches.yaml" ]] && cp "src/divapply/config/searches.example.yaml" "$HOME/.divapply/searches.yaml"

if [[ "$run_init" -eq 1 ]]; then
  step "Running first-time setup wizard"
  "$venv_python" -m divapply init
fi

if [[ "$skip_doctor" -eq 0 ]]; then
  step "Running DivApply doctor"
  if ! "$venv_python" -m divapply doctor; then
    warn "Doctor reported setup issues. Read the output above, then rerun divapply doctor after fixing them."
  fi
fi

cat <<EOF

DivApply install complete.

Use it from this terminal with:
  source .venv/bin/activate
  divapply doctor

First-time setup:
  divapply init

For auto-apply, install Node.js 18+ plus Codex CLI or Claude Code, then rerun:
  divapply doctor
EOF

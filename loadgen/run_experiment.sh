#!/usr/bin/env bash
# Instance-side: start one experiment run in tmux, then return.
#
#   loadgen/run_experiment.sh PATTERN CONDITION MODE [MINUTES]
#
#   PATTERN    steady | spiky | seasonal
#   CONDITION  c1 | c2 | c3-layer2 | c3-layer23 (Layers 2 + 3)
#   MODE       traffic  (Locust only: use with c1, the reactive baseline)
#              dryrun   (Locust + controller deciding, Provisioned Concurrency untouched)
#              apply    (Locust + controller setting Provisioned Concurrency)
#   MINUTES    run length, default 155: ~63 min of history first, then 3 x 30-min cycles of
#              decisions (95 left only one ramp to compare conditions on, Run 2026-11-01-1)
#
# Optional env: USER_RPS (default 10), SEED (default 42), LOCUST_PROCESSES (default 2),
# plus any TrafficPatternShape
# setting (BASE_USERS, SPIKES_PER_HOUR, SEASON_PERIOD_S, ...).
#
# Writes data/raw/RUN.jsonl (+ Locust csv/html), results/controller/RUN.csv and
# data/raw/RUN.meta.json, then uploads data/raw and results to S3 when finished.
# Watch: tmux attach -t RUN    (detach: Ctrl-b d)
set -euo pipefail

usage() { sed -n '2,21p' "$0" | sed 's/^# \{0,1\}//'; exit 1; }
[ $# -ge 3 ] || usage
PATTERN="$1"; CONDITION="$2"; MODE="$3"; MINUTES="${4:-155}"

REPO="$HOME/prophet-serverless-scaling"
cd "$REPO"
export AWS_DEFAULT_REGION="${AWS_DEFAULT_REGION:-ap-south-1}"
: "${RESULTS_BUCKET:?RESULTS_BUCKET not set (run as ec2-user: sudo -iu ec2-user)}"
FUNCTION="sandbox-lambda"
USER_RPS="${USER_RPS:-10}"
# One Locust process tops out at ~880 req/s on c7i-flex.large (Run 2026-11-03-2); one per
# vCPU reaches the spiky design load (~1,100-1,340 req/s at spike peaks)
LOCUST_PROCESSES="${LOCUST_PROCESSES:-2}"
# Noise and drift from experiment_config.yaml (traffic_realism); env overrides still win
eval "$(venv/bin/python -m src.data_generation.traffic_env 2>/dev/null | sed 's/^export \([A-Z_]*\)=\(.*\)$/export \1="${\1:-\2}"/')"
SEED="${SEED:-42}"
RUN="$(date -u +%Y%m%d-%H%M)_${PATTERN}_${CONDITION}_${MODE}"
# First full minute of this run: the controller trains only on data from here on,
# never on an earlier session or the partial minute Locust starts in.
HISTORY_START="$(date -u -d '+1 minute' +%Y-%m-%dT%H:%M)"
COMMIT="$(git rev-parse --short HEAD)"

# --- Preflight -------------------------------------------------------------------
if [ -n "$(git status --porcelain --untracked-files=no)" ]; then
  echo "WARNING: uncommitted changes; the run will not match commit $COMMIT exactly."
fi
# A failed git pull once left a run on stale code (Run 2026-10-18-4)
if ! git fetch -q origin main 2>/dev/null; then
  echo "WARNING: could not reach origin; cannot check that $COMMIT is the latest commit."
elif [ "$(git rev-parse HEAD)" != "$(git rev-parse origin/main)" ]; then
  # Run outputs committed from the laptop clash with this instance's own untracked
  # copies (already in S3) and block the pull; move those aside, then fast-forward
  for f in $(git diff --name-only --diff-filter=A HEAD origin/main); do
    if [ -e "$f" ] && ! git ls-files --error-unmatch "$f" >/dev/null 2>&1; then
      mkdir -p "$HOME/stash" && mv "$f" "$HOME/stash/" && echo "Moved untracked $f to ~/stash"
    fi
  done
  git merge -q --ff-only origin/main || { echo "Cannot fast-forward $COMMIT to origin/main; fix by hand."; exit 1; }
  echo "Updated $COMMIT -> $(git rev-parse --short HEAD); restarting with the new code."
  exec "$0" "$@"
fi
# Checked after the self-update, so a condition added in a newer commit is known here
case "$PATTERN" in steady|spiky|seasonal) ;; *) usage ;; esac
case "$CONDITION/$MODE" in
  c1/traffic|c2/dryrun|c2/apply|c3-layer2/dryrun|c3-layer2/apply|c3-layer23/dryrun|c3-layer23/apply) ;;
  *) echo "Invalid CONDITION/MODE: $CONDITION/$MODE (c1 needs traffic; c2, c3-layer2 and c3-layer23 need dryrun or apply)"; exit 1 ;;
esac
if tmux has-session 2>/dev/null; then
  echo "A tmux session is already running (tmux ls). Finish or kill it first."; exit 1
fi
pc="$(aws lambda list-provisioned-concurrency-configs --function-name "$FUNCTION" \
  --query "ProvisionedConcurrencyConfigs" --output text)"
if [ -n "$pc" ]; then
  echo "Provisioned Concurrency is already allocated; every run must start from none:"
  echo "$pc"; exit 1
fi

# --- Start protocol: a fresh version, so no environment is warm ---------------------
# Environments belong to a version. Earlier traffic left them warm (0 start-up cold
# starts in Runs 2026-10-18-5 and 2026-10-29-5 against 20 in 2026-10-16-2), so the
# alias is moved to a newly published version and every run starts cold.
# Lambda publishes nothing new while $LATEST is unchanged, hence the description.
ALIAS="prod"
echo "Start protocol: publishing a fresh version of $FUNCTION ..."
aws lambda update-function-configuration --function-name "$FUNCTION" \
  --description "start protocol: $RUN" --output text --query LastUpdateStatus >/dev/null
aws lambda wait function-updated --function-name "$FUNCTION"
LAMBDA_VERSION="$(aws lambda publish-version --function-name "$FUNCTION" \
  --description "$RUN" --query Version --output text)"
aws lambda wait published-version-active --function-name "$FUNCTION" --qualifier "$LAMBDA_VERSION"
aws lambda update-alias --function-name "$FUNCTION" --name "$ALIAS" \
  --function-version "$LAMBDA_VERSION" --output text --query FunctionVersion >/dev/null
[ "$(aws lambda get-alias --function-name "$FUNCTION" --name "$ALIAS" --query FunctionVersion --output text)" \
  = "$LAMBDA_VERSION" ] || { echo "Alias $ALIAS did not move to version $LAMBDA_VERSION"; exit 1; }
echo "Alias $ALIAS -> version $LAMBDA_VERSION (no warm environments)."

mkdir -p data/raw results/controller
cat > "data/raw/$RUN.meta.json" <<EOF
{"run": "$RUN", "pattern": "$PATTERN", "condition": "$CONDITION", "mode": "$MODE",
 "minutes": $MINUTES, "user_rps": $USER_RPS, "seed": $SEED, "commit": "$COMMIT", "locust_processes": $LOCUST_PROCESSES,
 "lambda_version": "$LAMBDA_VERSION", "start_state": "fresh version (cold)",
 "noise_pct": $NOISE_PCT, "noise_interval_s": $NOISE_INTERVAL_S, "drift_pct": $DRIFT_PCT,
 "instance_type": "$(curl -s -H "X-aws-ec2-metadata-token: $(curl -s -X PUT http://169.254.169.254/latest/api/token -H 'X-aws-ec2-metadata-token-ttl-seconds: 60')" http://169.254.169.254/latest/meta-data/instance-type)",
 "started_utc": "$(date -u +%Y-%m-%dT%H:%M:%SZ)", "history_start_utc": "$HISTORY_START"}
EOF

# --- Launch ----------------------------------------------------------------------
SYNC="aws s3 sync data/raw s3://$RESULTS_BUCKET/data/raw --only-show-errors && aws s3 sync results s3://$RESULTS_BUCKET/results --only-show-errors && echo 'Uploaded to S3. Finished.'"
LOCUST="TRAFFIC_PATTERN=$PATTERN DURATION_S=$((MINUTES * 60)) SEED=$SEED USER_RPS=$USER_RPS \
  NOISE_PCT=$NOISE_PCT NOISE_INTERVAL_S=$NOISE_INTERVAL_S DRIFT_PCT=$DRIFT_PCT \
  SANDBOX_INVOKE_LOG=data/raw/$RUN.jsonl venv/bin/locust \
  -f src/data_generation/locust_scenarios/sandbox_locustfile_patterns.py --headless \
  --processes $LOCUST_PROCESSES --csv data/raw/$RUN --html data/raw/$RUN.html"

if [ "$MODE" = "traffic" ]; then
  tmux new-session -d -s "$RUN" -n locust -c "$REPO" "$LOCUST; $SYNC; exec bash"
else
  APPLY=""; [ "$MODE" = "apply" ] && APPLY="--apply"
  CONTROLLER="venv/bin/python -m src.controller.live_controller --condition $CONDITION \
    --pattern $PATTERN --minutes $MINUTES --run-name $RUN --history-start $HISTORY_START $APPLY"
  # The controller window uploads once both the controller and Locust have exited
  # Locust drops a marker when it exits (a pgrep on its command line would also
  # match this window's own shell, whose command text contains the same words)
  DONE="data/raw/$RUN.locust-done"
  tmux new-session -d -s "$RUN" -n locust -c "$REPO" "$LOCUST; touch $DONE; exec bash"
  tmux new-window -t "$RUN" -n controller -c "$REPO" \
    "$CONTROLLER; until [ -e $DONE ]; do sleep 10; done; rm -f $DONE; $SYNC; exec bash"
fi

# --- Early health check: stop everything if requests are failing -------------------
echo "Started $RUN (commit $COMMIT). Checking the first 60 s ..."
sleep 60
venv/bin/python - "data/raw/$RUN.jsonl" <<'EOF' || { tmux kill-session -t "$RUN"; echo "Aborted: see above."; exit 1; }
import json, sys
rows = [json.loads(l) for l in open(sys.argv[1])]
errors = [r["error"] for r in rows if r["error"]]
print(f"{len(rows)} requests in the first minute, {len(errors)} errors")
if not rows or len(errors) > 0.01 * len(rows):
    print("First error:", errors[0] if errors else "no requests logged")
    sys.exit(1)
EOF
echo "Healthy. Watch with: tmux attach -t $RUN   (detach: Ctrl-b d)"
echo "You can close the session and laptop; results upload to S3 when the run ends."

#!/usr/bin/env bash
# Instance-side: start one experiment run in tmux, then return.
#
#   loadgen/run_experiment.sh PATTERN CONDITION MODE [MINUTES]
#
#   PATTERN    steady | spiky | seasonal
#   CONDITION  c1 | c2 | c3-layer2
#   MODE       traffic  (Locust only: use with c1, the reactive baseline)
#              dryrun   (Locust + controller deciding, Provisioned Concurrency untouched)
#              apply    (Locust + controller setting Provisioned Concurrency)
#   MINUTES    run length, default 95 (controller needs ~63 min of history first)
#
# Optional env: USER_RPS (default 10), SEED (default 42), plus any TrafficPatternShape
# setting (BASE_USERS, SPIKES_PER_HOUR, SEASON_PERIOD_S, ...).
#
# Writes data/raw/RUN.jsonl (+ Locust csv/html), results/controller/RUN.csv and
# data/raw/RUN.meta.json, then uploads data/raw and results to S3 when finished.
# Watch: tmux attach -t RUN    (detach: Ctrl-b d)
set -euo pipefail

usage() { sed -n '2,19p' "$0" | sed 's/^# \{0,1\}//'; exit 1; }
[ $# -ge 3 ] || usage
PATTERN="$1"; CONDITION="$2"; MODE="$3"; MINUTES="${4:-95}"
case "$PATTERN" in steady|spiky|seasonal) ;; *) usage ;; esac
case "$CONDITION/$MODE" in
  c1/traffic|c2/dryrun|c2/apply|c3-layer2/dryrun|c3-layer2/apply) ;;
  *) echo "Invalid CONDITION/MODE: $CONDITION/$MODE (c1 needs traffic; c2 and c3-layer2 need dryrun or apply)"; exit 1 ;;
esac

REPO="$HOME/prophet-serverless-scaling"
cd "$REPO"
export AWS_DEFAULT_REGION="${AWS_DEFAULT_REGION:-ap-south-1}"
: "${RESULTS_BUCKET:?RESULTS_BUCKET not set (run as ec2-user: sudo -iu ec2-user)}"
FUNCTION="sandbox-lambda"
USER_RPS="${USER_RPS:-10}"
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
if tmux has-session 2>/dev/null; then
  echo "A tmux session is already running (tmux ls). Finish or kill it first."; exit 1
fi
pc="$(aws lambda list-provisioned-concurrency-configs --function-name "$FUNCTION" \
  --query "ProvisionedConcurrencyConfigs" --output text)"
if [ -n "$pc" ]; then
  echo "Provisioned Concurrency is already allocated; every run must start from none:"
  echo "$pc"; exit 1
fi

mkdir -p data/raw results/controller
cat > "data/raw/$RUN.meta.json" <<EOF
{"run": "$RUN", "pattern": "$PATTERN", "condition": "$CONDITION", "mode": "$MODE",
 "minutes": $MINUTES, "user_rps": $USER_RPS, "seed": $SEED, "commit": "$COMMIT",
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
  --csv data/raw/$RUN --html data/raw/$RUN.html"

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

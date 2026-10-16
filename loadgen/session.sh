#!/usr/bin/env bash
# Laptop-side helper for the loadgen instance. Run from anywhere in the repo.
#
#   loadgen/session.sh start     start the instance, wait until reachable, open a shell as ec2-user
#   loadgen/session.sh connect   open a shell as ec2-user (instance already running)
#   loadgen/session.sh status    instance state + any Provisioned Concurrency left allocated
#   loadgen/session.sh results   download run outputs from S3 into data/raw and results/
#   loadgen/session.sh stop      check PC is cleared, stop the instance, wait until stopped
set -euo pipefail

LOADGEN_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(dirname "$LOADGEN_DIR")"
REGION="ap-south-1"            # explicit: the laptop's CLI default region is not the project's
FUNCTION="sandbox-lambda"

ID="$(terraform -chdir="$LOADGEN_DIR" output -raw instance_id)"
BUCKET="$(terraform -chdir="$LOADGEN_DIR" output -raw results_bucket)"

state() {
  aws ec2 describe-instances --region "$REGION" --instance-ids "$ID" \
    --query "Reservations[].Instances[].State.Name" --output text
}

pc_configs() {
  aws lambda list-provisioned-concurrency-configs --region "$REGION" --function-name "$FUNCTION" \
    --query "ProvisionedConcurrencyConfigs[].[FunctionArn,AllocatedProvisionedConcurrentExecutions,Status]" \
    --output text
}

connect() {
  # Land directly in ec2-user's login shell (venv active, in the repo)
  aws ssm start-session --region "$REGION" --target "$ID" \
    --document-name AWS-StartInteractiveCommand --parameters command="sudo -iu ec2-user"
}

case "${1:-}" in
  start)
    aws ec2 start-instances --region "$REGION" --instance-ids "$ID" >/dev/null
    echo "Starting $ID ..."
    aws ec2 wait instance-running --region "$REGION" --instance-ids "$ID"
    echo "Running. Waiting for Session Manager ..."
    for _ in $(seq 1 36); do  # up to 3 minutes
      ping="$(aws ssm describe-instance-information --region "$REGION" \
        --filters "Key=InstanceIds,Values=$ID" --query "InstanceInformationList[0].PingStatus" --output text)"
      [ "$ping" = "Online" ] && break
      sleep 5
    done
    [ "$ping" = "Online" ] || { echo "Session Manager not online yet; try: $0 connect"; exit 1; }
    echo "Online. Remember: $0 stop when finished."
    connect
    ;;
  connect)
    connect
    ;;
  status)
    echo "Instance $ID: $(state)"
    configs="$(pc_configs)"
    echo "Provisioned Concurrency: ${configs:-none}"
    ;;
  results)
    aws s3 sync "s3://$BUCKET/data/raw" "$REPO_ROOT/data/raw" --region "$REGION"
    aws s3 sync "s3://$BUCKET/results" "$REPO_ROOT/results" --region "$REGION"
    ;;
  stop)
    configs="$(pc_configs)"
    if [ -n "$configs" ]; then
      echo "WARNING: Provisioned Concurrency still allocated (it bills until deleted):"
      echo "$configs"
      echo "Delete with: aws lambda delete-provisioned-concurrency-config --region $REGION --function-name $FUNCTION --qualifier prod"
    fi
    aws ec2 stop-instances --region "$REGION" --instance-ids "$ID" >/dev/null
    echo "Stopping $ID ..."
    aws ec2 wait instance-stopped --region "$REGION" --instance-ids "$ID"
    echo "Stopped."
    ;;
  *)
    sed -n '2,9p' "$0" | sed 's/^# \{0,1\}//'
    exit 1
    ;;
esac

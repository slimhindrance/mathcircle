#!/usr/bin/env bash
# Math Circle Home — teardown.
# Reads .deploy-state/state.json, then prompts before removing each resource.
# Leaves the S3 backup bucket intact unless --nuke-s3 is passed.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
STATE="$ROOT_DIR/.deploy-state/state.json"
NUKE_S3=false
for arg in "$@"; do
  [[ "$arg" == "--nuke-s3" ]] && NUKE_S3=true
done

[[ -f "$STATE" ]] || { echo "no state file at $STATE — nothing to tear down"; exit 0; }
command -v jq >/dev/null || { echo "jq not found"; exit 1; }

REGION=$(jq -r .region "$STATE")
INSTANCE=$(jq -r .instance_id "$STATE")
EIP=$(jq -r .eip "$STATE")
EIP_ALLOC=$(jq -r .eip_allocation_id "$STATE")
SG=$(jq -r .security_group_id "$STATE")
S3=$(jq -r .s3_bucket "$STATE")

confirm() { read -r -p "$1 [y/N] " a; [[ "$a" =~ ^[Yy]$ ]]; }

echo "Will tear down (region=$REGION):"
echo "  instance:       $INSTANCE"
echo "  EIP:            $EIP ($EIP_ALLOC)"
echo "  security group: $SG"
echo "  S3 bucket:      $S3 $([[ $NUKE_S3 == true ]] && echo '(WILL DELETE)' || echo '(kept)')"
confirm "Proceed?" || { echo aborted; exit 0; }

aws ec2 terminate-instances --region "$REGION" --instance-ids "$INSTANCE" >/dev/null
echo "→ terminating $INSTANCE (waiting…)"
aws ec2 wait instance-terminated --region "$REGION" --instance-ids "$INSTANCE"

aws ec2 disassociate-address --region "$REGION" --association-id \
  "$(aws ec2 describe-addresses --region "$REGION" --allocation-ids "$EIP_ALLOC" \
    --query 'Addresses[0].AssociationId' --output text)" 2>/dev/null || true
aws ec2 release-address --region "$REGION" --allocation-id "$EIP_ALLOC" || true
echo "→ released EIP"

aws ec2 delete-security-group --region "$REGION" --group-id "$SG" || true
echo "→ deleted SG"

if $NUKE_S3; then
  echo "→ emptying + deleting bucket $S3"
  aws s3 rm "s3://$S3" --recursive
  aws s3api delete-bucket --bucket "$S3" --region "$REGION"
fi

rm -f "$STATE"
echo "done."

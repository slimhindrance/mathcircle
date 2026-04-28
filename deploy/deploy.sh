#!/usr/bin/env bash
# Math Circle Home — one-shot AWS deployer.
#
# What this does, in order:
#   1. Verify aws CLI is installed and authenticated
#   2. Create the S3 backup bucket (if missing) with versioning + AES256
#   3. Create the IAM policy + instance role for S3 backups
#   4. Generate / reuse an SSH key pair (~/.ssh/mathcircle-key)
#   5. Create / reuse a security group (SSH from your IP, 80/443 open)
#   6. Allocate / reuse an Elastic IP
#   7. Bake the cloud-init from a template using your settings
#   8. Launch the t2.micro Ubuntu 24.04 instance with the cloud-init
#   9. Associate the EIP
#  10. Print the Vercel DNS record + waiting tips
#
# Re-running this script is safe — every step checks for existing resources first.
#
# Required env (set inline at the top, or export before running):
#   AWS_REGION         default: us-east-1
#   GIT_REPO_URL       e.g. https://github.com/base2ml/mathcircle.git
#   GIT_BRANCH         default: main
#   DOMAIN             e.g. mathcircle.base2ml.com
#   S3_BUCKET          default: base2ml-mathcircle-backups
#   ACME_EMAIL         e.g. christopherwlindeman@gmail.com
#   BASIC_AUTH_USER    default: family
#   BASIC_AUTH_PASS    plaintext, will be hashed locally
#
# Usage:
#   ./deploy/deploy.sh

set -euo pipefail

# ---------- defaults ----------
AWS_REGION="${AWS_REGION:-us-east-1}"
GIT_REPO_URL="${GIT_REPO_URL:-}"
GIT_BRANCH="${GIT_BRANCH:-main}"
DOMAIN="${DOMAIN:-mathcircle.base2ml.com}"
S3_BUCKET="${S3_BUCKET:-base2ml-mathcircle-backups}"
ACME_EMAIL="${ACME_EMAIL:-}"
BASIC_AUTH_USER="${BASIC_AUTH_USER:-family}"
BASIC_AUTH_PASS="${BASIC_AUTH_PASS:-}"

# Resource names (override if you want)
KEY_NAME="${KEY_NAME:-mathcircle-key}"
SG_NAME="${SG_NAME:-mathcircle-sg}"
ROLE_NAME="${ROLE_NAME:-MathCircleEC2Role}"
POLICY_NAME="${POLICY_NAME:-MathCircleBackupWrite}"
INSTANCE_TAG="${INSTANCE_TAG:-mathcircle-prod}"

# Project paths
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
KEY_PATH="$HOME/.ssh/${KEY_NAME}.pem"
STATE_DIR="$ROOT_DIR/.deploy-state"
mkdir -p "$STATE_DIR"

# ---------- helpers ----------
log()  { printf "\033[1;36m[deploy]\033[0m %s\n" "$*" >&2; }
warn() { printf "\033[1;33m[warn]\033[0m %s\n" "$*" >&2; }
die()  { printf "\033[1;31m[error]\033[0m %s\n" "$*" >&2; exit 1; }
have() { command -v "$1" >/dev/null 2>&1; }

prompt_required() {
  local var="$1"; local hint="$2"
  if [[ -z "${!var:-}" ]]; then
    printf "%s\n" "$hint" >&2
    read -r -p "$var: " value
    eval "$var=\"\$value\""
  fi
}

# ---------- 1. preflight ----------
log "preflight checks"
have aws    || die "aws CLI not found. Install with: brew install awscli"
have jq     || die "jq not found. Install with: brew install jq"
have docker || warn "docker not found — needed for hashing the password unless you have caddy installed locally"
have python3 || die "python3 not found"

aws sts get-caller-identity --output text >/dev/null 2>&1 \
  || die "aws CLI not authenticated. Run: aws configure"

ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
log "AWS account $ACCOUNT_ID, region $AWS_REGION"

prompt_required GIT_REPO_URL "Enter the GitHub HTTPS clone URL (e.g. https://github.com/base2ml/mathcircle.git)"
prompt_required ACME_EMAIL  "Enter the email Let's Encrypt should associate with the cert"
prompt_required BASIC_AUTH_PASS "Enter the household password (min 8 chars, will be bcrypt-hashed)"

# ---------- 2. S3 bucket ----------
log "ensuring S3 bucket s3://$S3_BUCKET"
if aws s3api head-bucket --bucket "$S3_BUCKET" >/dev/null 2>&1; then
  log "bucket exists"
else
  if [[ "$AWS_REGION" == "us-east-1" ]]; then
    aws s3api create-bucket --bucket "$S3_BUCKET" --region "$AWS_REGION" >/dev/null
  else
    aws s3api create-bucket --bucket "$S3_BUCKET" --region "$AWS_REGION" \
      --create-bucket-configuration LocationConstraint="$AWS_REGION" >/dev/null
  fi
  log "bucket created"
fi

aws s3api put-bucket-versioning --bucket "$S3_BUCKET" \
  --versioning-configuration Status=Enabled >/dev/null

aws s3api put-bucket-encryption --bucket "$S3_BUCKET" \
  --server-side-encryption-configuration \
  '{"Rules":[{"ApplyServerSideEncryptionByDefault":{"SSEAlgorithm":"AES256"}}]}' >/dev/null

aws s3api put-public-access-block --bucket "$S3_BUCKET" \
  --public-access-block-configuration \
  "BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true" >/dev/null

# ---------- 3. IAM ----------
log "ensuring IAM policy + role"

POLICY_DOC=$(cat <<JSON
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": ["s3:PutObject","s3:PutObjectAcl"],
      "Resource": "arn:aws:s3:::${S3_BUCKET}/mathcircle/*"
    },
    {
      "Effect": "Allow",
      "Action": "s3:ListBucket",
      "Resource": "arn:aws:s3:::${S3_BUCKET}",
      "Condition": {"StringLike": {"s3:prefix": "mathcircle/*"}}
    }
  ]
}
JSON
)
POLICY_ARN="arn:aws:iam::${ACCOUNT_ID}:policy/${POLICY_NAME}"
if ! aws iam get-policy --policy-arn "$POLICY_ARN" >/dev/null 2>&1; then
  aws iam create-policy --policy-name "$POLICY_NAME" \
    --policy-document "$POLICY_DOC" --description "Math Circle Home backup writer" >/dev/null
  log "created policy $POLICY_ARN"
else
  log "policy exists"
fi

TRUST_DOC='{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Principal":{"Service":"ec2.amazonaws.com"},"Action":"sts:AssumeRole"}]}'
if ! aws iam get-role --role-name "$ROLE_NAME" >/dev/null 2>&1; then
  aws iam create-role --role-name "$ROLE_NAME" \
    --assume-role-policy-document "$TRUST_DOC" >/dev/null
  log "created role $ROLE_NAME"
else
  log "role exists"
fi

aws iam attach-role-policy --role-name "$ROLE_NAME" --policy-arn "$POLICY_ARN" || true

# Instance profile (EC2 attaches to this, not the role directly)
if ! aws iam get-instance-profile --instance-profile-name "$ROLE_NAME" >/dev/null 2>&1; then
  aws iam create-instance-profile --instance-profile-name "$ROLE_NAME" >/dev/null
  aws iam add-role-to-instance-profile --instance-profile-name "$ROLE_NAME" --role-name "$ROLE_NAME"
  log "created instance profile (waiting 8s for IAM to propagate…)"
  sleep 8
fi

# ---------- 4. SSH key ----------
log "ensuring SSH key pair"
if [[ ! -f "$KEY_PATH" ]]; then
  if aws ec2 describe-key-pairs --key-names "$KEY_NAME" --region "$AWS_REGION" >/dev/null 2>&1; then
    die "Key pair '$KEY_NAME' exists in AWS but $KEY_PATH is missing locally. Either delete the AWS key (aws ec2 delete-key-pair --key-name $KEY_NAME --region $AWS_REGION) or set KEY_NAME to a different name."
  fi
  aws ec2 create-key-pair --region "$AWS_REGION" --key-name "$KEY_NAME" \
    --query 'KeyMaterial' --output text > "$KEY_PATH"
  chmod 600 "$KEY_PATH"
  log "created key at $KEY_PATH"
else
  log "key exists at $KEY_PATH"
fi

# ---------- 5. security group ----------
log "ensuring security group"
DEFAULT_VPC=$(aws ec2 describe-vpcs --region "$AWS_REGION" \
  --filters Name=isDefault,Values=true --query 'Vpcs[0].VpcId' --output text)
[[ "$DEFAULT_VPC" == "None" || -z "$DEFAULT_VPC" ]] && die "No default VPC in $AWS_REGION"

SG_ID=$(aws ec2 describe-security-groups --region "$AWS_REGION" \
  --filters "Name=group-name,Values=$SG_NAME" "Name=vpc-id,Values=$DEFAULT_VPC" \
  --query 'SecurityGroups[0].GroupId' --output text)

if [[ "$SG_ID" == "None" || -z "$SG_ID" ]]; then
  SG_ID=$(aws ec2 create-security-group --region "$AWS_REGION" \
    --group-name "$SG_NAME" --description "Math Circle Home" \
    --vpc-id "$DEFAULT_VPC" --query 'GroupId' --output text)
  log "created SG $SG_ID"
else
  log "SG exists: $SG_ID"
fi

MY_IP=$(curl -s https://checkip.amazonaws.com | tr -d '[:space:]')
[[ -z "$MY_IP" ]] && die "could not detect your public IP"
log "opening SSH from your IP: ${MY_IP}/32"

# Idempotent ingress rules — ignore "already exists"
aws ec2 authorize-security-group-ingress --region "$AWS_REGION" --group-id "$SG_ID" \
  --protocol tcp --port 22 --cidr "${MY_IP}/32" 2>/dev/null || true
aws ec2 authorize-security-group-ingress --region "$AWS_REGION" --group-id "$SG_ID" \
  --protocol tcp --port 80 --cidr 0.0.0.0/0 2>/dev/null || true
aws ec2 authorize-security-group-ingress --region "$AWS_REGION" --group-id "$SG_ID" \
  --protocol tcp --port 443 --cidr 0.0.0.0/0 2>/dev/null || true

# ---------- 6. Elastic IP ----------
log "ensuring Elastic IP"
EIP_ALLOC_ID=""
EIP_ADDRESS=""
EXISTING_EIP=$(aws ec2 describe-addresses --region "$AWS_REGION" \
  --filters "Name=tag:Name,Values=mathcircle-eip" \
  --query 'Addresses[0].AllocationId' --output text 2>/dev/null || echo None)

if [[ "$EXISTING_EIP" != "None" && -n "$EXISTING_EIP" ]]; then
  EIP_ALLOC_ID="$EXISTING_EIP"
  EIP_ADDRESS=$(aws ec2 describe-addresses --region "$AWS_REGION" \
    --allocation-ids "$EIP_ALLOC_ID" --query 'Addresses[0].PublicIp' --output text)
  log "EIP exists: $EIP_ADDRESS"
else
  EIP_JSON=$(aws ec2 allocate-address --region "$AWS_REGION" --domain vpc \
    --tag-specifications 'ResourceType=elastic-ip,Tags=[{Key=Name,Value=mathcircle-eip}]')
  EIP_ALLOC_ID=$(echo "$EIP_JSON" | jq -r '.AllocationId')
  EIP_ADDRESS=$(echo "$EIP_JSON" | jq -r '.PublicIp')
  log "allocated EIP: $EIP_ADDRESS"
fi

# ---------- 7. password hash + cloud-init ----------
log "hashing basic-auth password (bcrypt cost 14)"
HASH=""
# Prefer caddy if installed, else use python bcrypt (most reliable across machines).
if have caddy; then
  HASH=$(caddy hash-password --plaintext "$BASIC_AUTH_PASS")
fi
if [[ -z "$HASH" ]]; then
  if ! python3 -c "import bcrypt" >/dev/null 2>&1; then
    log "installing python bcrypt locally (one-time)"
    python3 -m pip install --quiet --user bcrypt 2>/dev/null \
      || python3 -m pip install --quiet --break-system-packages bcrypt 2>/dev/null \
      || python3 -m pip install --quiet bcrypt
  fi
  HASH=$(python3 - "$BASIC_AUTH_PASS" <<'PY'
import bcrypt, sys
print(bcrypt.hashpw(sys.argv[1].encode(), bcrypt.gensalt(14)).decode())
PY
)
fi
[[ -z "$HASH" ]] && die "failed to hash password"
log "hash ready"

log "rendering cloud-init"
RENDERED="$STATE_DIR/cloud-init.yaml"
# Use a heredoc-fed python so we don't have to worry about escaping `$` in the hash
python3 - "$SCRIPT_DIR/cloud-init.yaml" "$RENDERED" \
  "$GIT_REPO_URL" "$GIT_BRANCH" "$DOMAIN" "$S3_BUCKET" "$ACME_EMAIL" \
  "$BASIC_AUTH_USER" "$HASH" <<'PY'
import pathlib, sys
src = pathlib.Path(sys.argv[1]).read_text()
out = sys.argv[2]
git_url, branch, domain, bucket, email, user, h = sys.argv[3:10]
sub = {
    "__GIT_REPO_URL__": git_url,
    "__GIT_BRANCH__":   branch,
    "__DOMAIN__":       domain,
    "__S3_BUCKET__":    bucket,
    "__ACME_EMAIL__":   email,
    "__BASIC_AUTH_USER__": user,
    "__BASIC_AUTH_HASH__": h,
}
for k, v in sub.items():
    src = src.replace(k, v)
pathlib.Path(out).write_text(src)
PY
log "cloud-init at $RENDERED"

# ---------- 8. AMI lookup ----------
log "looking up latest Ubuntu 24.04 AMI"
AMI_ID=$(aws ec2 describe-images --region "$AWS_REGION" \
  --owners 099720109477 \
  --filters "Name=name,Values=ubuntu/images/hvm-ssd-gp3/ubuntu-noble-24.04-amd64-server-*" \
            "Name=state,Values=available" \
  --query 'sort_by(Images, &CreationDate) | [-1].ImageId' --output text)
[[ -z "$AMI_ID" || "$AMI_ID" == "None" ]] && die "no Ubuntu 24.04 AMI found"
log "AMI: $AMI_ID"

# ---------- 9. launch instance ----------
EXISTING_INSTANCE=$(aws ec2 describe-instances --region "$AWS_REGION" \
  --filters "Name=tag:Name,Values=$INSTANCE_TAG" \
            "Name=instance-state-name,Values=pending,running,stopped,stopping" \
  --query 'Reservations[].Instances[0].InstanceId' --output text 2>/dev/null || echo "")

INSTANCE_ID=""
if [[ -n "$EXISTING_INSTANCE" && "$EXISTING_INSTANCE" != "None" ]]; then
  INSTANCE_ID="$EXISTING_INSTANCE"
  log "reusing instance $INSTANCE_ID (skipping launch)"
else
  log "launching t2.micro instance"
  INSTANCE_ID=$(aws ec2 run-instances --region "$AWS_REGION" \
    --image-id "$AMI_ID" \
    --instance-type t2.micro \
    --key-name "$KEY_NAME" \
    --security-group-ids "$SG_ID" \
    --iam-instance-profile "Name=$ROLE_NAME" \
    --block-device-mappings '[{"DeviceName":"/dev/sda1","Ebs":{"VolumeSize":30,"VolumeType":"gp3","DeleteOnTermination":true}}]' \
    --user-data "file://$RENDERED" \
    --tag-specifications "ResourceType=instance,Tags=[{Key=Name,Value=$INSTANCE_TAG}]" \
    --metadata-options "HttpTokens=required,HttpEndpoint=enabled" \
    --query 'Instances[0].InstanceId' --output text)
  log "launched $INSTANCE_ID — waiting for it to enter running state"
  aws ec2 wait instance-running --region "$AWS_REGION" --instance-ids "$INSTANCE_ID"
fi

# ---------- 10. associate EIP ----------
log "associating EIP $EIP_ADDRESS with instance"
aws ec2 associate-address --region "$AWS_REGION" \
  --instance-id "$INSTANCE_ID" --allocation-id "$EIP_ALLOC_ID" >/dev/null

# ---------- 11. write state ----------
cat > "$STATE_DIR/state.json" <<JSON
{
  "region": "$AWS_REGION",
  "instance_id": "$INSTANCE_ID",
  "eip": "$EIP_ADDRESS",
  "eip_allocation_id": "$EIP_ALLOC_ID",
  "security_group_id": "$SG_ID",
  "domain": "$DOMAIN",
  "s3_bucket": "$S3_BUCKET",
  "ssh_key_path": "$KEY_PATH",
  "basic_auth_user": "$BASIC_AUTH_USER",
  "deployed_at": "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
}
JSON

# ---------- final instructions ----------
cat <<EOF

────────────────────────────────────────────────────────────────────────
✓ AWS provisioning complete.

Next steps (manual):

1. Add this DNS record in Vercel for base2ml.com:
       Type:   A
       Name:   ${DOMAIN%.base2ml.com}
       Value:  $EIP_ADDRESS
       TTL:    60

2. Wait ~3–5 min for cloud-init to finish on the box.
   Watch progress with:
       ssh -i $KEY_PATH ubuntu@$EIP_ADDRESS 'sudo cloud-init status --wait'

3. Once DNS propagates and Caddy fetches the cert (another minute), open:
       https://$DOMAIN
   Login:  $BASIC_AUTH_USER / [the password you provided]

4. Verify the backup pipeline:
       ssh -i $KEY_PATH ubuntu@$EIP_ADDRESS 'sudo /opt/mathcircle/bin/backup.sh && \
            tail /opt/mathcircle/logs/backup.log'
       aws s3 ls s3://$S3_BUCKET/mathcircle/

State saved to: $STATE_DIR/state.json
SSH key:        $KEY_PATH
EIP:            $EIP_ADDRESS  (don't STOP the instance — EIP becomes paid)
────────────────────────────────────────────────────────────────────────
EOF

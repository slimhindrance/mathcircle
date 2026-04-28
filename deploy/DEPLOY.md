# Deploying Math Circle Home to EC2

Target: `https://mathcircle.base2ml.com` on a free-tier `t2.micro` in `us-east-1`,
DNS managed in Vercel, TLS via Caddy + Let's Encrypt, basic-auth gate, nightly
SQLite backups to S3.

End-to-end first-time setup is ~30 minutes.

---

## 0. One-time prerequisites

- AWS account in good standing (less than 12 months old → t2.micro free tier is active)
- A GitHub repo containing this code (we'll call it `base2ml/mathcircle`)
- Access to Vercel DNS for `base2ml.com`
- Local SSH key pair (or generate one in step 2)

---

## 1. Push the code to GitHub

```bash
cd /path/to/mathhound
git init -b main      # if not already a repo
git remote add origin git@github.com:base2ml/mathcircle.git
git add .
git commit -m "Initial Math Circle Home"
git push -u origin main
```

> The cloud-init script clones the repo on first boot, so the repo must be
> public — **or** we'd swap to a deploy-key flow. Public is fine if you don't
> mind the seed bank being visible. (No secrets are checked in.)

---

## 2. Create the S3 backup bucket

In the AWS console (or CLI):

```bash
aws s3api create-bucket \
  --bucket base2ml-mathcircle-backups \
  --region us-east-1
aws s3api put-bucket-versioning \
  --bucket base2ml-mathcircle-backups \
  --versioning-configuration Status=Enabled
aws s3api put-bucket-encryption \
  --bucket base2ml-mathcircle-backups \
  --server-side-encryption-configuration \
    '{"Rules":[{"ApplyServerSideEncryptionByDefault":{"SSEAlgorithm":"AES256"}}]}'
```

**Lifecycle (optional but recommended)** — drop daily snapshots to Glacier
after 30 days, delete after 365:

```bash
aws s3api put-bucket-lifecycle-configuration \
  --bucket base2ml-mathcircle-backups \
  --lifecycle-configuration file://deploy/s3-lifecycle.json
```

(Skip this if you don't want to deal with lifecycle yet — costs a few cents/yr regardless.)

---

## 3. Create the IAM role for the EC2 instance

1. IAM → Policies → **Create policy** → JSON → paste `deploy/iam-s3-policy.json`
   → name it `MathCircleBackupWrite`.
2. IAM → Roles → **Create role** → trusted entity = EC2 → attach
   `MathCircleBackupWrite` → name it `MathCircleEC2Role`.

---

## 4. Generate the basic-auth password hash

You need a bcrypt hash for the household password. Easiest way:

**Option A — local Docker (fastest):**
```bash
docker run --rm caddy:2 caddy hash-password --plaintext 'YourFamilyPassword'
```

**Option B — install Caddy locally** (`brew install caddy`) and run the same.

**Option C** — paste a bcrypt hash from any bcrypt generator (`htpasswd -nbB family 'YourPass'` and take the part after `family:`).

Save the resulting hash like `$2a$14$...`. You'll paste it into cloud-init in step 6.

---

## 5. Add the Vercel DNS record (do this BEFORE step 7 so Let's Encrypt can resolve)

Wait — actually, **add the record AFTER you have the EC2 EIP** (step 7). Skip
ahead, then come back here.

When you have the EIP, in Vercel:

- Project Settings → Domains → `base2ml.com` → DNS Records → Add Record
- Type: `A`
- Name: `mathcircle`
- Value: `<your-EIP>`
- TTL: 60 (so you can iterate fast on first setup)

---

## 6. Prepare the cloud-init file

Copy `deploy/cloud-init.yaml` to a working file and fill in placeholders:

```bash
cp deploy/cloud-init.yaml /tmp/mathcircle-cloud-init.yaml
sed -i '' \
  -e 's|__GIT_REPO_URL__|https://github.com/base2ml/mathcircle.git|g' \
  -e 's|__GIT_BRANCH__|main|g' \
  -e 's|__DOMAIN__|mathcircle.base2ml.com|g' \
  -e 's|__S3_BUCKET__|base2ml-mathcircle-backups|g' \
  -e 's|__ACME_EMAIL__|christopherwlindeman@gmail.com|g' \
  /tmp/mathcircle-cloud-init.yaml
```

Then **manually** edit `/tmp/mathcircle-cloud-init.yaml` and replace
`__BASIC_AUTH_HASH__` with the hash from step 4. (We use a manual edit here
because bcrypt hashes contain `$` and `/` characters that fight `sed`.)

---

## 7. Launch the EC2 instance

In the AWS console: EC2 → Launch instance.

| Field | Value |
| --- | --- |
| Name | `mathcircle-prod` |
| AMI | Ubuntu Server 24.04 LTS (HVM), SSD, 64-bit (x86) |
| Instance type | **t2.micro** (free tier eligible — has the badge) |
| Key pair | create or pick an existing one (`mathcircle-key`) |
| VPC | default |
| Auto-assign public IP | enable (you'll replace with EIP next) |
| Security group | create new — `mathcircle-sg`, allow `22` from My IP, `80` and `443` from `0.0.0.0/0` |
| Storage | 30 GB gp3 (free-tier maximum) |
| IAM instance profile | `MathCircleEC2Role` |
| User data | paste the contents of `/tmp/mathcircle-cloud-init.yaml` |

Click Launch.

While it's spinning up:

- EC2 → Elastic IPs → **Allocate Elastic IP address** → Allocate
- Select the new EIP → Actions → **Associate** → pick the `mathcircle-prod` instance

Now go back to step 5 and add the Vercel DNS record pointing `mathcircle.base2ml.com` → that EIP.

---

## 8. Wait for cloud-init to finish, then verify

Cloud-init takes ~3–5 minutes. SSH in:

```bash
ssh -i ~/.ssh/mathcircle-key.pem ubuntu@<EIP>
```

Check status:

```bash
sudo cloud-init status --wait
sudo systemctl status mathcircle    # should be "active (running)"
sudo systemctl status caddy         # should be "active (running)"
sudo journalctl -u mathcircle -f    # look for "seeded — added=209"
sudo tail /var/log/caddy/mathcircle.log
```

Once DNS has propagated (1–5 min), Caddy will request a Let's Encrypt cert
automatically. Watch:

```bash
sudo journalctl -u caddy -f
# look for "certificate obtained successfully"
```

Visit `https://mathcircle.base2ml.com` — you should see the basic-auth prompt.
Enter `family` / your password.

---

## 9. Smoke test

```bash
curl -I -u family:YOURPASS https://mathcircle.base2ml.com/
# expect: HTTP/2 200

curl -u family:YOURPASS https://mathcircle.base2ml.com/api/strands | jq length
# expect: 10

curl -u family:YOURPASS https://mathcircle.base2ml.com/api/problems?limit=500 | jq length
# expect: 209
```

---

## 10. Trigger a manual backup to confirm S3 is wired

```bash
sudo -u root /opt/mathcircle/bin/backup.sh
aws s3 ls s3://base2ml-mathcircle-backups/mathcircle/
# expect: a recent .db.gz file
tail /opt/mathcircle/logs/backup.log
```

Cron will run nightly at 03:17 UTC from then on.

---

## 11. Set up auto-deploy (optional)

In the GitHub repo settings → Secrets and variables → Actions → add:

- `EC2_HOST` = `mathcircle.base2ml.com`
- `EC2_USER` = `ubuntu`
- `EC2_SSH_KEY` = contents of your `.pem` file

Then add the `ubuntu` user to a sudoers entry that allows running deploy.sh
without a password:

```bash
echo 'ubuntu ALL=(ALL) NOPASSWD: /opt/mathcircle/bin/deploy.sh' | \
  sudo tee /etc/sudoers.d/mathcircle-deploy
```

`.github/workflows/deploy.yml` will now redeploy on every push to `main`.

---

## Troubleshooting

**Caddy stuck getting a cert.** DNS hasn't propagated yet, or port 80 is
blocked. `dig mathcircle.base2ml.com A` should return your EIP. `curl
http://<EIP>/` should hit Caddy (it serves an ACME challenge response, then
redirects to https).

**Service won't start.** `sudo journalctl -u mathcircle -n 100 --no-pager`.
Most common issue: SQLite path permissions. Ensure
`/opt/mathcircle/data` is owned by `mathcircle:mathcircle`.

**Ran out of memory during pip install.** t2.micro has 1 GB RAM. Add a 1 GB swap file:
```bash
sudo fallocate -l 1G /swapfile && sudo chmod 600 /swapfile && \
sudo mkswap /swapfile && sudo swapon /swapfile && \
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
```

**Forgot the basic-auth password.** Generate a new hash, edit
`/etc/caddy/Caddyfile`, then `sudo systemctl reload caddy`.

**Need to restore from S3.**
```bash
aws s3 cp s3://base2ml-mathcircle-backups/mathcircle/<filename>.db.gz /tmp/
gunzip /tmp/<filename>.db.gz
sudo systemctl stop mathcircle
sudo cp /tmp/<filename>.db /opt/mathcircle/data/mathcircle.db
sudo chown mathcircle:mathcircle /opt/mathcircle/data/mathcircle.db
sudo systemctl start mathcircle
```

---

## Cost watch

- t2.micro: free for 12 months, then ~$8.50/mo
- 30 GB gp3: free for 12 months, then ~$2.40/mo
- Elastic IP: $0 while attached, $3.60/mo if detached → **don't stop the instance**
- S3 (Standard-IA + lifecycle): pennies/month
- Data transfer out: 100 GB/mo free, this app uses ≪1 GB
- **Total: $0 for 12 months, then ~$11/mo**

Set a billing alarm at $5 to catch surprises:

```bash
aws cloudwatch put-metric-alarm \
  --alarm-name mathcircle-billing \
  --alarm-description "Bill > $5" \
  --metric-name EstimatedCharges \
  --namespace AWS/Billing \
  --statistic Maximum \
  --period 21600 \
  --threshold 5 \
  --comparison-operator GreaterThanThreshold \
  --dimensions Name=Currency,Value=USD \
  --evaluation-periods 1 \
  --region us-east-1
```

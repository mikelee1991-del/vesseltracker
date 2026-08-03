# aisstream free-tier VM collector

Always-on logger for live SoCal AIS via [aisstream.io](https://aisstream.io/).
Writes fleet-filtered daily parquet under `/var/lib/aisstream/ais_daily/`.

Expected volume: on the order of **~0.1–0.5 MB/day** after filtering (~40–90 MB/year), matching the Cadastre fleet extract scale.

---

## What you do (manual)

### 1. Free aisstream API key
1. Open https://aisstream.io/ and sign in with GitHub.
2. Create an API key.
3. Copy it somewhere safe (you’ll paste it on the VM).

### 2. Free-tier VM (Oracle Cloud recommended)
Oracle’s Always Free ARM VM is the most generous “actually free” option.

1. Sign up: https://www.oracle.com/cloud/free/
2. In the Oracle console → **Compute → Instances → Create instance**
   - **Image:** Canonical Ubuntu 22.04 or 24.04
   - **Shape:** `VM.Standard.A1.Flex` (Ampere ARM), 1–2 OCPU, 6–12 GB RAM is plenty
   - **Networking:** assign a public IP
   - **SSH keys:** paste your public key (`~/.ssh/id_ed25519.pub` or create one with `ssh-keygen`)
3. Note the public IP.
4. Open **egress** is enough (default). You do **not** need to open inbound ports beyond SSH (22).

**Alternative:** Google Cloud free `e2-micro` (Ubuntu) — tighter CPU/network; same install steps below.

### 3. SSH in and paste the key
From your laptop:

```bash
ssh -i ~/.ssh/id_ed25519 ubuntu@YOUR_VM_PUBLIC_IP
```

(Oracle Ubuntu images often use user `ubuntu`.)

Then run the install commands in **What I set up for you** below. When `install.sh` finishes the first time, edit the env file:

```bash
sudo nano /etc/aisstream.env
# set: AISSTREAM_API_KEY=your_key_here
sudo systemctl enable --now aisstream-collector
sudo journalctl -u aisstream-collector -f
```

You should see `subscribed` then occasional `flushed N rows` / `heartbeat` lines.

### 4. Confirm data is landing

```bash
sudo ls -lh /var/lib/aisstream/ais_daily/
```

After a busy fishing morning you should see `ais_YYYY-MM-DD.parquet` files growing.

### 5. (Optional) Pull data back to your laptop / this repo

```bash
# on laptop
mkdir -p data/processed/ais_daily
rsync -avz -e ssh ubuntu@YOUR_VM_PUBLIC_IP:/var/lib/aisstream/ais_daily/ data/processed/ais_daily/
```

Then run the normal stop/map pipeline locally against those parquet files.

---

## What the install script does for you

On the VM (after SSH):

```bash
sudo apt-get update -y && sudo apt-get install -y git
git clone https://github.com/mikelee1991-del/vesseltracker.git
cd vesseltracker
sudo bash deploy/aisstream/install.sh
```

That will:
- create system user `aisstream`
- clone/update the repo under `/opt/vesseltracker`
- create a Python venv with `pandas` / `pyarrow` / `websockets`
- install systemd unit `aisstream-collector`
- create `/etc/aisstream.env` from the example (first run only)
- write parquet under `/var/lib/aisstream/ais_daily/`

Useful commands:

```bash
sudo systemctl status aisstream-collector
sudo journalctl -u aisstream-collector -f
sudo systemctl restart aisstream-collector
```

Update code later:

```bash
cd /opt/vesseltracker && sudo git pull && sudo bash deploy/aisstream/install.sh
```

---

## Notes / gotchas

- **Missed hours are gone** — aisstream has no history API. Keep the service `enabled` and check it weekly.
- Free-tier VMs can be **reclaimed** if the account looks abandoned — log in to the cloud console occasionally.
- The collector filters to our SoCal bbox + allowlisted / name-matched sportfishing boats (`deploy/aisstream/accepted_names.json`). Regenerate after boat-name changes: `python3 scripts/export_accepted_names.py`.
- Disk use is tiny vs Cadastre bulk CSVs; a 50 GB free boot volume is more than enough for years of fleet parquet.

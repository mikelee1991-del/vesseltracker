# aisstream free-tier VM collector — setup checklist

Always-on logger for live SoCal AIS via [aisstream.io](https://aisstream.io/).
Writes fleet-filtered daily parquet under `/var/lib/aisstream/ais_daily/`.

**Expected volume:** ~0.1–0.5 MB/day after filtering (~40–90 MB/year).

**Paused reason (2026-08-03):** Oracle `VM.Standard.A1.Flex` was **out of capacity** in
`us-sanjose-1` AD-1. Resume when capacity returns, or use the E2.1.Micro fallback below.

---

## Status / context

| Item | Value |
|------|--------|
| Goal | Continuous forward AIS archive until Marine Cadastre `csv2026` appears |
| Collector | `scripts/collect_aisstream.py` (`--hours 0` = forever) |
| Deploy package | this directory (`install.sh`, systemd unit, `accepted_names.json`) |
| Cloud | Oracle Always Free (preferred); GCP free `e2-micro` also works |
| Region attempted | US West (San Jose) `us-sanjose-1` |
| Blocker | `Out of capacity for shape VM.Standard.A1.Flex in availability domain AD-1` |

Why not Workers / GitHub Actions: aisstream is a **persistent outbound WebSocket**; missed
hours are gone forever. Needs an always-on host with disk.

---

## Prerequisites (do once, anytime)

### A. aisstream API key
1. https://aisstream.io/ → sign in with GitHub  
2. Create an API key → save it for `/etc/aisstream.env` later  

### B. SSH key on your laptop (if you don’t have one)
```bash
ssh-keygen -t ed25519 -C "oci-aisstream"
# public key to paste/upload: ~/.ssh/id_ed25519.pub
```

### C. Oracle account
https://www.oracle.com/cloud/free/ — Free Tier is fine.

---

## Step-by-step: create the VM (when capacity is available)

Do **Part 1 (VCN) before Part 2 (instance)**. A missing VCN is why public IP stays locked.

### Part 1 — Create VCN with internet (required first)

1. ☰ → **Networking** → **Virtual cloud networks**
2. **Start VCN Wizard** → **Create VCN with Internet Connectivity** → **Start VCN Wizard**
3. Fields:

| Field | Value |
|--------|--------|
| VCN name | `vcn-aisstream` |
| Compartment | `mikelee1991 (root)` (or your root compartment) |
| VCN CIDR | leave `10.0.0.0/16` |
| Public subnet CIDR | leave `10.0.0.0/24` |
| Private subnet CIDR | leave `10.0.1.0/24` |
| Everything else | defaults |

4. **Next** → **Create** → wait → **View VCN**
5. Confirm you see:
   - subnet named like **`public subnet-…`**
   - subnet named like **`private subnet-…`**
   - an **Internet Gateway**

### Part 2 — Create compute instance

Open: Compute → Instances → **Create instance**  
(Example URL pattern: `https://cloud.oracle.com/compute/instances/create?region=us-sanjose-1`)

#### Step 1 — Basic information

| Field | Value |
|--------|--------|
| **Name** | `aisstream-collector` |
| **Create in compartment** | your root compartment |
| **Availability domain** | AD 1 (or another AD if A1 capacity is only elsewhere) |
| **Fault domain** | leave unset / Oracle chooses (helps with capacity errors) |
| **Capacity type** | **On-demand capacity** only |
| Do **not** use | Preemptible, Capacity reservation, Dedicated host, Compute cluster |
| **Image** | **Canonical Ubuntu 24.04 Minimal aarch64** (for A1 Ampere) |
| **Shape** | **VM.Standard.A1.Flex** — Always Free-eligible |
| **OCPUs / memory** | **1 OCPU**, **6 GB** (enough) |
| **Boot volume** | defaults |
| **IMDS / cloud-init / tags / live migration / Cloud Agent** | leave defaults |
| **Initialization script** | leave empty |

**If A1 is still out of capacity** (error: *Out of capacity for shape VM.Standard.A1.Flex…*):

| Fallback | Value |
|----------|--------|
| Image | **Canonical Ubuntu 24.04 Minimal** (**not** aarch64) |
| Shape | **VM.Standard.E2.1.Micro** (Always Free AMD) |

Also try: clear fault domain, retry later, or try another Always Free region if your tenancy allows (e.g. Chicago / Ashburn).

#### Step 2 — Security

| Field | Value |
|--------|--------|
| **Shielded instance** | **Off** |
| **Confidential computing** | **Off** (if shown) |
| **Security attributes (ZPR)** | none — do not add |

SSH keys are **not** on this page.

#### Step 3 — Networking

| Field | Value |
|--------|--------|
| **VNIC name** | blank |
| **Primary network** | **Select existing virtual cloud network** |
| **Virtual cloud network** | `vcn-aisstream` |
| **Subnet** | **Select existing subnet** |
| **Subnet name** | **`public subnet-…` only** — never `private subnet-…` |
| **Automatically assign private IPv4** | On |
| **Automatically assign public IPv4 address** | **On** |
| **IPv6** | Off |
| **NSGs** | none |

**Public IP warning:**  
`You must select a public subnet to assign a public IPv4 address.`  
→ You selected a **private** subnet, or no VCN/subnet yet. Pick **`public subnet-…`** from Part 1.

**Add SSH keys** (scroll down on this same Networking step):

| Option | When to use |
|--------|-------------|
| **Generate a key pair for me** | Easiest — then **Download private key** immediately and keep it safe |
| **Paste public keys** | Paste `~/.ssh/id_ed25519.pub` |
| **Upload public key files (.pub)** | Upload that `.pub` file |
| **No SSH keys** | Do **not** choose |

#### Step 4 — Review → Create

Confirm: Ubuntu image, shape, **public** subnet, public IPv4 on, SSH key present → **Create**.

Wait until state is **Running**. Copy **Public IP** from the instance details page.

---

## Step-by-step: install the collector on the VM

### 1. SSH in

If you pasted your own key:
```bash
ssh ubuntu@PUBLIC_IP
```

If Oracle generated the key:
```bash
chmod 600 ~/Downloads/ssh-key-XXXX.key
ssh -i ~/Downloads/ssh-key-XXXX.key ubuntu@PUBLIC_IP
```

If SSH times out: VCN **Security List** ingress must allow TCP **22** from your IP (or `0.0.0.0/0` temporarily).

### 2. Install

```bash
sudo apt-get update -y && sudo apt-get install -y git
git clone -b cursor/aisstream-vm-deploy-6672 https://github.com/mikelee1991-del/vesseltracker.git
cd vesseltracker
sudo bash deploy/aisstream/install.sh
```

After this branch is merged to `main`, you can clone `main` instead.

### 3. Put the API key in place

```bash
sudo nano /etc/aisstream.env
# AISSTREAM_API_KEY=your_key_here
sudo systemctl enable --now aisstream-collector
sudo journalctl -u aisstream-collector -f
```

Expect: `subscribed`, then `flushed N rows` / `heartbeat`.

### 4. Confirm parquet

```bash
sudo systemctl status aisstream-collector
sudo ls -lh /var/lib/aisstream/ais_daily/
```

### 5. Optional — pull data to your laptop / this repo

```bash
mkdir -p data/processed/ais_daily
rsync -avz -e 'ssh -i YOUR_KEY' ubuntu@PUBLIC_IP:/var/lib/aisstream/ais_daily/ data/processed/ais_daily/
```

Then run the normal stop / map pipeline locally.

---

## What `install.sh` configures for you

- System user `aisstream`
- Repo at `/opt/vesseltracker`
- venv with `pandas`, `pyarrow`, `websockets`
- systemd unit `aisstream-collector` (restart on failure, forever mode)
- Env file `/etc/aisstream.env`
- Data dir `/var/lib/aisstream/ais_daily/`
- Boat name filter from `deploy/aisstream/accepted_names.json` (no need to copy the full fish-report archive)

Useful later:
```bash
sudo systemctl status aisstream-collector
sudo journalctl -u aisstream-collector -f
sudo systemctl restart aisstream-collector
cd /opt/vesseltracker && sudo git pull && sudo bash deploy/aisstream/install.sh
```

Regenerate accepted names after boat-list changes (on a machine with fish-report data):
```bash
python3 scripts/export_accepted_names.py
```

---

## Troubleshooting cheatsheet

| Symptom | Fix |
|---------|-----|
| Public IPv4 greyed out / “must select a public subnet” | No VCN yet, or subnet is **private**. Create VCN wizard first; select **`public subnet-…`**. |
| SSH keys not in Basic or Security | They’re on **Networking → Add SSH keys** (scroll down). |
| Out of capacity A1.Flex AD-1 | Clear fault domain; retry; try other AD/region; or use **E2.1.Micro** + non-aarch64 Ubuntu. |
| SSH timeout | Security list: ingress TCP 22; confirm **Public IP** on instance. |
| Service won’t start / REPLACE_ME | Set `AISSTREAM_API_KEY` in `/etc/aisstream.env`. |
| No rows kept | Stream up but no matched boats yet; check bbox/allowlist; wait for vessels underway. |

---

## Ongoing care

- Missed hours are **gone** (no aisstream history API) — keep `aisstream-collector` enabled.
- Log into the Oracle console occasionally so the free-tier account isn’t marked abandoned.
- Prefer Cadastre `csv2026` over aisstream for those days once NOAA publishes it.

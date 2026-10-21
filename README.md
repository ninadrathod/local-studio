# The Local Studio

Upload an image, send it to the API, and get a blurred copy back.

## Requirements

- Python 3.12+ (3.14 works with the pinned dependencies)
- A modern browser (Chrome, Firefox, Safari, or Edge)

## Quick start (scripts)

1. Clone the repository:

```bash
git clone https://github.com/ninadrathod/local-studio.git
cd local-studio
```

2. Set up the project (creates `backend/.venv`, installs API + helper deps, downloads the rembg `u2net` model into `~/.rembg/`, prepares the Real-ESRGAN upscale model in `~/.local-studio/models/`, and creates the local preset database `backend/database/presets.local.db`, which `run.sh` also refreshes on every start):

```bash
./scripts/setup.sh
```

3. Run the API and frontend:

```bash
./scripts/run.sh
```

4. Open [http://localhost:5500](http://localhost:5500), pick a preset, upload an image, and click **Generate edit**.

The servers run in the background (they keep running after you close the terminal); logs are in `logs/api.log` and `logs/frontend.log`. Stop both with:

```bash
./scripts/stop.sh
```

To pull the latest code and restart the app in one step:

```bash
./scripts/update.sh
```

If `./scripts/run.sh` reports a broken virtualenv or a port already in use, re-run `./scripts/setup.sh` (it recreates a relocated/broken `backend/.venv`) and run `./scripts/stop.sh` (the API always uses port 8000; only the frontend port can be changed, with `FRONTEND_PORT=…`).

<details>
<summary><strong>Setup on server / Raspberry Pi</strong></summary>

Assumes a running 64-bit Linux (e.g. Raspberry Pi OS 64-bit) with Python 3.12+ (`python3 --version`), network access, and ideally 4 GB+ RAM.

1. Install system packages:

```bash
sudo apt update && sudo apt install -y git python3-venv lsof curl
```

2. Clone your fork over HTTPS (so scheduled `git pull` needs no password):

```bash
cd ~ && git clone https://github.com/<your-username>/local-studio.git && cd local-studio
```

3. Low-RAM devices (2 GB or less) only — add a 3 GB swap file, or the subject-cutout presets (they need ~2–3 GB) get killed mid-edit. With swap they work, just slowly (minutes per edit):

```bash
sudo fallocate -l 3G /swapfile && sudo chmod 600 /swapfile
sudo mkswap /swapfile && sudo swapon /swapfile
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
free -h   # "Swap:" should now show ~3G (more if the OS already had swap)
```

4. Set up and start:

```bash
./scripts/setup.sh
./scripts/run.sh
```

5. Open the app from any device on your network:

```bash
echo "http://$(hostname).local:5500"   # or by IP: hostname -I
```

If a firewall is enabled, open both ports (the page calls the API on 8000):

```bash
sudo ufw allow 5500,8000/tcp
```

6. Schedule auto-update (pull + restart) daily at 00:00 and on every boot (run once; re-running adds duplicate entries):

```bash
( crontab -l 2>/dev/null
  echo "0 0 * * * $HOME/local-studio/scripts/update.sh >> $HOME/local-studio-update.log 2>&1"
  echo "@reboot sleep 30 && $HOME/local-studio/scripts/update.sh >> $HOME/local-studio-update.log 2>&1"
) | crontab -
```

Check it with `crontab -l` and `tail ~/local-studio-update.log`. Midnight uses the system timezone (`timedatectl`; change with `sudo timedatectl set-timezone <Region/City>`). To remove the schedule, delete those two lines with `crontab -e`.

</details>

## Run tests

Service-function unit tests (not HTTP/API) live in `test-suite/` and run on PRs via GitHub Actions.

```bash
source backend/.venv/bin/activate
pip install -r test-suite/requirements.txt
pytest test-suite/ -v
```

## Optional: subject extraction helper

Setup already installs helper deps and pulls the `u2net` model. To run:

```bash
source backend/.venv/bin/activate
python backend/helpers/extract_subject.py path/to/photo.jpg -o subject.png
```

Model weights live in `~/.rembg/` (rembg) and `~/.local-studio/models/` (Real-ESRGAN for the HD presets), outside the repo; `*.onnx` is gitignored.

## Optional: JSON presets

Presets are JSON step lists in `backend/presets/`.

```bash
source backend/.venv/bin/activate
python backend/helpers/apply_preset.py path/to/photo.jpg -p bw_bg_glowing_subject -o out.png
```

# The Local Studio

A local photo studio: pick a preset, upload a photo, get the edit back — all on your machine.

## Prerequisites

- [Docker Desktop](https://docs.docker.com/get-docker/) (includes Docker Compose v2) — keep it running
- [Git](https://git-scm.com/downloads)
- A modern browser (Chrome, Firefox, Safari, or Edge)

Python, packages and AI models are not needed on your machine — they are built into the containers.

## Setup

```bash
git clone https://github.com/ninadrathod/local-studio.git
cd local-studio
cp .env.example .env    # optional: LIGHTWEIGHT=1 for low-RAM machines, FRONTEND_PORT to change the port
```

## Run

```bash
docker compose up -d --build
```

Open [http://localhost:5500](http://localhost:5500). The first build downloads packages and models (~250 MB) and takes a few minutes; later starts take seconds.

## Stop

```bash
docker compose down
```

Preset download counts are kept. To update after a `git pull`, run `docker compose up -d --build` again.

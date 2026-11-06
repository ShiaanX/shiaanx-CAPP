# Dev deploy of 2026-11-05 (about 22:50 IST): what changed and how to undo it

Deployed to dev.shiaanx.com from the local working tree (branches `demo/investor-nov`, uncommitted) with
`bash shiaanx-backend-flow/deploy/dev-env/scripts/deploy.sh`. Backend, capp and nginx(+frontend) were rebuilt
and recreated. db, qc and certbot were not touched.

## What is new on dev
- Part-analysis (capp) service now ships the demo modules, the saved v3 analyses (Motor Mount, Rekise,
  Heat Sink D1) and the Motor Mount / Rekise data pack. `V3_DISABLED=1`: no v3 / PowerMill on the server,
  so only saved analyses work; any other STEP shows "not available on this environment".
- nginx route `/capp/` -> capp:8001, behind the same sx_session cookie check as /inspection (401 without login).
- Frontend built with `REACT_APP_CAPP_API_URL=/capp`; the "Open v3 console" button only shows on localhost.
- `GEMINI_API_KEY` is read from the server's `dev-env/.env` (NOT set by the deploy; the founder adds it by hand).

## Rollback (server)
Source backup: `/opt/shiaanx-dev-rollback-20261105-2245.tar.gz` (root-only; contains the old `.env`).
Previous image IDs: nginx b4918775f18f, qc 96592dda274f, capp 8dee8e895416, backend 701b35106547
(see `dev_server_state_before_deploy.txt`; they stay on the server as untagged images until pruned).

Fast rollback to the old images (source restore first, so compose and nginx files match):
```
ssh -i ~/.ssh/shiaanx-dev.pem ubuntu@65.2.120.75
sudo tar xzf /opt/shiaanx-dev-rollback-20261105-2245.tar.gz -C /opt
docker tag b4918775f18f shiaanx-dev/nginx:local
docker tag 8dee8e895416 shiaanx-dev/capp:local
docker tag 701b35106547 shiaanx-dev/backend:local
cd /opt/shiaanx-dev/dev-env && docker compose up -d --no-build
```
Do not run `docker image prune -a` on the server until you are sure you will not roll back.

## Add the Gemini key (client-feedback drafts), from Git Bash on the laptop
```
printf 'GEMINI_API_KEY=%s\n' "$GEMINI_API_KEY" | ssh -i ~/.ssh/shiaanx-dev.pem ubuntu@65.2.120.75 'cat >> /opt/shiaanx-dev/dev-env/.env && cd /opt/shiaanx-dev/dev-env && docker compose up -d capp'
```

## Refreshing the saved analyses later (e.g. RIB1 when it finishes)
New analyses are produced on the planning workstation (cached under `capp_service/demo_data/v3_cache`, then
indexed in `index.json`) and reach dev with the next deploy, because they live inside the capp image.

# Deploying CartPilot

This guide takes the code on this branch to three free services:

1. **Database:** Neon Postgres (or Supabase)
2. **Agent API:** Hugging Face Spaces, Docker SDK (or Render)
3. **Website:** Vercel

Allow about 30–45 minutes. Do the steps in order, because each step needs the URL from the one before it.

You will need:

- the group's Claude API key (it starts with `sk-ant-`)
- free accounts on neon.tech, huggingface.co and vercel.com
- `git`, and Python 3.10+ for the final checks

> Never paste the API key into code, the README or a commit. It goes only into the hosting
> platform's secret settings.

---

## 1. Create the database (Neon)

1. Go to <https://neon.tech>, sign in and click **New project**. Any name works, for example
   `cartpilot`. Pick the region closest to the API host (AWS `eu-central-1` or `us-east-1` both work).
2. On the project dashboard, click **Connect**. Keep **Connection pooling** on and copy the
   connection string. It looks like:

   ```text
   postgresql://neondb_owner:XXXX@ep-something-pooler.eu-central-1.aws.neon.tech/neondb?sslmode=require
   ```

3. Save it; this is `DATABASE_URL`. You don't need to create any tables: the API creates its tables,
   the LangGraph memory tables and the demo catalogue on first start.

**Supabase instead of Neon:** create a project, open **Connect**, and copy the **Session pooler**
string (port 5432). It works over IPv4, which Hugging Face Spaces needs. Replace `[YOUR-PASSWORD]`
with the database password you set when you created the project.

---

## 2. Deploy the agent API (Hugging Face Spaces)

### 2.1 Create the Space

1. Go to <https://huggingface.co/new-space>.
2. **Space name:** `cartpilot-api`. **License:** MIT. **SDK:** Docker, **Blank** template.
   **Hardware:** CPU basic (free). **Visibility:** Public, so the grader can reach it.
3. Click **Create Space**.

### 2.2 Add the secrets

In the Space, open **Settings → Variables and secrets** and add these. Use **New secret** for the
private values and **New variable** for the rest.

| Name | Type | Value |
|---|---|---|
| `DATABASE_URL` | secret | the connection string from step 1 |
| `ANTHROPIC_API_KEY` | secret | the group's Claude key |
| `ADMIN_PASSWORD` | secret | a password for the admin dashboard (share it with the team) |
| `SECRET_KEY` | secret | any long random string, for example from `python -c "import secrets; print(secrets.token_urlsafe(32))"` |
| `LLM_PROVIDER` | variable | `anthropic` |
| `CLAUDE_MODEL` | variable | `claude-haiku-5-5` |
| `CORS_ORIGINS` | variable | `*` for now (step 4 tightens it) |

### 2.3 Push the code

From the root of this repository:

```bash
# Use a Hugging Face access token with "write" scope as the password when git asks
# (create one at https://huggingface.co/settings/tokens).
git clone https://huggingface.co/spaces/<HF_USERNAME>/cartpilot-api ../cartpilot-space
cp -r Dockerfile .dockerignore backend ../cartpilot-space/
cp deploy/huggingface/README.md ../cartpilot-space/README.md
cd ../cartpilot-space
rm -rf backend/tests backend/.env
git add . && git commit -m "Deploy CartPilot API" && git push
```

The Space starts building (watch the **Logs** tab). The first build takes 3–5 minutes. When the
log shows `CartPilot ready (LLM provider: anthropic)`, the API is up.

### 2.4 Check it

Your API base URL is `https://<HF_USERNAME>-cartpilot-api.hf.space`. You can also find it under
**⋯ → Embed this Space → Direct URL**.

```bash
API=https://<HF_USERNAME>-cartpilot-api.hf.space
curl $API/health                    # -> ok
curl $API/health/ready              # -> {"status":"ok","database":true,"llm_provider":"anthropic"}
curl -X POST $API/chat -H 'Content-Type: application/json' \
  -d '{"user_id":"deploy-check","thread_id":"t1","message":"What is your return policy?"}'
```

The last call should return a reply that mentions 7-day returns, with `get_store_policy` in
`tool_calls` and non-zero `tokens`.

**If something fails:**

| Symptom | Fix |
|---|---|
| Build log shows `Could not initialise database` | `DATABASE_URL` is wrong, or you used a direct (IPv6) Supabase string. Use the pooled/Session pooler string. |
| `/chat` replies "Sorry, I'm having trouble…" | Check the Space logs. `authentication_error` means the `ANTHROPIC_API_KEY` secret is wrong; `credit balance`/`spend limit` means the key's $2 limit has been reached. |
| `llm_provider` is not `anthropic` | Set the `LLM_PROVIDER` variable to `anthropic` and restart the Space. |

After changing a secret, click **Settings → Restart this Space**.

### Alternative: Render

Render's free plan also works but sleeps after 15 minutes without traffic, so the first request
after a pause takes about a minute. If you use it: **New → Blueprint**, select this repository, and
Render reads `render.yaml`. Fill in the secret values when prompted.

---

## 3. Deploy the website (Vercel)

1. Go to <https://vercel.com/new> and import the GitHub repository. If the work is still on a
   branch, merge it first or choose that branch under **Git → Production Branch** after import.
2. **Root Directory:** click **Edit** and choose `frontend`. Vercel detects **Vite**.
3. **Environment Variables:** add `VITE_API_URL` = your API base URL from step 2.4, with no trailing
   slash.
4. Click **Deploy**. Your site URL looks like `https://cartpilot-xyz.vercel.app`.

Check that:

- the catalogue loads on the home page (this proves the site reaches the API)
- **Chat with CartPilot** answers a question
- `https://<your-site>/admin` accepts the `ADMIN_PASSWORD`
- signing in as `ali` / `demo1234` shows saved preferences and orders on **My account**

If the catalogue shows "Can't reach the CartPilot server", `VITE_API_URL` is wrong or missing.
Fix it in **Settings → Environment Variables**, then **Deployments → ⋯ → Redeploy**, because Vite
reads the variable at build time.

---

## 4. Lock down and finish

1. **CORS (optional):** in the Space, set `CORS_ORIGINS` to your Vercel URL (for example
   `https://cartpilot-xyz.vercel.app`), then restart. The grader calls `/chat` from a server, so CORS
   doesn't affect grading.
2. **Keep it awake until evaluation is over:** free Spaces sleep after 48 hours without traffic.
   Add a free monitor at <https://uptimerobot.com> (or cron-job.org) that requests
   `https://<HF_USERNAME>-cartpilot-api.hf.space/health` every 30 minutes. Keep the website and API
   running until Wednesday 25 November.
3. **Run the benchmark against the live API.** It uses about 25 Claude calls, roughly $0.01:

   ```bash
   python scripts/benchmark.py --base-url $API --label "claude-haiku-5-5 on Hugging Face Spaces" --update-readme
   ```

   This writes the results into the README's benchmark table and `docs/benchmark.md`. Commit both.
4. **Record the demo GIF against the live site (optional, it already has one).** Needs
   `pip install playwright` and Chrome:

   ```bash
   python scripts/record_demo.py --site https://<your-site> --admin-password <ADMIN_PASSWORD>
   ```

5. **Fill in the links** at the top of `README.md`: website, API base URL and demo video. Commit and
   push.

## Cost notes

- Each chat turn costs about $0.0003–0.0006 with Haiku 5.5 and prompt caching. The $2 limit covers
  several thousand turns, so the grader's run is fine.
- Avoid load-testing `/chat` against the real key. Blocked (unsafe or off-topic) messages cost
  nothing.
- The admin **Overview** shows tokens used and an estimated cost.

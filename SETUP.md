# Setup: auto-posting for @samsonsatprep

What this does: every hour, a free GitHub Actions job checks `posts/` and publishes any carousel or image whose `publish_at` time has passed to Instagram and TikTok. Reels and stories are skipped so you can post them by hand with trending audio.

About 45–60 minutes, one time. Do the steps in order.

> **Before you start:** Meta and TikTok developer accounts may require you to be 18. If either one blocks you, a parent can create the developer account and app, then add @samsonsatprep as the account it posts to. Nothing else changes.

---

## 1. GitHub repo + hosting (10 min)

1. Create a **public** repo named `samsonsatprep-autopost`. It has to be public for free GitHub Pages; your secrets stay private.
2. Push this folder to it. On your Mac, in Terminal:
   ```bash
   cd ~/Downloads/samsonsatprep-autopost      # wherever you unzipped it
   git init && git add . && git commit -m "autopost setup"
   git branch -M main
   git remote add origin https://github.com/YOUR_USERNAME/samsonsatprep-autopost.git
   git push -u origin main
   ```
   (Dragging files into GitHub's website skips the hidden `.github` folder, so use Terminal or GitHub Desktop.)
3. Repo → **Settings → Pages** → Source: *Deploy from a branch* → `main` / `(root)` → Save.
   After a minute your site is live at `https://YOUR_USERNAME.github.io/samsonsatprep-autopost`
4. Repo → **Settings → Secrets and variables → Actions → Variables** tab → New variable
   `PUBLIC_BASE_URL` = `https://YOUR_USERNAME.github.io/samsonsatprep-autopost` (no trailing slash)
5. Open `privacy.html` and `terms.html`, replace `CONTACT_EMAIL` with a contact email, and push again.

## 2. GitHub token for auto-renewing logins (3 min)

Tokens expire, and the bot renews them itself, but it needs permission to save the new ones.

1. GitHub → Settings → Developer settings → **Fine-grained tokens** → Generate new token
2. Repository access: only `samsonsatprep-autopost`. Permissions: **Secrets → Read and write**. Expiration: 1 year
3. Copy it → repo **Settings → Secrets → Actions → New repository secret**: `GH_PAT`

## 3. Instagram (15 min)

1. In the Instagram app on @samsonsatprep: Settings → *Account type and tools* → **Switch to professional account → Creator**.
2. Go to **developers.facebook.com** → log in → My Apps → **Create app**.
   Pick the use case for managing Instagram content/messaging; if asked for an app type, choose **Business**.
3. In the app dashboard, open **Instagram → API setup with Instagram login**.
4. Under *Generate access tokens*, click **Add account** and log in as @samsonsatprep.
   If Instagram shows a tester invite, accept it: Instagram → Settings → *Apps and websites* → *Tester invites*.
5. Click **Generate token** next to the account and copy it.
6. Make sure the permissions include `instagram_business_basic` and `instagram_business_content_publish`.
7. Get your IG user ID (the dashboard often shows it next to the account). If not:
   ```bash
   pip3 install requests
   IG_ACCESS_TOKEN=paste_token_here python3 tools/ig_whoami.py
   ```
8. Add repo secrets: `IG_ACCESS_TOKEN` and `IG_USER_ID`.

The app can stay in **development mode**. It only posts to your own account, which has a role on the app.

## 4. TikTok (20 min)

1. Go to **developers.tiktok.com** → log in → **Manage apps → Connect an app**.
2. Fill in the app details:
   - Name: `Samson SAT Prep Publisher` · Category: Education · Platform: **Web**
   - Website URL: your `PUBLIC_BASE_URL`
   - Terms of Service URL: `PUBLIC_BASE_URL/terms.html`
   - Privacy Policy URL: `PUBLIC_BASE_URL/privacy.html`
3. **Add products:**
   - **Login Kit** → Redirect URI: `PUBLIC_BASE_URL/callback.html`
   - **Content Posting API** → turn on **Direct Post**
   - Scopes: `user.info.basic`, `video.publish`, `video.upload`
4. **Verify your image URL.** Under URL properties, add a **URL prefix**: `PUBLIC_BASE_URL/`.
   TikTok gives you a small verification file. Put it in the root of this repo, push, wait a minute, then click Verify.
5. Switch to **Sandbox** and add @samsonsatprep as a **target user**. This lets you test before TikTok reviews the app.
6. Copy the **Client key** and **Client secret** → repo secrets `TIKTOK_CLIENT_KEY` and `TIKTOK_CLIENT_SECRET`.
7. Log in once to get a refresh token. On your Mac:
   ```bash
   export TIKTOK_CLIENT_KEY=...  TIKTOK_CLIENT_SECRET=...
   export PUBLIC_BASE_URL=https://YOUR_USERNAME.github.io/samsonsatprep-autopost
   python3 tools/tiktok_auth.py
   ```
   Open the link, approve as @samsonsatprep, paste the code from the page you land on.
   Save the printed value as the repo secret `TIKTOK_REFRESH_TOKEN`.

**Public posting:** until TikTok reviews and audits the app, every auto-post is **private** (only you can see it). When you're ready, submit the app for review from the developer portal, then apply for the Content Posting API audit. They ask for a short screen recording of how the app works. After approval, the bot switches to public automatically, with no code changes.

## 5. Test it (5 min)

1. Repo → **Actions** → enable workflows if asked.
2. **autopost → Run workflow** with *Dry run* checked. The log should list what it would post.
3. For a real test, set a post's `publish_at` to a few minutes ago, push, and run it with *Dry run* unchecked.
   Check Instagram (public) and TikTok (private for now).
4. Posted items get logged in `state/posted.json`, so nothing double-posts.

---

## Day to day

- New post = a folder in `posts/` with JPEG slides and a `post.json`. `tools/make_post.py` builds it from PNG slides.
- `python3 -m autopost.runner --check` validates every post before you push.
- Times use your timezone offset, e.g. `2026-10-12T16:00:00-05:00` is 4pm Central (use `-06:00` after Nov 1 when daylight saving ends).
- Posts go out at the first hourly run after their time (within ~1 hour; GitHub sometimes runs a few minutes late).
- Instagram renews its token every Monday automatically (`refresh-ig-token` workflow).
- Reels/stories: keep them in `posts/` with `"type": "reel"` as a to-do list. The bot ignores them, and you post them by hand with a trending sound.

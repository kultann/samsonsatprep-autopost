# Setup: auto-posting for @samsonsatprep

What this does: every hour, a free GitHub Actions job checks `posts/` and publishes anything whose `publish_at` time has passed: carousels and images to Instagram and TikTok, and short videos (`"type": "short"`) to Instagram Reels, TikTok and YouTube Shorts. Posts marked `reel` or `story` are skipped so you can post them by hand with trending audio.

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

## 5. Shorts on Instagram + TikTok (nothing to set up)

Shorts use the same Instagram and TikTok logins as your carousels. Instagram pulls the MP4 from GitHub Pages; TikTok gets the file uploaded directly. TikTok shorts carry the "AI-generated" label by default (`"ai_label": true`) because the narration is TTS; set it to `false` if you ever use your own voice.

## 6. Shorts on YouTube (15 min, optional)

> Google Cloud may require you to be 18. If it blocks you, a parent can create the project and the OAuth client; you still log in as the channel in step 8. Make the @samsonsatprep YouTube channel first.

1. **console.cloud.google.com** → sign in with the Google account that owns the channel → create a project (e.g. `samsonsatprep-publisher`).
2. **APIs & Services → Library** → **YouTube Data API v3** → Enable.
3. **Google Auth Platform** (search it in the top bar) → **Get started**: app name, support email, Audience **External**, contact email → Create.
4. **Data Access → Add or remove scopes** → add `.../auth/youtube.upload` and `.../auth/youtube.readonly` → Save.
5. **Audience → Publish app** (status **In production**). Don't skip this: in *Testing* mode Google expires the login after 7 days. You don't need Google's verification for a personal tool; you'll just see an "unverified app" warning when you log in.
6. **Clients → Create client → Desktop app**. Copy the client ID and secret → repo secrets `YT_CLIENT_ID` and `YT_CLIENT_SECRET`.
7. On your Mac:
   ```bash
   cd ~/Desktop/SAT/samsonsatprep-autopost
   pip3 install requests
   export YT_CLIENT_ID=...  YT_CLIENT_SECRET=...
   python3 tools/youtube_auth.py
   ```
8. In the browser: pick your account, choose the **@samsonsatprep channel**, then **Advanced → Go to (app name) → Allow**. Save the printed value as the repo secret `YT_REFRESH_TOKEN`.
9. Run **check-connections**. It should show `YouTube channel` with your channel name.
10. Apply for the audit: **YouTube API Services – Audit and Quota Extension Form** (https://support.google.com/youtube/contact/yt_api_form). Describe it as a single-channel tool that uploads your own Shorts to your own channel.

**Public uploads:** Google locks videos uploaded by *unverified* API projects to **private**. Until the audit passes, auto-posted Shorts land as private videos. Until then, leave `youtube` out of each short's `platforms` and upload Shorts in YouTube Studio instead (Studio has its own free scheduler).

## 6b. Shorts media repo (10 min, needed for the 1000 shorts)

1000 shorts are ~6–10 GB of video, and a GitHub Pages site maxes out at 1 GB (this repo's `posts/` is already ~550 MB). So the shorts live in a second public repo whose only job is serving videos. Its own daily workflow deletes each video 48 h after it's live everywhere.

1. GitHub Desktop → **File → Add Local Repository** → choose `~/Desktop/SAT/samsonsatprep-media` → it offers to **create a repository** there → Create → **Publish repository**, name `samsonsatprep-media`, **uncheck "Keep this code private"** (free Pages needs public).
2. On github.com, that repo → **Settings → Pages** → *Deploy from a branch* → `main` / `(root)` → Save.
3. In **this** repo (samsonsatprep-autopost) → **Settings → Secrets and variables → Actions → Variables** → New variable
   `MEDIA_BASE_URL` = `https://kultann.github.io/samsonsatprep-media`
4. Run **check-connections**: you should see `Media repo index` OK.

Each week: Claude Code renders the next week of shorts into `samsonsatprep-media/shorts/<post_id>/` (video.mp4, cover.jpg, post.json) and runs `python3 tools/build_index.py`; you commit + push that repo in GitHub Desktop. That's it. When the media repo passes ~3 GB of history, delete it on GitHub and re-create it with the same name.

## 7. Test it (5 min)

1. Repo → **Actions** → enable workflows if asked.
2. **autopost → Run workflow** with *Dry run* checked. The log should list what it would post.
3. For a real test, set a post's `publish_at` to a few minutes ago, push, and run it with *Dry run* unchecked.
   Check Instagram (public) and TikTok (private for now).
4. Posted items get logged in `state/posted.json`, so nothing double-posts.

---

## 8. Long-form YouTube videos (20 min + uploading time)

The bot uploads each long video from `longform/<id>/` (post.json + thumbnail + captions). The MP4s are too big for the repo (GitHub's 100 MB limit), so they live in a **release** named `longform` (2 GB per file, no total limit). Nothing uploads until you turn it on, because videos uploaded before the YouTube API audit passes are locked private for good.

1. **Verify the channel** (once): YouTube Studio → Settings → Channel → Feature eligibility → verify with your phone. Needed for videos over 15 minutes and for custom thumbnails.
2. **Upload the MP4s to the release**: on GitHub, open the repo → **Releases** → **Draft a new release** → **Choose a tag** → type `longform` → **Create new tag** → title `Long-form videos` → drag in every file from `~/Desktop/SAT/youtube/_upload_to_github_release/` → **Publish release** (not "Save draft": draft files can't be downloaded). Keep the file names exactly as they are.
3. **Optional test now** (checks download, upload and thumbnail end to end): repo → Settings → Secrets and variables → Actions → **Variables** → New variable `YT_LONGFORM` = `test`. The next run uploads the first video once as a private `[TEST]` video (the Actions log says `TEST uploaded ...`). Look at it in Studio, delete it, then set `YT_LONGFORM` back to `0`.
4. **When the audit passes**: re-date the videos from the next good day, push, then turn it on:
   ```bash
   cd ~/Desktop/SAT/samsonsatprep-autopost
   python3 tools/schedule_longform.py --start 2026-11-01     # Sun/Tue/Thu at 4:00 PM Central
   python3 -m autopost.runner --check
   ```
   Commit + push, then set the variable `YT_LONGFORM` = `1`.

**How it posts:** each video uploads 24 hours before its `publish_at` as a scheduled video (`LONGFORM_UPLOAD_LEAD_HOURS`), so YouTube finishes HD processing and makes it public right on time. You get an ntfy push with a Studio link: add the B thumbnail there (Test & Compare) before it goes live. Two long videos never go live less than 40 hours apart (`LONGFORM_MIN_GAP_HOURS`), so a stale schedule drips out instead of dumping, and at most one uploads per run.

- **Date-specific videos** (03 "before November 7", 07 "before December 5") have `expires_at`: if they can't go live in time, the bot holds them instead (log: `HOLD`). The scheduler puts them about 2 weeks before their test.
- **Uploaded one by hand?** Add `"manual": true` to its `longform/<id>/post.json` so the bot skips it.
- **New videos later:** render into `~/Desktop/SAT/youtube/<NN_slug>/`, run `python3 tools/make_longform.py --only NN`, attach `final/<NN_slug>.mp4` to the `longform` release (Releases → Edit), then `python3 tools/schedule_longform.py --start <date>`.
- **Captions:** off by default (YouTube makes automatic ones). Uploading the `.srt` files needs the `youtube.force-ssl` scope: add it to `SCOPES` in `tools/youtube_auth.py` and to the Google Auth Platform data access list, log in again, update `YT_REFRESH_TOKEN`, then set the variable `YT_CAPTIONS` = `1`.
- The results go in `state/posted.json` under each `long-...` id (`youtube`: video id, upload time, publish time).

## Day to day

- New post = a folder in `posts/` with JPEG slides and a `post.json`. `tools/make_post.py` builds it from PNG slides.
- `python3 -m autopost.runner --check` validates every post before you push.
- Times use your timezone offset, e.g. `2026-10-12T16:00:00-05:00` is 4pm Central (use `-06:00` after Nov 1 when daylight saving ends).
- Posts go out at the first hourly run after their time (within ~1 hour; GitHub sometimes runs a few minutes late).
- Instagram renews its token every Monday automatically (`refresh-ig-token` workflow).
- Reels/stories: keep them in `posts/` with `"type": "reel"` as a to-do list. The bot ignores them, and you post them by hand with a trending sound.
- **Shorts** (auto-posted video): a folder with `video.mp4` (1080×1920, under 3 min), optional `cover.jpg`, and a `post.json` like this. `tools/make_short.py` writes it for you.
  ```json
  {
    "id": "2026-10-13_desmos-systems",
    "publish_at": "2026-10-13T17:00:00-05:00",
    "type": "short",
    "video": "video.mp4",
    "cover": "cover.jpg",
    "cover_time_ms": 500,
    "platforms": ["instagram", "tiktok", "youtube"],
    "caption": "Instagram caption (hashtags get added from the list)",
    "tiktok_caption": "optional, defaults to caption",
    "hashtags_instagram": ["#SAT", "#SATmath", "#Desmos", "#MathHacks", "#DigitalSAT"],
    "hashtags_tiktok": ["#studytok", "#satprep", "#desmos"],
    "youtube": {"title": "Max 100 characters", "description": "...", "hashtags": ["#SAT", "#Desmos", "#DigitalSAT"]},
    "tiktok_mode": "direct",
    "ai_label": true
  }
  ```
  `"tiktok_mode": "draft"` sends it to your TikTok inbox instead, so you can add a trending sound and post it yourself.
- The 1000-short plan uses the media repo (§6b) instead of `posts/`; shorts placed directly in `posts/` still work for one-offs.
- Short videos are deleted from the repo 48 hours after they're live everywhere (`PRUNE_VIDEOS_AFTER_HOURS`, a repo variable; `0` keeps them). That keeps GitHub Pages under its 1 GB limit; the posting log keeps the record. Keep your own copy of each MP4 outside the repo.
- At most 1 short posts per hourly run, oldest first (`MAX_SHORTS_PER_RUN`, a repo variable; `0` = no limit). If a batch is rendered late or GitHub Actions was down, the overdue shorts go out one an hour instead of all at once. Feed posts aren't capped.

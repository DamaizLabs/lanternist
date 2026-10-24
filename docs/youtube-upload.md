# Uploading to YouTube: by hand, or through the API

Lanternist never needs a Google account to make a video. **By default it uploads nothing**: the run ends with
everything ready for you to upload by hand in YouTube Studio. This page explains both ways, and how to set up your own
Google project if you want Lanternist to upload the draft for you.

For now, `LEEME.html` and the console messages that this page quotes are in Spanish.

## Two ways to upload

| | By hand in Studio (the default) | Through the API |
|---|---|---|
| How to choose it | leave `YOUTUBE_SUBIDA_API` empty in `.env` | `YOUTUBE_SUBIDA_API=1` in `.env`, plus your own OAuth (steps 1 to 8) |
| What Lanternist does | prepares everything and talks to nobody | uploads the video as a **private draft** and sets the thumbnail |
| What you do | follow the steps in `subir-al-canal/LEEME.html` | review the draft in Studio, attach the `.srt` files and publish when you decide |
| Google setup | none | once, on this page |

Both ways run the same checks first: the subtitles are up to date, the description is composed (chapters, sources and
the AI disclosure), the video and the thumbnail carry their AI marks ([AI marking](ai-marking.md)), and every asset has
its provenance in `assets.json`. If a check fails, nothing is uploaded and the run says what to fix.

Any other value of `YOUTUBE_SUBIDA_API` (`yes`, `true`, `0`…) stops the run. Lanternist does not guess whether you meant
to send your video out of your PC.

### By hand (the default)

The run leaves these files in `canales/<channel>/videos/<run>/subir-al-canal/`:

- `final.mp4`, the video;
- `thumbnail.png`;
- one `subtitulos.<language>.srt` per language;
- `LEEME.html`, which opens by itself at the end of `--run-all`. It has the title and the full description, each with
  a copy button, and the Studio steps: keep the video **private** first, answer **yes** to the question about altered
  or synthetic content, set the audience and the category that your channel profile declares, then upload the
  thumbnail and the `.srt` files.

### Through the API

With `YOUTUBE_SUBIDA_API=1`, the upload stage:

- refuses to start if your `.env` lacks one of the three OAuth values, and says which one;
- uploads the video as a **private** draft. Privacy is not an option: it is a constant in `lib/youtube_client.py`;
- declares it as synthetic content (`status.containsSyntheticMedia`);
- puts the AI disclosure in the description;
- sets the thumbnail, if your channel is verified by phone ([step 8](#8-verify-the-channel-by-phone));
- lists in `LEEME.html` what is left to do by hand. The `.srt` files are always on that list (see
  [step 3](#3-permissions)).

It never publishes, and it never uploads the same run twice: running the stage again shows the video that is already
up. `--forzar-subida` makes a second draft on purpose. Lanternist never retries a failed upload on its own.

## What the API upload promises

A private draft, with the synthetic-content flag and the AI disclosure: what Lanternist controls is listed above.

What YouTube does next with a video uploaded from a new, unaudited project is not settled in Google's documentation,
because two of its pages disagree:

- the reference of [`videos.insert`](https://developers.google.com/youtube/v3/docs/videos/insert), updated on
  15 October 2026, says: "Videos uploaded from unverified API projects are not restricted to private viewing mode";
- the [revision history](https://developers.google.com/youtube/v3/revision_history) has no entry that explains the
  change. Its only entry on the subject, of 28 July 2020, is the one that introduced the restriction.

In practice, the same upload code works from a project like the one this page sets up: created in 2026, never
audited, published to production with its sensitive scope unverified. Its uploads behave as normal drafts. What has not
been tested is this guide followed from scratch by a new user.

If YouTube still locks your draft as private and Studio does not let you change it, upload `final.mp4` by hand in Studio.
The title, the description and every file you need are in `subir-al-canal/`, and `LEEME.html` lists them. Answer
**yes** to the question about altered or synthetic content.

Since 1 June 2026, `videos.insert` is charged to its own quota bucket (revision history). The `videos.insert` reference
gives its size: "100 calls per day", at 1 unit per call.

## Before you start

- **Your own Google Cloud project.** Lanternist ships no Google credentials. Every user creates their own project, so
  the quota, the consent screen and the tokens are yours. Never use someone else's client ID or secret.
- **A YouTube channel that is yours**, already created. A token is valid for one channel: the token of one channel gets
  a `403` on another.
- **A home page and a privacy policy on a domain of yours.** Google asks for both before it lets you publish the app
  (step 5). A domain already verified in [Google Search Console](https://search.google.com/search-console) was accepted
  as an authorized domain with no extra step. This guide was written with such a site; without one, step 2 may need
  work that this page does not describe yet.
- **A phone**, to verify the channel (step 8).

## 1. Create the project and enable two APIs

1. In the [Google Cloud console](https://console.cloud.google.com/), create a new project. Its name is only for you:
   the consent screen shows the app name of step 2.
2. Open the [API Library](https://console.cloud.google.com/apis/library) (**APIs & Services → Library**) and enable
   [**YouTube Data API v3**](https://console.cloud.google.com/apis/library/youtube.googleapis.com) and
   [**YouTube Analytics API**](https://console.cloud.google.com/apis/library/youtubeanalytics.googleapis.com).
3. Check both in the [API dashboard](https://console.cloud.google.com/apis/dashboard).

> **Check the project name at the top of every console page.** The console opens the last project you used, so a link
> can take you to the right page of the wrong project, and then everything looks misconfigured.

**Why Analytics now, if you only want to upload.** Lanternist's metrics snapshot (`metricas.py`) reads YouTube
Analytics with the same token. If that API is not enabled, its permission does not show up in step 3, and adding it
later means doing step 6 again.

## 2. The branding

Google calls this whole area **Google Auth Platform** ([its documentation](https://support.google.com/cloud/answer/15549049)).
Open [**Branding**](https://console.cloud.google.com/auth/branding):

| Field | What to write | Required |
|---|---|---|
| App name | the brand of your home page (see below) | yes |
| User support email | your email | yes |
| App logo | **leave it empty**: uploading a logo sends the app to verification ([Google](https://support.google.com/cloud/answer/15549049)) | no |
| Application home page | your site's home page | **yes, to publish** |
| Application privacy policy link | your privacy policy | **yes, to publish** |
| Application terms of service link | empty | no |
| Authorized domains | your domain, without `www.` or `https://` | yes |
| Developer contact information | your email | yes |

Then **Save**.

> **The app name has to match the brand of your home page.** Brand verification rejects an app whose name is not the
> name of the home page you declare. The consent screen shows the app name, not the project name.

## 3. Permissions

Open [**Data Access**](https://console.cloud.google.com/auth/scopes) → **Add or remove scopes**, and add exactly these
two:

```
https://www.googleapis.com/auth/youtube.upload
https://www.googleapis.com/auth/yt-analytics.readonly
```

The console files `yt-analytics.readonly` under the non-sensitive scopes and `youtube.upload` under the sensitive ones.
That is expected.

- **Do not add `youtube` on its own.** Together with `youtube.upload`, the consent fails with
  `Access blocked: Authorization Error` and `invalid_scope`, and the error does not say which scope is extra.
- **Why not `youtube.force-ssl`.** Uploading subtitles through the API (`captions.insert`) needs `youtube.force-ssl` or
  `youtubepartner`, and `force-ssl` gives full write access to the account, deleting videos included. Lanternist would
  rather leave the `.srt` files to you than hold a permission that can delete your videos. So the subtitles always go
  by hand, in Studio.
- These two scopes do not let Lanternist change your channel's banner, description or keywords either. You do that in
  Studio.

## 4. The OAuth client

Open [**Clients**](https://console.cloud.google.com/auth/clients) → **Create client**:

| Field | Value |
|---|---|
| Application type | **Web application** |
| Name | anything: it only names the client in the console |
| Authorized JavaScript origins | empty |
| **Authorized redirect URIs** | `https://developers.google.com/oauthplayground` |

- **Web application, not Desktop.** A desktop client has no redirect URI field, and without that URI the OAuth
  Playground of step 6 cannot give you the token.
- **Copy the client secret right away.** Google shows it in full only once, when it is created
  ([Google](https://support.google.com/cloud/answer/15549257)): after that the client page shows it masked, with its
  last characters. If you lose it, press **+ Add secret** on the same page and copy the new one.
- **One client serves all your channels.** What changes per channel is the refresh token (step 6).

## 5. Publish the app

Open [**Audience**](https://console.cloud.google.com/auth/audience) → **Publish app** → **Confirm**.

**Why this step matters.** While the app is in **Testing**, Google issues refresh tokens that expire after 7 days. Once
it is in production they last, unless the token goes unused for six months or you revoke the access
([OAuth 2.0 for Google APIs, "Refresh token expiration"](https://developers.google.com/identity/protocols/oauth2#expiration)).

The confirmation dialog warns about two things that sound worse than they are:

- **The app becomes available to any user with a Google Account.** Anyone with your client ID **and** your secret could
  start an authorization, but OAuth grants access to the account of whoever consents: theirs, not yours. If your
  secret leaked, the real risk is someone spending your project's quota.
- **You will need to submit it for verification**, because `youtube.upload` is a sensitive scope. Unverified and in
  production:

| Unverified, in production | What it means for you |
|---|---|
| The consent shows **"Google hasn't verified this app"** | you go past it once per channel (step 6) |
| At most **100 users** can grant access ([Google](https://support.google.com/cloud/answer/7454865)) | you are one user, even with several channels |
| The refresh token **no longer expires after 7 days** | this is the whole point of publishing |

**Check:** the publishing status says **In production** and offers to go **back to testing**. If it still says
Testing, see [Traps](#traps-by-the-error-you-see).

## 6. The refresh token, in the OAuth Playground

Once per channel, after the channel exists: without a channel there is nobody to grant access to. In the
[OAuth 2.0 Playground](https://developers.google.com/oauthplayground):

1. **Gear icon**, top right → tick **Use your own OAuth credentials** → paste your client ID and secret.
2. Left panel → **Input your own scopes** → paste the two scopes of step 3, separated by a space.
3. **Authorize APIs** → sign in with **the Google account that owns the channel**.
4. If that account has several channels, YouTube asks which one you are granting access to: **pick the channel you will
   upload to**. A token for the wrong channel gets a `403` on the right one, and you have to start again.
5. You see **"Google hasn't verified this app"**. That is expected: **Advanced** → **Go to … (unsafe)**, where "…" is
   your app name.
6. **Allow**.
7. In **Step 2**, press **Exchange authorization code for tokens** and copy the **Refresh token** (it starts with
   `1//`). It goes in your `.env` (step 7). Never paste it in a chat, an issue or a commit.

> **Step 1 is not optional.** A note at the foot of the panel says: "The OAuth Playground will automatically revoke
> refresh tokens after 24h. You can avoid this by specifying your own application OAuth credentials using the
> Configuration panel." Without your own credentials, your token dies the next day.

- **The Playground's Step 3, "Configure request to API", is not used.** What you came for is in Step 2. Close the tab
  once you have the token.
- **Leave "Auto-refresh the token before it expires" alone.** It refreshes the Playground's own access token, which
  Lanternist does not use: Lanternist asks Google for a new access token itself, with your refresh token.

## 7. The `.env`

```
YOUTUBE_SUBIDA_API=1
YOUTUBE_CLIENT_ID=<your client ID>
YOUTUBE_CLIENT_SECRET=<your client secret>
YOUTUBE_REFRESH_TOKEN=<the refresh token of your channel>
```

`.env` is in `.gitignore`, so it never goes into git.

### One token per channel

The channel profile names the variable that holds its token: `canales/<channel>/perfil.json →
publicacion.refresh_token_env`. The example channel uses `YOUTUBE_REFRESH_TOKEN`. A second channel declares another
name, for instance `YOUTUBE_REFRESH_TOKEN_2`, and gets its own token from step 6, signed in with the account that owns
it. The client ID and the secret are the same for all your channels.

- Without the **name** in the profile, the channel does not start any run.
- Without the **token** in `.env`, the upload by API refuses and says which variable is missing. The upload by hand
  does not ask for it.

### Check it

```
.venv\Scripts\python pipeline.py --check
```

The upload block has to say `✓ subida por la API: encendida, con el OAuth completo`. If a value is missing, it says
which one, with a `✗`, and `--check` fails.

`--check` only sees that the values are there. To check that the token is valid and belongs to **your** client:

```
.venv\Scripts\python -c "import os,sys,requests; os.environ['CANAL_ACTIVO']='<channel>'; sys.path.insert(0,'.'); from lib import config as c; r=requests.post('https://oauth2.googleapis.com/token', data={'client_id':c.YOUTUBE_CLIENT_ID,'client_secret':c.YOUTUBE_CLIENT_SECRET,'refresh_token':c.YOUTUBE_REFRESH_TOKEN,'grant_type':'refresh_token'}); print(r.status_code, r.json().get('scope') or r.json().get('error_description'))"
```

It has to print `200` and the two scopes. A `400` with `invalid_grant` means that the token was revoked or does not
belong to this client. This exchange spends no Data API quota.

A token from another of your channels also passes that check. To make sure the token is for **this** channel, ask
YouTube Analytics with the channel's id: it starts with `UC`, and it is the last part of the address of the channel's
Studio, `https://studio.youtube.com/channel/<channel id>`. Its own token gets `200`, any other gets `403`.

```
.venv\Scripts\python -c "import os,sys,requests; os.environ['CANAL_ACTIVO']='<channel>'; sys.path.insert(0,'.'); from lib.youtube_client import get_access_token; r=requests.get('https://youtubeanalytics.googleapis.com/v2/reports', params={'ids':'channel==<channel id>','startDate':'<YYYY-MM-DD>','endDate':'<YYYY-MM-DD>','metrics':'views'}, headers={'Authorization':'Bearer '+get_access_token()}); print(r.status_code)"
```

Use a few recent days as the dates. A new channel with no videos gets `200` and no rows, and that is correct.

## 8. Verify the channel by phone

Without it, YouTube refuses custom thumbnails (`thumbnails.set` gives `403`, so the video goes up without its
thumbnail) and videos longer than 15 minutes. It is a requirement of the **channel**, not an OAuth permission:
`youtube.upload` already covers `thumbnails.set`.

- **It is per channel, not per Google account.** A verified channel does not verify another one of the same account.
- **"A phone number can only be associated with 2 channels per year"**, says
  [YouTube Help](https://support.google.com/youtube/answer/171664).

1. Open Studio and check, top right, which channel you are in.
2. Go to [youtube.com/verify](https://www.youtube.com/verify).
3. Check again which channel the page shows, before you type anything.
4. Choose your country, and SMS or automated call. If the SMS does not arrive within a couple of minutes, start again
   with the call.
5. Type the number, then the 6-digit code you receive.
6. Write `"verificado_por_telefono": true` in the `publicacion` block of the channel profile.
   `scripts/comprueba_canal.py` reads it.

A video uploaded before the verification does not need a new upload:

```
.venv\Scripts\python pipeline.py --run-id <run_id> --set-thumbnail
```

puts the thumbnail on the video that is already up, without touching its visibility.

## 9. Upload

```
.venv\Scripts\python pipeline.py --stage upload --run-id <run_id>
```

or let `--run-all` get there. Then open the draft in Studio (`LEEME.html` has the link), attach the `.srt` files and
publish when you decide.

### Optional: a read-only API key

With `youtube.upload` alone, Lanternist cannot read the video back after uploading it (YouTube answers `403
insufficientPermissions`), so it cannot confirm the privacy and the synthetic-content flag. With an API key in `.env`
(`YOUTUBE_API_KEY`), it can at least confirm that the video is not public, because a key does not see private videos.
Create it in the [Credentials](https://console.cloud.google.com/apis/credentials) page of your project. Without a key,
the upload says the check is `SIN CONFIRMAR` and you look in Studio.

## Traps, by the error you see

| What you see | What is really going on |
|---|---|
| **Publish app** is greyed out, with a note about an incomplete configuration | The home page or the privacy policy URL is missing. The tooltip of the disabled button is the only place that says so |
| Brand verification says the app name does not match the name of your home page | Rename the app to the brand of the domain you gave as home page |
| `Access blocked: this app is not configured for your account` when consenting | The app is in Testing and your account is not one of its test users, a list that starts empty. Add yourself, or publish the app (step 5) |
| `Access blocked: Authorization Error` with `invalid_scope` | You added `youtube` on its own besides `youtube.upload` |
| The client secret shows as `****` and cannot be copied | Google no longer shows it. **+ Add secret** creates a new one |
| The client has no redirect URI field | You created it as Desktop. It has to be Web application |
| **"Google hasn't verified this app"** when consenting | Expected with a sensitive scope and no verification: **Advanced → Go to … (unsafe)** |
| The token stops working the next day | You did not tick **Use your own OAuth credentials** in the Playground |
| The token stops working after a week | The app is in Testing. Publish it (step 5) |
| `403` on `channels.list?mine=true` with a fresh token | It is not the token: that call needs `youtube.readonly`, which is not one of your two scopes. To see whose token it is, use the Analytics check of [step 7](#check-it) |
| `403` when uploading or reading metrics, with a token that works on another channel | The token belongs to the other channel. Repeat step 6 and pick the right channel |
| `403 forbidden` when setting the thumbnail: "The authenticated user doesn't have permissions to upload and set custom video thumbnails" | It is not a scope problem: the channel is not verified by phone (step 8). After verifying it, use `--set-thumbnail` |
| `400 Bad Request` with the API key read by hand from `.env` | The key's line has a comment after it, and you sent the comment too. Read the key through `lib/config.py`, which strips it. Do not retry blindly: find the cause, then make one more call |
| `--check` or the upload says `YOUTUBE_SUBIDA_API vale '…'` | The switch only takes two values: empty (by hand) or `1` (through the API) |
| Typing a URL in the console jumps to the search box | `/` is the console's shortcut for search. Paste with `Ctrl+V`, or click inside the field first |

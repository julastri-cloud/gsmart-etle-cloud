# Telegram CAPTCHA human-in-the-loop — development notes

## Current development scope

The helper is integrated on branch `feature/telegram-captcha-human-in-loop` into these login entry points:

- `sync_etle.py` — main ETLE synchronization.
- `sync_private_dispute_one.py` — used by private dispute imports and stopped-vehicle photo sync.
- `diagnose_dispute_detail_safe.py` — read-only dispute diagnostic.
- `diagnose_terminated_vehicle_photo_safe.py` — read-only stopped-vehicle diagnostic.

The helper uses the login selectors supplied from the ETLE Hub page:

- CAPTCHA image: `#captchaImg`
- CAPTCHA input: `input[name="captcha"]`
- Login submit button: `button[type="submit"].btn-theme`

It screenshots only the CAPTCHA element to a temporary local file, sends that image to the configured private Telegram chat, and accepts a five-character alphanumeric answer only when the owner replies to that exact challenge photo. The temporary image is deleted after the reply. No CAPTCHA solver is used, and no browser cookies/storage state are persisted by this helper.

After submission, login is considered successful only if the browser leaves the `/main/` login route. The helper makes at most three human-assisted attempts and stops safely if it cannot reach the dashboard.

## Required GitHub Actions secrets

Configure these repository secrets only when ready to test the feature:

- `TG_TOKEN` — Telegram bot token.
- `TG_CHAT_ID` — numeric ID of the owner's private chat with the bot.
- `EMAIL_ETLE` and `PASSWORD_ETLE` — existing ETLE credentials, already required by relevant jobs.
- `CAPTCHA_WAIT_SECONDS` — optional, defaults to 300 seconds; maximum 600 seconds.

Never paste tokens, passwords, browser cookies, session storage, or private ETLE data into commits, logs, or this PR.

## Safe verification plan

1. Confirm the branch and draft PR only; do not merge.
2. Run the isolated unit/syntax workflow. It does not log into ETLE or access Supabase.
3. Configure Telegram secrets only after confirming the bot is private and the chat ID is correct.
4. Test one explicitly approved diagnostic first, with no Supabase write path.
5. Confirm timeout, wrong answer, failed credentials, and dashboard navigation all fail closed.
6. Only then consider testing a data sync. Review its database writes separately before any production run.

The automated workflow does not itself prove live ETLE login works. A real integration test requires the owner to reply to a CAPTCHA in Telegram and must be run separately from isolated CI tests.

## Production boundary

This branch changes login behavior in scripts but does not change the default branch, production workflows, database schema, RLS, or production secrets. Do not merge or trigger production synchronization without explicit approval.

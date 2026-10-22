# Telegram CAPTCHA integration — development branch

Branch: `feature/telegram-captcha-human-in-loop`

## Scope of this first commit

- Adds a reusable Telegram client that sends a CAPTCHA image to a configured **private** chat.
- Accepts only a text reply to that exact challenge photo from the configured chat owner.
- Waits up to `CAPTCHA_WAIT_SECONDS` (default 300 seconds) and fails closed on timeout/API errors.
- Does not solve CAPTCHA automatically.
- Does not persist ETLE cookies or browser storage state.
- Does not change any existing sync script, workflow, database schema, RLS policy, or production secret.

## Configuration (for a future integration test)

Set as GitHub Actions secrets:
- `TG_TOKEN`: token issued by BotFather.
- `TG_CHAT_ID`: numeric ID of the owner's private Telegram chat.

Optional environment variable:
- `CAPTCHA_WAIT_SECONDS`: integer 1–600; default 300.

Do not commit tokens, session files, CAPTCHA images, or credentials.

## Verification before wiring into production sync scripts

1. Verify the actual ETLE Hub CAPTCHA image/input selectors against the current login page. The current repository code does not identify those selectors, so no guessed selector is silently added here.
2. Test Telegram API access in an isolated workflow with no ETLE credentials and no Supabase/Fonnte secrets.
3. Test that unrelated Telegram messages, group messages, and replies to old photos are rejected.
4. Decide on a protected cross-run session mechanism. Do **not** put raw Playwright `storage_state` files in GitHub Actions cache.
5. Only then wire the module into each relevant login path and add a manually triggered test workflow with no production writes.

## Local unit tests

```bash
python -m unittest discover -s tests -v
```

These tests cover reply binding and sender restrictions; they do not test live Telegram or ETLE Hub.

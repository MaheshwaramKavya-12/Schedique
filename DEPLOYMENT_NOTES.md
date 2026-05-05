## Deployment Notes

These optional environment variables improve reliability and deployment safety without changing the app workflow or UI:

```env
SECRET_KEY=change_this_to_a_long_random_secret
APP_LOG_LEVEL=INFO
SESSION_COOKIE_SECURE=false
SESSION_COOKIE_SAMESITE=Lax
SESSION_LIFETIME_HOURS=12
AUTO_OPEN_BROWSER=true
```

### Notes

- Set `SECRET_KEY` explicitly outside local demo environments.
- Turn `SESSION_COOKIE_SECURE=true` when serving over HTTPS.
- Use `AUTO_OPEN_BROWSER=false` on servers or CI environments.
- `APP_LOG_LEVEL=DEBUG` can help during troubleshooting.

### Health Check

The app now exposes a lightweight status endpoint:

```text
GET /api/health
```

It returns app time, timezone, DB probe result, mail configuration status, and scheduler availability.

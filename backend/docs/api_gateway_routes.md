# API Gateway Routes — M7 Pricing + OAuth

## Gateway: Nginx / Kong / Cloudflare

### Public routes (no auth)
```
GET  /health
GET  /api/auth/login/google
GET  /api/auth/login/github
GET  /api/auth/callback/google
GET  /api/auth/callback/github
GET  /api/pricing/currency
POST /api/pricing/convert
```

### Authenticated routes (require `Authorization: Bearer <token>`)
```
GET  /api/auth/me
POST /api/auth/logout
```

### Upstream
- **Service**: `http://localhost:8000` (FastAPI uvicorn)
- **Timeout**: 30s
- **Retries**: 3

---

## Example Nginx config

```nginx
server {
    listen 80;
    server_name api.poe2li.com;

    client_max_body_size 10M;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 30s;
        proxy_connect_timeout 10s;
    }
}
```

---

## Example Kong config (declarative)

```yaml
_format_version: "2.1"
services:
  - name: poe2li-backend
    url: http://127.0.0.1:8000
    routes:
      - name: api-route
        paths:
          - /api
        methods:
          - GET
          - POST
          - PUT
          - DELETE
    plugins:
      - name: cors
      - name: rate-limiting
        config:
          minute: 100
          policy: local
```

---

## Environment Variables

| Variable | Required | Description |
|---|---|---|
| `SECRET_KEY` | Yes | JWT signing key (use strong random in prod) |
| `GOOGLE_CLIENT_ID` | Yes | Google OAuth client ID |
| `GOOGLE_CLIENT_SECRET` | Yes | Google OAuth client secret |
| `GITHUB_CLIENT_ID` | Yes | GitHub OAuth client ID |
| `GITHUB_CLIENT_SECRET` | Yes | GitHub OAuth client secret |
| `FRONTEND_REDIRECT_BASE` | No | Frontend base URL (default `http://localhost:3000`) |
| `REDIS_URL` | No | Redis URL (default `redis://localhost:6379/0`) |
| `CELERY_BROKER_URL` | No | Celery broker URL |
| `CELERY_RESULT_BACKEND` | No | Celery result backend |

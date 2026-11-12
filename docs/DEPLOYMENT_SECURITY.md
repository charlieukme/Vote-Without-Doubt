# Deployment Security & Hardening Guide

**Product:** Vote Without Doubt (AI & Blockchain-Based Secure E-Voting System)  
**Phase:** 15 — Privacy, Legal & Security Documentation  

---

## 1. Production Deployment Checklist

Before deploying **Vote Without Doubt** in any institutional collegiate election environment, system administrators must complete and verify the following hardening checklist:

| Control Area | Security Requirement | Implementation in Repository | Operational Status |
|:---|:---|:---|:---:|
| **Debug Mode** | Disable Flask debug mode: `DEBUG=False`, `FLASK_ENV=production`. | Configured via `APP_ENV` and `FLASK_ENV` | **REQUIRES DEPLOYMENT CONFIG** |
| **Secret Randomness** | All secrets must be generated using CSPRNG (minimum 32 bytes). | Supported via `.env` / environment variables | **REQUIRES DEPLOYMENT CONFIG** |
| **Database Isolation** | MySQL 8.0 bind address `127.0.0.1` or internal Docker network only. | Schema supports InnoDB row locking | **REQUIRES DEPLOYMENT CONFIG** |
| **TLS / HTTPS** | Terminate TLS 1.2+ at Nginx/Caddy reverse proxy; disable HTTP. | Web server reverse proxy configuration | **REQUIRES DEPLOYMENT CONFIG** |
| **Secure Cookies** | `SESSION_COOKIE_SECURE = True`, `SESSION_COOKIE_HTTPONLY = True`. | Implemented in `backend/app/config/config.py` | **IMPLEMENTED** (Configurable flag) |
| **Cookie SameSite** | `SESSION_COOKIE_SAMESITE = 'Strict'` to prevent CSRF. | Implemented in `backend/app/config/config.py` | **IMPLEMENTED** |
| **CORS Origins** | Restrict `CORS_ORIGINS` to trusted college frontend domain only. | Configurable in `backend/app/config/config.py` | **IMPLEMENTED** (Configurable flag) |
| **Rate Limiting** | Rate limit auth, face, and voting endpoints to prevent brute-force. | In-memory sliding window rate limiter | **IMPLEMENTED** |
| **Admin 2FA** | Mandatory password + TOTP (RFC 6238) for all administrative logins. | Implemented in `backend/app/security/totp.py` | **IMPLEMENTED** |
| **Password KDF** | Memory-hard Argon2id parameters ($m=64\text{MB}, t=3, p=4$). | Implemented in `backend/app/security/password.py` | **IMPLEMENTED** |
| **Relayer Key Storage** | Relayer private key loaded from secure env or HSM; not in Git. | Read via `os.getenv('RELAYER_PRIVATE_KEY')` | **IMPLEMENTED** |
| **Biometric Key Storage**| Master AES-256 key (`FACE_EMBEDDING_KEY`) stored securely. | Read via `os.getenv('FACE_EMBEDDING_KEY')` | **IMPLEMENTED** |
| **Pseudonym Master Key** | 32-byte Fernet key (`PSEUDONYM_MASTER_KEY`) stored securely. | Fails closed if missing in `pseudonym.py` | **IMPLEMENTED** |
| **Logging Hygiene** | Sanitized metadata; zero secrets, tokens, or PII in logs. | Deny-by-default allow-list in `audit.py` | **IMPLEMENTED** |
| **Tampering Demo Route**| Route `/api/elections/<id>/tampering-demo` must be disabled. | Code auto-returns 403 when `APP_ENV=production` | **IMPLEMENTED** |
| **Automated Backups** | Encrypted daily snapshots of MySQL database and Ganache state. | External cron / backup script required | **REQUIRES DEPLOYMENT CONFIG** |
| **Network Firewalls** | Block public access to ports 3306 (MySQL) and 8545 (Ganache/RPC).| Operating system firewall / security group | **REQUIRES DEPLOYMENT CONFIG** |

---

## 2. Hardened Environment Variable Template (`.env.production`)

```bash
# ------------------------------------------------------------------------------
# CORE APPLICATION ENVIRONMENT
# ------------------------------------------------------------------------------
APP_ENV=production
FLASK_ENV=production
DEBUG=False
TESTING=False
SECRET_KEY=<GENERATE_64_CHAR_HEX_SECRET>

# ------------------------------------------------------------------------------
# DATABASE CONNECTION (MySQL 8 with InnoDB)
# ------------------------------------------------------------------------------
DATABASE_URL=mysql+pymysql://vwd_app_user:<DB_PASSWORD>@127.0.0.1:3306/voting_sys_prod?charset=utf8mb4
AUTO_CREATE_SCHEMA=0

# ------------------------------------------------------------------------------
# SESSION & COOKIE SECURITY
# ------------------------------------------------------------------------------
SESSION_COOKIE_SECURE=True
SESSION_COOKIE_HTTPONLY=True
SESSION_COOKIE_SAMESITE=Strict
SESSION_TIMEOUT_HOURS=2
SESSION_IDLE_TIMEOUT_MINUTES=10

# ------------------------------------------------------------------------------
# CORS & NETWORKING
# ------------------------------------------------------------------------------
CORS_ORIGINS=https://vote.college.edu
ALLOWED_HOSTS=vote.college.edu

# ------------------------------------------------------------------------------
# CRYPTOGRAPHIC MASTER KEYS (NEVER COMMIT TO GIT)
# ------------------------------------------------------------------------------
# 32-byte base64-encoded Fernet key for election pseudonym key envelope
PSEUDONYM_MASTER_KEY=<GENERATE_BASE64_32_BYTE_KEY>

# 32-byte base64-encoded Fernet key for biometric ArcFace template encryption (AES-128-CBC + HMAC-SHA256)
FACE_ENCRYPTION_KEY=<GENERATE_BASE64_32_BYTE_KEY>

# Secret for voter receipt code HMAC computation
RECEIPT_SECRET=<GENERATE_64_CHAR_HEX_SECRET>

# Pepper for Email OTP HMAC computation
OTP_PEPPER=<GENERATE_64_CHAR_HEX_SECRET>

# ------------------------------------------------------------------------------
# BLOCKCHAIN & RELAYER (Ganache or Private Geth / Polygon PoS)
# ------------------------------------------------------------------------------
BLOCKCHAIN_RPC_URL=http://127.0.0.1:8545
CHAIN_ID=1337
BALLOTBOX_CONTRACT_ADDRESS=0x<DEPLOYED_CONTRACT_ADDRESS>
RELAYER_ACCOUNT=0x<RELAYER_PUBLIC_ADDRESS>
RELAYER_PRIVATE_KEY=<RELAYER_32_BYTE_HEX_PRIVATE_KEY>
RELAYER_ENABLED=True

# ------------------------------------------------------------------------------
# RATE LIMITING & SECURITY GUARDS
# ------------------------------------------------------------------------------
RATE_LIMIT_ENABLED=True
SKIP_RATE_LIMIT=0
RATE_LIMIT_LOGIN=5,300
RATE_LIMIT_AUTHORIZE=10,60
RATE_LIMIT_SUBMIT=5,60
```

---

## 3. Reverse Proxy Configuration Example (Nginx)

```nginx
server {
    listen 443 ssl http2;
    server_name vote.college.edu;

    ssl_certificate /etc/letsencrypt/live/vote.college.edu/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/vote.college.edu/privkey.pem;
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers HIGH:!aNULL:!MD5;

    # Security Headers
    add_header X-Frame-Options "DENY" always;
    add_header X-Content-Type-Options "nosniff" always;
    add_header X-XSS-Protection "1; mode=block" always;
    add_header Content-Security-Policy "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self' https://vote.college.edu;" always;

    # Reverse proxy to Gunicorn backend
    location /api/ {
        proxy_pass http://127.0.0.1:5000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto https;
        proxy_read_timeout 60s;
    }

    # Static frontend build
    location / {
        root /var/www/voting-sys/frontend/dist;
        index index.html;
        try_files $uri $uri/ /index.html;
    }
}
```

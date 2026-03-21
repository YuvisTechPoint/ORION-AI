# GitHub OAuth 2.0 Integration Guide

## Overview

ORION CI/CD Platform now includes complete GitHub OAuth 2.0 authentication, enabling seamless user login and automated PR management with GitHub credentials.

## Setup Instructions

### 1. Register GitHub OAuth Application

1. Go to [GitHub Settings › Developer Settings › OAuth Apps](https://github.com/settings/developers)
2. Click "New OAuth App"
3. Fill in the application details:
   - **Application name**: `ORION CI/CD`
   - **Homepage URL**: `http://localhost:5173` (or your production domain)
   - **Authorization callback URL**: `http://localhost:8001/api/v1/auth/github/callback`
4. Click "Register application"
5. Generate a new client secret (save it securely)

### 2. Configure Environment Variables

Add to `backend/.env`:

```env
GITHUB_CLIENT_ID=your_client_id_here
GITHUB_CLIENT_SECRET=your_client_secret_here
GITHUB_REDIRECT_URI=http://localhost:8001/api/v1/auth/github/callback
SESSION_SECRET_KEY=your_random_secret_key_here
FRONTEND_URL=http://localhost:5173
```

### 3. Backend Configuration

The backend automatically configures OAuth with:
- **Session Middleware**: `same_site="none"` for cross-origin cookies
- **CORS**: Allows `localhost:5173` and `127.0.0.1:5173`
- **HMAC-SHA256**: Cryptographic state validation for CSRF protection

### 4. Frontend Setup

The frontend automatically handles:
- OAuth redirect to GitHub login
- Session polling every 30 seconds
- User profile display with avatar
- Automatic logout capability

## API Endpoints

### Authentication Routes

#### `GET /api/v1/auth/github`
Initiates OAuth login flow. Redirects to GitHub login page.

```bash
curl -i http://localhost:8001/api/v1/auth/github
```

#### `GET /api/v1/auth/github/callback?code=xxx&state=xxx`
OAuth callback endpoint (called by GitHub). Exchanges code for token and establishes session.

#### `GET /api/v1/auth/status`
Get current authentication status.

```bash
curl -i -b "session=..." http://localhost:8001/api/v1/auth/status
```

Response:
```json
{
  "authenticated": true,
  "username": "github_username",
  "has_github_token": true,
  "token_valid": true
}
```

#### `GET /api/v1/auth/me`
Get authenticated user profile.

```bash
curl -i -b "session=..." http://localhost:8001/api/v1/auth/me
```

Response:
```json
{
  "username": "github_username",
  "avatar": "https://avatars.githubusercontent.com/u/123456",
  "email": "user@example.com",
  "scopes": "repo,read:user,user:email"
}
```

#### `POST /api/v1/auth/logout`
Clear session and logout user.

```bash
curl -i -X POST -b "session=..." http://localhost:8001/api/v1/auth/logout
```

## Security Features

### CSRF Protection

State validation uses cryptographically signed HMAC-SHA256 tokens instead of session-dependent storage:

```python
# Generated state format: {token}.{hmac_signature}
state = "random_token.signature_hash"

# Validated on callback through HMAC comparison
validate_state_signature(state)  # Returns True/False
```

### Session Management

- **Session Secret Key**: Used for signing session data
- **Max Age**: Configurable OAuth token expiry (default: 24 hours)
- **SameSite**: Set to "none" for cross-origin allowed (with Secure flag in production)

### Token Scopes

Default GitHub scopes:
- `repo` - Full control of private repositories
- `read:user` - Read user profile info
- `user:email` - Read user email address

## Testing

### Run OAuth Tests

```bash
cd backend
python -m pytest tests/test_api.py -v
```

### Manual Testing

1. Start backend: `python -m uvicorn main:app --reload --port 8001`
2. Start frontend: `npm run dev` (port 5173)
3. Navigate to `http://localhost:5173`
4. Click "Login with GitHub"
5. Authorize the app on GitHub
6. Verify user profile displays correctly

## Troubleshooting

### "Invalid OAuth state — possible CSRF attack"
- **Cause**: State validation failed
- **Solution**: Check `SESSION_SECRET_KEY` is same on backend config

### "incorrect_client_credentials"
- **Cause**: Client secret is empty or wrong
- **Solution**: Verify `GITHUB_CLIENT_SECRET` in `.env`

### Cookies not persisting across requests
- **Cause**: CORS not allowing credentials
- **Solution**: Ensure `credentials: "include"` in frontend API calls

### 401 Unauthorized on protected endpoints
- **Cause**: Session not authenticated
- **Solution**: Confirm OAuth callback completed successfully

## Production Deployment

### Environment Setup

```env
APP_ENV=prod
GITHUB_REDIRECT_URI=https://yourdomain.com/api/v1/auth/github/callback
FRONTEND_URL=https://yourdomain.com
SESSION_SECRET_KEY=generate_strong_random_key_with_secrets_module
DATABASE_URL=<your_production_db>
```

### HTTPS Enforcement

In production, update middleware configuration:

```python
# main.py
app.add_middleware(
    SessionMiddleware,
    secret_key=settings.session_secret_key,
    https_only=True,  # Enforce HTTPS
    same_site="strict",  # Stricter CSRF protection
)
```

### GitHub App Configuration

Update OAuth app settings on GitHub:
- Set **Homepage URL** to production domain
- Set **Authorization callback URL** to production callback URL
- Generate new client secret for production

## Additional Resources

- [FastAPI Security Documentation](https://fastapi.tiangolo.com/advanced/security/)
- [GitHub OAuth Documentation](https://docs.github.com/en/apps/oauth-apps/building-oauth-apps)
- [Starlette Session Middleware](https://www.starlette.io/middleware/)

# 🔒 HTTPS Setup for Thakii Backend

## Overview
This backend now supports HTTPS using **Nginx reverse proxy** - the standard way to serve Flask applications securely.

## Architecture
```
Internet → HTTPS (Port 443) → Nginx → HTTP (localhost:5001) → Flask
```

## Quick Setup

### 1. Deploy Backend
```bash
./scripts/deploy-https.sh
```

### 2. Setup HTTPS Proxy
```bash
sudo ./scripts/setup-nginx-https.sh
```

### 3. Test
```bash
curl https://thakii-02.fanusdigital.site/health
```

## What This Provides

✅ **Standard HTTPS on port 443**  
✅ **Let's Encrypt SSL certificates**  
✅ **Automatic certificate renewal**  
✅ **Proper security headers**  
✅ **CORS configuration for frontend**  
✅ **Large file upload support**  

## Files Added

- `nginx/thakii-backend.conf` - Nginx configuration
- `scripts/setup-nginx-https.sh` - HTTPS setup script  
- `scripts/deploy-https.sh` - Backend deployment script
- `HTTPS_SETUP.md` - This documentation

## Changes to Flask App

- Added `ProxyFix` middleware to handle reverse proxy headers
- Backend runs on `127.0.0.1:5001` (localhost only)
- Nginx handles HTTPS and forwards to Flask

## Production URLs

- **Backend API**: `https://thakii-02.fanusdigital.site`
- **Health Check**: `https://thakii-02.fanusdigital.site/health`

## Security Features

- **TLS 1.2/1.3** encryption
- **HSTS** headers
- **XSS Protection**
- **Content Type Protection** 
- **Frame Protection**
- **Referrer Policy**

This is the **proper way** to serve Flask applications with HTTPS in production!

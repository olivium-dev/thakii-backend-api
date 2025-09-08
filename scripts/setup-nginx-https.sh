#!/bin/bash

# Simple HTTPS Setup with Nginx Reverse Proxy
# This is the CORRECT way to do HTTPS for web APIs

set -e

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

print_status() {
    echo -e "${GREEN}✅ $1${NC}"
}

print_error() {
    echo -e "${RED}❌ $1${NC}"
}

print_warning() {
    echo -e "${YELLOW}⚠️ $1${NC}"
}

print_info() {
    echo -e "${BLUE}ℹ️ $1${NC}"
}

print_header() {
    echo -e "${BLUE}"
    echo "=================================================="
    echo "$1"
    echo "=================================================="
    echo -e "${NC}"
}

# Configuration
DOMAIN="thakii-02.fanusdigital.site"

print_header "Thakii HTTPS Setup with Nginx (The Right Way)"

# Check if running as root
if [ "$EUID" -ne 0 ]; then
    print_error "This script must be run as root (use sudo)"
    exit 1
fi

# Step 1: Install Nginx and Certbot
print_info "Installing Nginx and Certbot..."
apt-get update
apt-get install -y nginx certbot python3-certbot-nginx

print_status "Nginx and Certbot installed"

# Step 2: Stop Nginx temporarily for certificate generation
systemctl stop nginx

# Step 3: Get Let's Encrypt certificate
print_info "Getting Let's Encrypt SSL certificate..."
certbot certonly --standalone \
    --email admin@fanusdigital.site \
    --agree-tos \
    --no-eff-email \
    --domains $DOMAIN

if [ $? -eq 0 ]; then
    print_status "SSL certificate obtained successfully"
else
    print_error "Failed to obtain SSL certificate"
    exit 1
fi

# Step 4: Copy certificates to expected location
print_info "Setting up certificate paths..."
mkdir -p /etc/ssl/certs /etc/ssl/private

cp "/etc/letsencrypt/live/$DOMAIN/fullchain.pem" "/etc/ssl/certs/thakii.crt"
cp "/etc/letsencrypt/live/$DOMAIN/privkey.pem" "/etc/ssl/private/thakii.key"

chmod 644 /etc/ssl/certs/thakii.crt
chmod 600 /etc/ssl/private/thakii.key

print_status "Certificates configured"

# Step 5: Install Nginx configuration
print_info "Installing Nginx configuration..."
cp /home/ec2-user/thakii-backend-api/nginx/thakii-backend.conf /etc/nginx/sites-available/
ln -sf /etc/nginx/sites-available/thakii-backend.conf /etc/nginx/sites-enabled/

# Remove default site
rm -f /etc/nginx/sites-enabled/default

# Test Nginx configuration
nginx -t
if [ $? -eq 0 ]; then
    print_status "Nginx configuration is valid"
else
    print_error "Nginx configuration is invalid"
    exit 1
fi

# Step 6: Configure firewall
print_info "Configuring firewall..."
ufw allow 'Nginx Full'
ufw allow ssh
ufw --force enable

print_status "Firewall configured"

# Step 7: Start and enable services
print_info "Starting services..."
systemctl start nginx
systemctl enable nginx

print_status "Nginx started and enabled"

# Step 8: Set up auto-renewal
print_info "Setting up SSL certificate auto-renewal..."
(crontab -l 2>/dev/null; echo "0 12 * * * /usr/bin/certbot renew --quiet --nginx && systemctl reload nginx") | crontab -

print_status "Auto-renewal configured"

# Step 9: Test HTTPS
print_info "Testing HTTPS configuration..."
sleep 2

if curl -f https://$DOMAIN/health 2>/dev/null; then
    print_status "HTTPS is working correctly!"
else
    print_warning "HTTPS test failed - check if Flask backend is running on port 5001"
fi

print_header "Setup Complete!"

echo -e "${GREEN}🎉 HTTPS is now properly configured!${NC}"
echo
echo -e "${BLUE}📍 Your API is now available at:${NC}"
echo -e "${GREEN}   https://$DOMAIN${NC}"
echo
echo -e "${BLUE}🔧 Next steps:${NC}"
echo -e "${YELLOW}1. Start your Flask backend on port 5001 (HTTP)${NC}"
echo -e "${YELLOW}2. Update frontend to use: https://$DOMAIN${NC}"
echo -e "${YELLOW}3. Test the complete flow${NC}"
echo
echo -e "${BLUE}📋 Backend command:${NC}"
echo -e "${YELLOW}   python3 app.py${NC}"
echo -e "${YELLOW}   (No HTTPS needed - Nginx handles it!)${NC}"

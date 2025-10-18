#!/bin/bash
# PostgreSQL Installation Script for Server
# Run on server via SSH

set -e

echo "==================================="
echo "PostgreSQL 15 Installation"
echo "==================================="

# Install PostgreSQL 15
echo "Step 1: Installing PostgreSQL 15..."
sudo yum update -y
sudo amazon-linux-extras install -y postgresql15
sudo yum install -y postgresql15-server postgresql15-contrib

# Initialize database
echo "Step 2: Initializing database..."
sudo /usr/bin/postgresql-setup --initdb

# Start and enable PostgreSQL
echo "Step 3: Starting PostgreSQL service..."
sudo systemctl start postgresql
sudo systemctl enable postgresql

# Wait for PostgreSQL to start
sleep 5

# Configure PostgreSQL for local connections
echo "Step 4: Configuring PostgreSQL..."

# Create user and database
sudo -u postgres psql << 'EOF'
-- Create user
CREATE USER thakii_user WITH PASSWORD 'P@ssw0rd768_DB';

-- Create database
CREATE DATABASE thakii_production OWNER thakii_user;

-- Grant privileges
GRANT ALL PRIVILEGES ON DATABASE thakii_production TO thakii_user;

-- Connect to the database and grant schema privileges
\c thakii_production
GRANT ALL ON SCHEMA public TO thakii_user;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON TABLES TO thakii_user;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON SEQUENCES TO thakii_user;

EOF

# Update pg_hba.conf for local connections
echo "Step 5: Updating pg_hba.conf..."
PG_HBA="/var/lib/pgsql/data/pg_hba.conf"

sudo cp "$PG_HBA" "${PG_HBA}.backup"

# Add MD5 authentication for local connections
sudo bash -c "cat >> $PG_HBA << 'EOF'

# Thakii application access
local   thakii_production    thakii_user                     md5
host    thakii_production    thakii_user    127.0.0.1/32     md5
host    thakii_production    thakii_user    ::1/128          md5
EOF"

# Restart PostgreSQL to apply changes
echo "Step 6: Restarting PostgreSQL..."
sudo systemctl restart postgresql

# Verify installation
echo "Step 7: Verifying installation..."
sudo -u postgres psql -c "SELECT version();"

echo ""
echo "==================================="
echo "✅ PostgreSQL Installation Complete"
echo "==================================="
echo ""
echo "Database: thakii_production"
echo "User: thakii_user"
echo "Password: P@ssw0rd768_DB"
echo ""
echo "Next step: Run setup_postgres.sql to create schema"





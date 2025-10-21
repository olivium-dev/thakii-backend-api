#!/bin/bash
################################################################################
# Deploy Worker Fallback System
# This script deploys the primary/fallback worker implementation
################################################################################

set -e  # Exit on error

echo "========================================="
echo "🚀 Worker Fallback System Deployment"
echo "========================================="
echo ""

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Function to print colored output
print_success() {
    echo -e "${GREEN}✅ $1${NC}"
}

print_error() {
    echo -e "${RED}❌ $1${NC}"
}

print_warning() {
    echo -e "${YELLOW}⚠️  $1${NC}"
}

print_info() {
    echo "ℹ️  $1"
}

# Check if running on the correct server
print_info "Checking server environment..."
if [ ! -f "/home/ec2-user/thakii-backend-api/app.py" ]; then
    print_error "This script should be run on the backend server"
    exit 1
fi
print_success "Server check passed"
echo ""

# Step 1: Backup current .env file
print_info "Step 1: Backing up current .env file..."
cd /home/ec2-user/thakii-backend-api
if [ -f ".env" ]; then
    cp .env .env.backup.$(date +%Y%m%d_%H%M%S)
    print_success ".env backed up"
else
    print_warning "No .env file found - will need to create one"
fi
echo ""

# Step 2: Check if worker URLs are configured
print_info "Step 2: Checking worker configuration..."
if grep -q "PRIMARY_WORKER_URL" .env 2>/dev/null; then
    PRIMARY_URL=$(grep PRIMARY_WORKER_URL .env | cut -d '=' -f2)
    print_success "PRIMARY_WORKER_URL already configured: $PRIMARY_URL"
else
    print_warning "PRIMARY_WORKER_URL not configured"
    echo "Please add the following to your .env file:"
    echo "PRIMARY_WORKER_URL=https://thakii-03.fanusdigital.site/thakii-worker"
    echo "FALLBACK_WORKER_URL=https://thakii-02.fanusdigital.site/thakii-worker"
    echo "WORKER_PRIORITY_MODE=primary-with-fallback"
    echo ""
    read -p "Would you like to add these now? (y/n) " -n 1 -r
    echo ""
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        echo "PRIMARY_WORKER_URL=https://thakii-03.fanusdigital.site/thakii-worker" >> .env
        echo "FALLBACK_WORKER_URL=https://thakii-02.fanusdigital.site/thakii-worker" >> .env
        echo "WORKER_PRIORITY_MODE=primary-with-fallback" >> .env
        echo "WORKER_HEALTH_TIMEOUT=5" >> .env
        echo "WORKER_REQUEST_TIMEOUT=30" >> .env
        print_success "Worker URLs added to .env"
    else
        print_error "Cannot proceed without worker configuration"
        exit 1
    fi
fi
echo ""

# Step 3: Check PostgreSQL connection
print_info "Step 3: Checking PostgreSQL connection..."
if command -v psql &> /dev/null; then
    POSTGRES_USER=$(grep POSTGRES_USER .env | cut -d '=' -f2 | tr -d '"' | tr -d "'")
    POSTGRES_DB=$(grep POSTGRES_DB .env | cut -d '=' -f2 | tr -d '"' | tr -d "'")
    
    if [ -z "$POSTGRES_USER" ] || [ -z "$POSTGRES_DB" ]; then
        print_warning "PostgreSQL credentials not found in .env"
        POSTGRES_USER="thakii_user"
        POSTGRES_DB="thakii_production"
    fi
    
    print_success "PostgreSQL connection configured"
else
    print_warning "psql command not found - skipping database check"
fi
echo ""

# Step 4: Run database migration
print_info "Step 4: Running database migration..."
if [ -f "scripts/add_worker_tracking.sql" ]; then
    read -p "Run database migration now? (y/n) " -n 1 -r
    echo ""
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        if command -v psql &> /dev/null; then
            # Try to run migration
            export PGPASSWORD=$(grep POSTGRES_PASSWORD .env | cut -d '=' -f2 | tr -d '"' | tr -d "'")
            
            if psql -U $POSTGRES_USER -d $POSTGRES_DB -f scripts/add_worker_tracking.sql > /tmp/migration.log 2>&1; then
                print_success "Database migration completed"
                
                # Verify columns were added
                if psql -U $POSTGRES_USER -d $POSTGRES_DB -c "\d video_tasks" | grep -q "processed_by_worker"; then
                    print_success "Worker tracking columns verified"
                else
                    print_warning "Could not verify columns - please check manually"
                fi
            else
                print_warning "Migration may have failed - check /tmp/migration.log"
                cat /tmp/migration.log
            fi
            
            unset PGPASSWORD
        else
            print_error "psql not available - please run migration manually"
        fi
    else
        print_warning "Skipping database migration - remember to run it manually"
    fi
else
    print_error "Migration script not found at scripts/add_worker_tracking.sql"
fi
echo ""

# Step 5: Check if new files exist
print_info "Step 5: Verifying new files..."
if [ -f "core/worker_manager.py" ]; then
    print_success "worker_manager.py found"
else
    print_error "core/worker_manager.py not found - code update may be incomplete"
    exit 1
fi

if [ -f "tests/test_worker_fallback.py" ]; then
    print_success "test_worker_fallback.py found"
else
    print_warning "test_worker_fallback.py not found - tests may not be available"
fi
echo ""

# Step 6: Restart API service
print_info "Step 6: Restarting API service..."
read -p "Restart thakii-api.service now? (y/n) " -n 1 -r
echo ""
if [[ $REPLY =~ ^[Yy]$ ]]; then
    if sudo systemctl restart thakii-api.service; then
        print_success "API service restarted"
        sleep 2
        
        # Check service status
        if sudo systemctl is-active --quiet thakii-api.service; then
            print_success "API service is running"
        else
            print_error "API service failed to start - check logs"
            sudo journalctl -u thakii-api.service -n 50
            exit 1
        fi
    else
        print_error "Failed to restart service"
        exit 1
    fi
else
    print_warning "Service not restarted - remember to restart manually"
fi
echo ""

# Step 7: Verify deployment
print_info "Step 7: Verifying deployment..."
sleep 2

# Check logs for worker manager initialization
print_info "Checking logs for worker manager initialization..."
if sudo journalctl -u thakii-api.service -n 100 | grep -q "Worker Manager initialized"; then
    print_success "Worker Manager initialized successfully"
    
    # Show worker configuration from logs
    echo ""
    echo "Worker Configuration:"
    sudo journalctl -u thakii-api.service -n 100 | grep -A 4 "Worker Manager initialized" | tail -5
    echo ""
else
    print_warning "Could not find worker manager initialization in logs"
fi
echo ""

# Step 8: Run tests (optional)
print_info "Step 8: Running tests..."
if [ -f "tests/test_worker_fallback.py" ]; then
    read -p "Run worker fallback tests? (y/n) " -n 1 -r
    echo ""
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        cd /home/ec2-user/thakii-backend-api
        
        # Activate virtual environment if exists
        if [ -d "venv" ]; then
            source venv/bin/activate
        fi
        
        # Set environment variables for tests
        export PRIMARY_WORKER_URL=$(grep PRIMARY_WORKER_URL .env | cut -d '=' -f2)
        export FALLBACK_WORKER_URL=$(grep FALLBACK_WORKER_URL .env | cut -d '=' -f2)
        
        if python3 tests/test_worker_fallback.py; then
            print_success "All tests passed"
        else
            print_error "Some tests failed - please review"
        fi
    else
        print_info "Skipping tests"
    fi
else
    print_warning "Test file not found - skipping tests"
fi
echo ""

# Summary
echo ""
echo "========================================="
echo "📊 DEPLOYMENT SUMMARY"
echo "========================================="
print_success "Worker fallback system deployed"
print_info "Primary Worker: $(grep PRIMARY_WORKER_URL .env | cut -d '=' -f2)"
print_info "Fallback Worker: $(grep FALLBACK_WORKER_URL .env | cut -d '=' -f2)"
print_info "Priority Mode: $(grep WORKER_PRIORITY_MODE .env | cut -d '=' -f2)"
echo ""
print_info "Next steps:"
echo "  1. Verify worker health: curl /worker-health (admin endpoint)"
echo "  2. Upload a test video to verify functionality"
echo "  3. Check database: SELECT * FROM video_tasks ORDER BY created_at DESC LIMIT 5;"
echo "  4. Monitor logs: sudo journalctl -u thakii-api.service -f"
echo ""
print_success "Deployment complete!"


#!/bin/bash
# Script to run integration tests with Docker Compose

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Configuration
COMPOSE_FILE="docker-compose.test.yml"
MAX_WAIT=300  # 5 minutes
CHECK_INTERVAL=10

echo -e "${GREEN}=== Metabase Migration Toolkit - Integration Tests ===${NC}"
echo ""

# Check if Docker is running
if ! docker info > /dev/null 2>&1; then
    echo -e "${RED}Error: Docker is not running${NC}"
    exit 1
fi

# Check if docker-compose is available
if ! command -v docker-compose &> /dev/null; then
    echo -e "${RED}Error: docker-compose is not installed${NC}"
    exit 1
fi

# Function to check if a service is healthy
check_service_health() {
    local service=$1
    local status=$(docker-compose -f $COMPOSE_FILE ps -q $service | xargs docker inspect -f '{{.State.Health.Status}}' 2>/dev/null || echo "unknown")
    echo $status
}

# Function to wait for service
wait_for_service() {
    local service=$1
    local elapsed=0
    
    echo -e "${YELLOW}Waiting for $service to be healthy...${NC}"
    
    while [ $elapsed -lt $MAX_WAIT ]; do
        status=$(check_service_health $service)
        
        if [ "$status" = "healthy" ]; then
            echo -e "${GREEN}✓ $service is healthy${NC}"
            return 0
        fi
        
        sleep $CHECK_INTERVAL
        elapsed=$((elapsed + CHECK_INTERVAL))
        echo "  Still waiting... (${elapsed}s elapsed)"
    done
    
    echo -e "${RED}✗ $service did not become healthy within ${MAX_WAIT}s${NC}"
    return 1
}

# Cleanup function
cleanup() {
    echo ""
    echo -e "${YELLOW}Cleaning up...${NC}"
    docker-compose -f $COMPOSE_FILE down -v
    echo -e "${GREEN}Cleanup complete${NC}"
}

# Set trap to cleanup on exit
trap cleanup EXIT

# Start services
echo -e "${YELLOW}Starting Docker Compose services...${NC}"
docker-compose -f $COMPOSE_FILE up -d

echo ""
echo -e "${YELLOW}Waiting for services to be ready...${NC}"
echo "This may take 2-3 minutes for Metabase to initialize..."
echo ""

# Wait for databases
wait_for_service "source-postgres" || exit 1
wait_for_service "target-postgres" || exit 1
wait_for_service "sample-data-postgres" || exit 1

# Wait for Metabase instances
wait_for_service "source-metabase" || exit 1
wait_for_service "target-metabase" || exit 1

echo ""
echo -e "${GREEN}All services are ready!${NC}"
echo ""

# Show service status
echo -e "${YELLOW}Service Status:${NC}"
docker-compose -f $COMPOSE_FILE ps
echo ""

# Run tests
echo -e "${YELLOW}Running integration tests...${NC}"
echo ""

if pytest tests/integration/test_e2e_export_import.py -v -s --tb=short; then
    echo ""
    echo -e "${GREEN}=== All integration tests passed! ===${NC}"
    exit 0
else
    echo ""
    echo -e "${RED}=== Some integration tests failed ===${NC}"
    echo ""
    echo -e "${YELLOW}Tip: Services are still running. You can:${NC}"
    echo "  - Access source Metabase: http://localhost:3000"
    echo "  - Access target Metabase: http://localhost:3001"
    echo "  - Check logs: docker-compose -f $COMPOSE_FILE logs"
    echo ""
    echo -e "${YELLOW}Press Ctrl+C to stop services and exit${NC}"
    
    # Keep services running for debugging
    trap - EXIT
    read -p "Press Enter to stop services..."
    cleanup
    exit 1
fi


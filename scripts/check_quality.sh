#!/bin/bash
# Code quality check script
# Runs all quality checks and reports results

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Counters
PASSED=0
FAILED=0
WARNINGS=0

echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}  Code Quality Check${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""

# Function to run a check
run_check() {
    local name=$1
    local command=$2
    local allow_warnings=${3:-false}
    
    echo -e "${BLUE}Running: ${name}${NC}"
    echo "Command: $command"
    echo ""
    
    if eval "$command"; then
        echo -e "${GREEN}✓ ${name} passed${NC}"
        ((PASSED++))
    else
        if [ "$allow_warnings" = true ]; then
            echo -e "${YELLOW}⚠ ${name} completed with warnings${NC}"
            ((WARNINGS++))
        else
            echo -e "${RED}✗ ${name} failed${NC}"
            ((FAILED++))
        fi
    fi
    echo ""
}

# 1. Black formatting check
run_check "Black formatting" "python -m black --check --diff lib/ tests/ *.py"

# 2. isort import sorting check
run_check "isort import sorting" "python -m isort --check-only lib/ tests/ *.py"

# 3. Ruff linting
run_check "Ruff linting" "python -m ruff check lib/ tests/ *.py"

# 4. Mypy type checking (allow warnings)
run_check "Mypy type checking" "python -m mypy lib/ --ignore-missing-imports" true

# 5. Bandit security scan (allow warnings)
run_check "Bandit security scan" "python -m bandit -r lib/ -f screen" true

# 6. Safety dependency check (allow warnings)
run_check "Safety dependency check" "python -m safety check" true

# 7. Pytest tests
run_check "Pytest tests" "python -m pytest -v"

# 8. Test coverage
run_check "Test coverage" "python -m pytest --cov=lib --cov-report=term-missing --cov-fail-under=70" true

# Summary
echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}  Summary${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""
echo -e "${GREEN}Passed:   ${PASSED}${NC}"
echo -e "${YELLOW}Warnings: ${WARNINGS}${NC}"
echo -e "${RED}Failed:   ${FAILED}${NC}"
echo ""

if [ $FAILED -eq 0 ]; then
    echo -e "${GREEN}✓ All critical checks passed!${NC}"
    if [ $WARNINGS -gt 0 ]; then
        echo -e "${YELLOW}⚠ Some checks completed with warnings${NC}"
    fi
    exit 0
else
    echo -e "${RED}✗ Some checks failed${NC}"
    exit 1
fi


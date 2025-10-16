# Integration Tests

This directory contains end-to-end integration tests for the Metabase Migration Toolkit.

## Overview

The integration tests use Docker Compose to spin up:

- **Source Metabase instance** (port 3000)
- **Target Metabase instance** (port 3001)
- **Sample PostgreSQL database** (port 5434) - shared between both instances
- **PostgreSQL databases** for Metabase application data (ports 5432, 5433)

## Prerequisites

- Docker and Docker Compose installed
- Python 3.10+ with all dependencies installed
- At least 4GB of available RAM for Docker containers

## Running Integration Tests

### Quick Start

```bash
# From the project root directory
make test-integration
```

### Manual Setup

1. **Start Docker services:**

   ```bash
   docker-compose -f docker-compose.test.yml up -d
   ```

2. **Wait for services to be ready** (this can take 2-3 minutes):

   ```bash
   # Check logs
   docker-compose -f docker-compose.test.yml logs -f

   # Wait for "Metabase Initialization COMPLETE" messages
   ```

3. **Run the tests:**

   ```bash
   pytest tests/integration/test_e2e_export_import.py -v -s
   ```

4. **Stop services when done:**

   ```bash
   docker-compose -f docker-compose.test.yml down -v
   ```

## Test Structure

### Test Files

- `test_e2e_export_import.py` - Main end-to-end test suite
- `test_helpers.py` - Helper utilities for setting up Metabase instances
- `fixtures/init-sample-data.sql` - SQL script to initialize sample data

### Test Fixtures

- `docker_services` - Starts Docker Compose and sets up both Metabase instances
- `source_database_id` - Adds sample database to source Metabase
- `target_database_id` - Adds sample database to target Metabase
- `test_data_setup` - Creates test collections, cards, and dashboards
- `export_dir` - Temporary directory for export artifacts
- `db_map_file` - Database mapping configuration

### Test Cases

1. **test_docker_services_running** - Verifies Docker services are accessible
2. **test_sample_database_added** - Verifies sample databases were added
3. **test_test_data_created** - Verifies test data was created in source
4. **test_export_from_source** - Tests export functionality
5. **test_import_to_target** - Tests import functionality
6. **test_dry_run_import** - Tests dry-run mode
7. **test_export_with_dependencies** - Tests card dependency resolution
8. **test_conflict_strategy_skip** - Tests conflict handling
9. **test_different_database_ids** - Tests database ID mapping
10. **test_independent_instances** - Tests instance independence

## Accessing Metabase Instances

While tests are running, you can access the Metabase instances:

- **Source Metabase**: <http://localhost:3000>
- **Target Metabase**: <http://localhost:3001>

Login credentials:

- Email: `admin@example.com`
- Password: `Admin123!`

## Sample Data

The sample database contains:

- `users` table - Sample user data
- `products` table - Sample product catalog
- `orders` table - Sample orders
- `order_items` table - Order line items
- Views for aggregated data

## Troubleshooting

### Services won't start

```bash
# Check if ports are already in use
lsof -i :3000
lsof -i :3001
lsof -i :5432

# Stop any conflicting services
docker-compose -f docker-compose.test.yml down -v

# Remove old volumes
docker volume prune
```

### Metabase takes too long to start

Metabase initialization can take 2-3 minutes. The tests wait up to 5 minutes.

```bash
# Check Metabase logs
docker logs metabase-source
docker logs metabase-target

# Look for "Metabase Initialization COMPLETE"
```

### Tests fail with connection errors

```bash
# Verify all services are healthy
docker-compose -f docker-compose.test.yml ps

# All services should show "healthy" status
```

### Database sync issues

```bash
# Check sample database
docker exec -it metabase-sample-data psql -U sample_user -d sample_data -c "\dt"

# Should show: users, products, orders, order_items tables
```

### Clean slate

```bash
# Complete cleanup and restart
docker-compose -f docker-compose.test.yml down -v
docker volume prune -f
docker-compose -f docker-compose.test.yml up -d
```

## Performance

- **First run**: ~3-5 minutes (includes Docker image pulls and Metabase initialization)
- **Subsequent runs**: ~2-3 minutes (images cached, but Metabase still needs to initialize)
- **Individual tests**: 10-30 seconds each

## CI/CD Integration

These tests are marked with `@pytest.mark.integration` and `@pytest.mark.slow`.

To run in CI:

```bash
# Skip integration tests (default)
pytest tests/ -m "not integration"

# Run only integration tests
pytest tests/ -m "integration"

# Run all tests including integration
pytest tests/
```

## Development

### Adding New Tests

1. Add test methods to `TestEndToEndExportImport` class
2. Use existing fixtures for setup
3. Mark with `@pytest.mark.integration` and optionally `@pytest.mark.slow`
4. Clean up any test data created

### Debugging Tests

```bash
# Run with verbose output and print statements
pytest tests/integration/test_e2e_export_import.py -v -s

# Run specific test
pytest tests/integration/test_e2e_export_import.py::TestEndToEndExportImport::test_export_from_source -v -s

# Keep Docker services running after test failure
# (Don't use the fixture teardown)
docker-compose -f docker-compose.test.yml up -d
# Run tests manually
# Inspect services
docker-compose -f docker-compose.test.yml down -v
```

## Known Limitations

1. Tests require significant resources (4GB+ RAM)
2. Metabase startup time is slow (2-3 minutes)
3. Tests modify Docker containers (not suitable for parallel execution)
4. Some tests depend on previous test state (use module-scoped fixtures)

## Future Improvements

- [ ] Add tests for error scenarios
- [ ] Add tests for large datasets
- [ ] Add tests for custom fields
- [ ] Add performance benchmarks
- [ ] Add tests for different Metabase versions
- [ ] Parallelize test execution with separate Docker Compose stacks

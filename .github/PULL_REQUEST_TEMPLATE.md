# Pull Request

## Description

<!-- Provide a brief description of the changes in this PR -->

## Type of Change

<!-- Mark the relevant option with an "x" -->

- [ ] Bug fix (non-breaking change which fixes an issue)
- [ ] New feature (non-breaking change which adds functionality)
- [ ] Breaking change (fix or feature that would cause existing functionality to not work as expected)
- [ ] Documentation update
- [ ] Code refactoring
- [ ] Performance improvement
- [ ] Test coverage improvement
- [ ] CI/CD improvement

## Related Issues

<!-- Link to related issues using #issue_number -->

Fixes #
Relates to #

## Changes Made

<!-- List the main changes made in this PR -->

- 
- 
- 

## Testing

<!-- Describe the tests you ran to verify your changes -->

### Test Configuration

- Python version:
- Operating System:
- Metabase version (if applicable):

### Test Results

- [ ] All existing tests pass
- [ ] New tests added and passing
- [ ] Manual testing completed

### Test Commands Run

```bash
# Example:
pytest tests/
pytest --cov=lib --cov-report=term-missing
```

## Screenshots (if applicable)

<!-- Add screenshots to help explain your changes -->

## Checklist

<!-- Mark completed items with an "x" -->

- [ ] My code follows the project's style guidelines
- [ ] I have performed a self-review of my own code
- [ ] I have commented my code, particularly in hard-to-understand areas
- [ ] I have made corresponding changes to the documentation
- [ ] My changes generate no new warnings
- [ ] I have added tests that prove my fix is effective or that my feature works
- [ ] New and existing unit tests pass locally with my changes
- [ ] Any dependent changes have been merged and published
- [ ] I have updated the CHANGELOG.md file
- [ ] I have checked my code with black, ruff, and mypy

## Breaking Changes

<!-- If this PR introduces breaking changes, describe them here -->

None / N/A

## Migration Guide

<!-- If breaking changes exist, provide a migration guide -->

N/A

## Additional Notes

<!-- Add any additional notes for reviewers -->

## Code Quality

<!-- Confirm code quality checks -->

```bash
# Run these commands before submitting:
black lib/ tests/ *.py
ruff check lib/ tests/ *.py
mypy lib/
pytest --cov=lib
```

---

**By submitting this pull request, I confirm that my contribution is made under the terms of the MIT License.**


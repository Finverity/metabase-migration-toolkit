# Security Policy

## Supported Versions

We release patches for security vulnerabilities. The following versions are currently supported:

| Version | Supported          |
| ------- | ------------------ |
| 1.0.x   | :white_check_mark: |
| < 1.0   | :x:                |

## Reporting a Vulnerability

If you discover a security vulnerability in Metabase Migration Toolkit, please report it responsibly:

1. **DO NOT** open a public GitHub issue
2. Email the maintainers at: [your-security-email@example.com]
3. Include detailed information about the vulnerability:
   - Description of the vulnerability
   - Steps to reproduce
   - Potential impact
   - Suggested fix (if any)

We will respond within **48 hours** and provide:

- Confirmation of receipt
- Initial assessment of the vulnerability
- Timeline for a fix
- Credit for the discovery (if desired)

## Security Best Practices

### Credential Management

**DO:**

- ✅ Use environment variables or `.env` files for credentials
- ✅ Use session tokens or personal API tokens when possible
- ✅ Rotate credentials regularly
- ✅ Use different credentials for source and target instances
- ✅ Limit API token permissions to minimum required

**DON'T:**

- ❌ Commit `.env` files to version control
- ❌ Share credentials in issue reports or pull requests
- ❌ Use production credentials in development/testing
- ❌ Store credentials in export files or logs
- ❌ Hardcode credentials in scripts

### Network Security

**DO:**

- ✅ Always use HTTPS URLs for Metabase instances
- ✅ Verify SSL certificates (do not disable SSL verification)
- ✅ Use VPN or secure networks when accessing production instances
- ✅ Restrict network access to Metabase instances

**DON'T:**

- ❌ Use HTTP (unencrypted) connections
- ❌ Disable SSL certificate verification
- ❌ Run exports/imports over public WiFi without VPN

### Data Protection

**DO:**

- ✅ Secure export directories with appropriate file permissions (chmod 700)
- ✅ Delete exports after successful import
- ✅ Review exported data before sharing
- ✅ Encrypt export directories if storing long-term
- ✅ Use database mapping files carefully (they contain database IDs)

**DON'T:**

- ❌ Share export directories publicly
- ❌ Commit export data to version control
- ❌ Leave export data on shared systems
- ❌ Include sensitive data in bug reports

### Database Mapping

**DO:**

- ✅ Keep `db_map.json` secure (it's in .gitignore by default)
- ✅ Verify database mappings before import
- ✅ Use dry-run mode to preview changes

**DON'T:**

- ❌ Commit `db_map.json` to version control
- ❌ Share database mapping files publicly

## Known Security Considerations

### 1. Credentials in Memory

- Credentials are stored in memory during script execution
- Use session tokens with limited lifetime when possible
- Clear terminal history after entering credentials via CLI

### 2. Export Data Sensitivity

- Exported JSON files contain:
  - Full query definitions (may include sensitive SQL)
  - Collection and dashboard metadata
  - Database references
- Treat export directories as sensitive data

### 3. API Token Lifetime

- Session tokens expire after inactivity (typically 14 days)
- Personal API tokens do not expire but can be revoked
- Prefer personal tokens for automation

### 4. Logging

- Passwords and tokens are masked in logs as `********`
- Log files may contain:
  - API endpoints accessed
  - Collection and card names
  - Error messages
- Review logs before sharing

### 5. Dry-Run Mode

- Dry-run mode reads from target instance but doesn't write
- Still requires valid credentials
- Use for safe preview of import actions

## Security Features

### Built-in Protections

1. **Credential Masking**: Passwords and tokens are automatically masked in:
   - Console output
   - Log files
   - Export manifest files

2. **Environment Variables**: Credentials can be loaded from `.env` files:
   - `.env` is in `.gitignore` by default
   - Example file provided as `.env.example`

3. **Secure Defaults**:
   - HTTPS required for Metabase URLs
   - SSL certificate verification enabled
   - No credentials logged or exported

4. **Retry Logic**: Exponential backoff prevents rate limiting issues

## Dependency Security

We regularly monitor dependencies for security vulnerabilities:

- All dependencies are pinned with minimum versions
- Security updates are applied promptly
- Use `pip-audit` or `safety` to check for vulnerabilities:

```bash
pip install pip-audit
pip-audit

# or
pip install safety
safety check
```

## Reporting Other Issues

For non-security issues:

- Open a GitHub issue
- Use the bug report template
- Include relevant (non-sensitive) information

## Security Updates

Security updates will be:

- Released as patch versions (e.g., 1.0.1)
- Documented in CHANGELOG.md
- Announced in GitHub releases
- Tagged with `security` label

## Questions?

If you have questions about security:

- Open a GitHub discussion
- Email the maintainers
- Check existing security advisories

---

**Last Updated**: 2025-10-07

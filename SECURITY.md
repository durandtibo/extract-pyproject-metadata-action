# Security Policy

## Supported Versions

We release patches for security vulnerabilities. Only the latest release is supported:

| Version | Supported          |
| ------- | ------------------ |
| 0.3.x   | :white_check_mark: |
| < 0.3   | :x:                |

## Reporting a Vulnerability

If you discover a security vulnerability, please report it responsibly.

### How to Report

**Please do not report security vulnerabilities through public GitHub issues.**

Instead, please report them via email to: **<durand.tibo+gh@gmail.com>**

Include the following information:

- Type of issue (e.g., command injection, unsafe handling of an input, etc.)
- Full paths of affected source files
- Location of the affected code (tag/branch/commit or direct URL)
- Step-by-step instructions to reproduce the issue
- Proof-of-concept or exploit code (if possible)
- Impact of the issue, including how an attacker might exploit it

### What to Expect

After submitting a vulnerability report:

1. **Acknowledgment**: You'll receive a response within 48 hours acknowledging your report
2. **Assessment**: We'll investigate and assess the vulnerability
3. **Timeline**: We'll keep you informed about our progress
4. **Resolution**: Once fixed, we'll coordinate disclosure timing with you
5. **Credit**: With your permission, we'll credit you in the security advisory

## Security Best Practices

When using this action:

1. **Token Permissions**: The action does not use a token. Grant the job the minimum
   permissions, for example `contents: read` for `actions/checkout`

   ```yaml
   permissions:
     contents: read
   ```

2. **Pin Action Versions**: Use a specific version tag (or a commit SHA) instead of `@main`

   ```yaml
   # Good
   uses: durandtibo/extract-pyproject-metadata-action@v0.3.0

   # Avoid
   uses: durandtibo/extract-pyproject-metadata-action@main
   ```

3. **Trust the `pyproject.toml`**: The action only reads and parses the file, and never
   executes it. Be careful with a file from an untrusted pull request, because its values
   (name, version, dependencies) end up in the outputs of the action. Pass them to later steps
   through `env:` instead of interpolating `${{ steps.<id>.outputs.* }}` in `run:`

   ```yaml
   env:
     PROJECT_NAME: ${{ steps.metadata.outputs.name }} # Good
   ```

## Known Limitations

- The action reads a local file, so the repository must be checked out first
- The action only reads the metadata used for its outputs; it does not validate the whole
  `pyproject.toml`

## Dependencies

This action uses:

- Python 3.11 or later, found by `scripts/run.sh` on the runner
- The Python standard library and a vendored copy of
  [`packaging`](https://github.com/pypa/packaging)

The action installs nothing at run time and has no runtime dependency to download.

# Contributing

Thank you for helping improve YouTube Clipper. Keep changes focused, explain the
user-facing behavior, and preserve the project's publishing safeguards.

## Development setup

1. Fork and clone the repository.
2. Create a virtual environment.
3. Install `requirements.txt` when working on the full video pipeline.
4. Create a branch from `main`.

For regression and policy work, the standard-library test suite can run without
installing the media dependencies:

```bash
python -m compileall -q .
python -m tests.test_isolation
node --check dashboard/app.js
```

Keep new application code inside the appropriate `youtube_clipper/` package.
Root Python files are stable compatibility entry points, not implementation
modules. See `docs/ARCHITECTURE.md` before introducing a new top-level module.

## Pull requests

- Describe the problem, approach, and verification performed.
- Include tests for regressions or upload-policy changes.
- Use dry runs or private uploads when testing publishing behavior.
- Keep platform-specific paths out of application code.
- Update the README or deployment documentation when behavior changes.
- Do not weaken explicit approval, validation, or duplicate-upload protection.

## Sensitive data

Never commit or attach:

- OAuth client secrets, access tokens, or refresh tokens
- Browser cookies or exported sessions
- Private source video, generated video, captions, or transcripts
- Account identifiers or unsanitized logs

If a security issue could expose credentials or publish content unexpectedly,
use GitHub's private vulnerability reporting instead of opening a public issue.

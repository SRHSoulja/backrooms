# Public release checklist

Before publishing a public change:

1. Run `python3 scripts/validate_repo.py`.
2. Run `git diff --check`.
3. Confirm no credentials, private prompts, private memory, or environment files are tracked.
4. For site links, test the rendered URL—not only the source file.
5. Wait for deployment completion before reporting success.
6. Verify the live response status and content type.
7. Record failures as failures; never convert reachability into a consciousness claim.

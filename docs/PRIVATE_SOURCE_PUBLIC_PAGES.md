# Private source / public Pages split

The detailed intelligence engine should run from a private source repository. Only three approved static pages are mirrored to a separate public GitHub Pages repository:

- `index.html`
- `command-center.html`
- `intelligence-dashboard.html` (AES-GCM encrypted shell only)

The exporter refuses an Intelligence page that does not contain the encryption envelope or that contains known plaintext dashboard markers. It never copies JSON, external-data files, Portfolio inputs, source code, caches, or encrypted operational state.

## One-time setup

1. Create a new public repository, recommended name: `v38-watchlist-pages`.
2. Initialize it with a README so that the `main` branch exists.
3. Create a fine-grained personal access token restricted to that repository with **Contents: Read and write** only.
4. In the source repository, add:
   - Actions variable `V38_PUBLIC_PAGES_REPOSITORY` = `thanzo12wizu-stack/v38-watchlist-pages`
   - Actions secret `V38_PUBLIC_PAGES_TOKEN` = the fine-grained token
5. Run **Publish safe public site mirror** manually once.
6. In the new public repository, enable GitHub Pages from the `main` branch root.
7. Confirm all three pages open from the new Pages URL.
8. Change the source repository visibility to private.

## Why the split is required

Deleting plaintext from the latest branch does not remove it from earlier public Git commits. Making the source repository private immediately removes public access to that history. A new public Pages repository starts with a clean history containing only allowlisted static artifacts.

## Rotation and failure behavior

- Missing deployment configuration produces a warning and does not fail calculation workflows.
- An invalid encrypted Intelligence page fails before any public push.
- Rotate the fine-grained token periodically and immediately after suspected exposure.
- The deployment token must never have access to the private source repository or other repositories.

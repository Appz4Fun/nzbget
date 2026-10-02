# Fork CI for xbmc4lyfe/nzbget

This branch is the fork's default branch and holds only fork automation. The nzbget source lives on the other branches; see [`develop`](https://github.com/xbmc4lyfe/nzbget/tree/develop) or upstream [nzbgetcom/nzbget](https://github.com/nzbgetcom/nzbget).

## Test builds of nzbgetcom/nzbget#850 (DupeArticleFallback)

[`.github/workflows/dupe-article-fallback-release.yml`](.github/workflows/dupe-article-fallback-release.yml) checks the [`dupe-article-fallback`](https://github.com/xbmc4lyfe/nzbget/tree/dupe-article-fallback) branch every hour. For each new branch commit it builds `.deb` packages for `amd64`, `arm64`, and `armhf` and publishes a new [release](https://github.com/xbmc4lyfe/nzbget/releases) tagged `dupe-article-fallback-<commit>`. Each release lists the branch, commit, commit time, and build time.

Every release is made by xbmc4lyfe:

- the tag is signed with an xbmc4lyfe signing key
- `SHA256SUMS.sig` signs the package checksums with the same key
- each `.deb` has a GitHub build provenance attestation (`gh attestation verify <file>.deb -R xbmc4lyfe/nzbget`)

The workflow needs two repository secrets: `RELEASE_TOKEN`, a fine-grained xbmc4lyfe token for this repository with Contents and Workflows read/write access, and `RELEASE_SIGNING_KEY`, an SSH private key registered as an xbmc4lyfe signing key.

To build by hand, open **Actions → dupe-article-fallback release → Run workflow**. Tick **force** to rebuild and replace the release for a commit that already has one.

GitHub disables scheduled workflows after 60 days without repository activity. If builds stop, re-enable the workflow on the Actions tab.

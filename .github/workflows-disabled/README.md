# Disabled workflows

These are the build, package and test workflows inherited from NZBGet. GitHub
runs only files in `.github/workflows/`, so none of these run. They stay here
as a reference while the test suite and the release builds are rebuilt for
the Rust rewrite.

The only active workflow is `.github/workflows/pages.yml`, which builds and
deploys the documentation site.

To bring one back, move it into `.github/workflows/`, then turn it on again in
the repository's Actions tab: the copies registered on GitHub are disabled
there too, so pushes to other branches don't start them either.

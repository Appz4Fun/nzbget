+++
title = "NZBHydra2"
description = "Why NZBHydra2 is the recommended indexer front end for RustyGet and the Kodi add-on, and how to connect both to it."
eyebrow = "Features"
lede = "NZBHydra2 puts all of your Newznab indexers behind one API. RustyGet's donor search and the Kodi add-on both talk to it, so you manage indexer keys, limits, and categories in one place."
+++

## Why NZBHydra2

[NZBHydra2](https://github.com/theotherp/nzbhydra2) is a meta search for Newznab indexers. It takes one search, sends it to every indexer you've added, and merges the answers.

- **One endpoint, one key.** RustyGet and the Kodi add-on each need only NZBHydra2's URL and API key, not one per indexer.
- **More copies of each release.** Every indexer carries a slightly different slice of Usenet. Searching all of them at once finds the reposts and alternate postings that duplicate fleets are built from.
- **Each result names its indexer.** The add-on shows it, and repeated listings of one posting from different indexers can still be told apart.
- **Limits in one place.** NZBHydra2 tracks each indexer's API and download limits, so a donor search can't run an indexer out of hits behind your back.
- **History and statistics.** You can see which indexer supplied each download and how often each one answers.

Any Newznab-compatible endpoint works with RustyGet, but NZBHydra2 is the setup the project tests and recommends.

## Set it up

1. Install NZBHydra2 from its releases page or as a container. By default it listens on port 5076.
2. In **Config > Indexers**, add each Newznab indexer with its own API key, and run the check for each one.
3. In **Config > Main**, copy NZBHydra2's own API key.
4. Optional: set API hit and download limits per indexer, so automatic searches stay within your plans.

## Connect the Kodi add-on

In the add-on's indexer settings:

| Setting | Value |
|---|---|
| Enable NZBHydra2 | On |
| NZBHydra2 URL | `http://<host>:5076` |
| API key | NZBHydra2's API key |

Click **Test NZBHydra Connection**. The add-on reads NZBHydra2's capabilities and searches by IMDb or TVDB ID wherever the indexers support it. See [Streaming with Kodi](kodi.md).

## Connect RustyGet's donor search

RustyGet uses NZBHydra2 to look for more copies of a download on its own. Set these options in **INCOMING NZBS**:

```ini
DupeSearch=yes
DupeSearchUrl=http://127.0.0.1:5076/api
DupeSearchApiKey=<NZBHydra2 API key>
DupeSearchDryRun=yes
```

A URL without a path gets `/api` added. With `DupeSearchDryRun=yes`, RustyGet only logs what it would search for and queue. Read the log of a few downloads, then set it to `no`. See [Donor search](dupesearch.md).

> [!WARNING] Donor searches use indexer hits
> Each new download can trigger a search and several NZB downloads. Set limits in NZBHydra2, and use `DupeSearchMaxDonors` to cap the copies queued per download.

## Duplicate keys and IDs

Both the add-on and NZBHydra2 work best with indexers that report IMDb, TVDB, or TVmaze IDs. The add-on puts the ID in the duplicate key, such as `imdb=1234567` or `tvdbid=81189-S05-E14`, so copies from different indexers and with different names still land in one fleet. RustyGet's own RSS duplicate keys use the same IDs; see [Duplicate handling](duplicates.md#duplicate-keys).

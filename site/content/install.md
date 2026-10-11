+++
title = "Install and build"
description = "Build RustyGet from source on Linux, macOS, or FreeBSD with CMake and the pinned Rust toolchain, then run it as a service."
eyebrow = "Get started"
lede = "RustyGet builds from source with CMake, a C++20 compiler, and Rust. Release packages come back once the build workflows are rebuilt for the rewrite."
+++

> [!IMPORTANT] No release packages yet
> The NZBGet installers, Docker images, and NAS packages install stock NZBGet, not RustyGet. Until RustyGet publishes its own packages, build it from source.

## Requirements

| Tool or library | Version | Notes |
|---|---|---|
| CMake | 3.15 or later | 3.13 can build, but `cmake --install` needs 3.15. |
| C++ compiler | GCC 11+ or Clang 14+ | C++20 support is required. GCC 13 or later is recommended. |
| Rust | 1.99.0 | Pinned in `rust/rust-toolchain.toml`. With rustup, the right toolchain installs itself on the first build. |
| libxml2 | any current | Development headers |
| `Boost.JSON`, `Boost.Asio` | 1.81 or later | CMake fetches Boost if your system lacks it. |
| OpenSSL | any current | For encrypted server connections |
| zlib | any current | For gzip in the web server |
| ncurses | any current | Optional, for the terminal interface |
| unrar, 7-Zip | any current | At run time, for unpacking |

### Install the libraries

Debian 13 and Ubuntu 24.04:

```bash
sudo apt install cmake build-essential libncurses-dev libssl-dev libxml2-dev zlib1g-dev libboost-json-dev
```

Debian 12 names the Boost package by version, so use `libboost-json1.81-dev` instead of `libboost-json-dev`. On a release with neither, leave the Boost package out, and CMake fetches Boost itself.

macOS with Homebrew:

```bash
xcode-select --install
brew install cmake ncurses openssl libxml2 zlib boost
```

FreeBSD:

```bash
pkg install cmake ncurses openssl libxml2 zlib boost-libs
```

### Install Rust

Install rustup from [rustup.rs](https://rustup.rs), then check that `cargo` is on your path:

```bash
cargo --version
```

You don't need to pick a version. The repository pins Rust 1.99.0, and rustup installs it the first time the build runs `cargo` inside `rust/`.

## Build

```bash
git clone https://github.com/Appz4Fun/nzbget.git rustyget
cd rustyget
cmake -B build -DCMAKE_BUILD_TYPE=Release
cmake --build build -j 8
```

The binary is `build/nzbget`. The program still uses NZBGet's filenames, such as `nzbget` and `nzbget.conf`, while the rename is in progress.

To install it system-wide, along with the web interface, a configuration template, and a default configuration in `/usr/local/etc`:

```bash
sudo cmake --install build
sudo cmake --build build --target install-conf
```

> [!WARNING] Upgrades: skip install-conf
> `install-conf` replaces an existing `/usr/local/etc/nzbget.conf` with the default, which loses your servers and settings. Run it only on a first install. To upgrade, run `sudo cmake --install build` alone.

To run it as your own user instead of as a service, give yourself a private copy of the configuration, which RustyGet finds at `~/.nzbget`:

```bash
[ -e ~/.nzbget ] || install -m 600 /usr/local/share/nzbget/nzbget.conf ~/.nzbget
```

The test keeps an existing `~/.nzbget` when you run the steps again for an upgrade.

To install into your home directory instead, without `sudo`, set the prefix when you configure and use the paths under it:

```bash
cmake -B build -DCMAKE_BUILD_TYPE=Release -DCMAKE_INSTALL_PREFIX="$HOME/usr"
cmake --build build -j 8
cmake --install build
[ -e ~/.nzbget ] || install -m 600 ~/usr/share/nzbget/nzbget.conf ~/.nzbget
~/usr/bin/nzbget -D
```

### Build options

| Option | Effect |
|---|---|
| `-DENABLE_TESTS=ON` | Builds the unit tests. Run them with `ctest` in the `build` folder. |
| `-DDISABLE_CURSES=ON` | Builds without the terminal interface. |
| `-DDISABLE_PARCHECK=ON` | Builds without par2 check and repair. |
| `-DDISABLE_GZIP=ON` | Builds without zlib. |
| `-DNZBGET_RUST_TARGET=<triple>` | Sets the Rust target for a cross build, such as `aarch64-unknown-linux-gnu`. |

> [!NOTE] Builds without Rust
> If CMake can't find `cargo` and `rustc`, or you cross-compile without `NZBGET_RUST_TARGET`, the build uses the original C++ code for every routine that has moved to Rust. The result behaves the same, because each Rust port matches the C++ output byte for byte. Code written new in Rust has no C++ version, though. Without Rust, downloads get no twin and alt labels, and article fallback matches donor files by name and structure only, not by content. par2 repair from a twin still works.

## First start

Copy the default configuration, then start RustyGet in the foreground from the source tree to check it:

```bash
[ -e ~/rustyget.conf ] || install -m 600 nzbget.conf ~/rustyget.conf
build/nzbget -c ~/rustyget.conf -o WebDir="$PWD/webui" -o ConfigTemplate="$PWD/nzbget.conf" -s
```

Downloads go under `~/downloads` until you change `MainDir`. After `cmake --install`, the installed configuration files already point at the installed web interface, and `nzbget -s` is enough.

Then open the web interface at `http://<host>:6789`. The default login is `nzbget` with the password `tegbzn6789`. Change it in **SECURITY** before you expose the port. [Quick start](quick-start.md) walks through the first settings.

If the terminal interface can't open your terminal, add `-o outputmode=log`.

## Run as a service

On Linux with systemd, run RustyGet as its own user. Create the user with a home directory, which becomes the base of the default `MainDir`, `~/downloads`, and give it the installed configuration file, which the web interface writes to:

```bash
sudo useradd --system --create-home --home-dir /var/lib/nzbget nzbget
sudo chown nzbget: /usr/local/etc/nzbget.conf
sudo chmod 600 /usr/local/etc/nzbget.conf
```

The file holds your news-server passwords and API keys once you save settings, so only the service user may read it.

Then add a unit such as `/etc/systemd/system/nzbget.service`:

```ini
[Unit]
Description=RustyGet Usenet downloader
After=network-online.target
Wants=network-online.target

[Service]
User=nzbget
Group=nzbget
Type=forking
ExecStart=/usr/local/bin/nzbget -D -c /usr/local/etc/nzbget.conf
ExecStop=/usr/local/bin/nzbget -Q -c /usr/local/etc/nzbget.conf
Restart=on-failure

[Install]
WantedBy=multi-user.target
```

Start it with `sudo systemctl enable --now nzbget`. These paths assume the default install prefix, `/usr/local`; adjust them if you set `CMAKE_INSTALL_PREFIX`.

On other systems, start RustyGet with `nzbget -D` from your init system and stop it with `nzbget -Q`.

## Move from NZBGet

RustyGet reads NZBGet's configuration file, queue, and history, so you can point it at an existing setup.

1. Stop NZBGet.
2. Back up the queue directory (`QueueDir`) and `nzbget.conf`.
3. Start RustyGet with the same configuration file.

RustyGet writes the queue in NZBGet's format and keeps its own extra data in a trailer that NZBGet ignores, so NZBGet can still read the queue afterward. Some RustyGet-only state is lost if you go back.

> [!WARNING] Back up before you switch back
> If you return to NZBGet, back up the queue directory first. NZBGet keeps the queue and history but drops RustyGet's extra data, such as stream-repair progress and recovery counters, the first time it saves.

The new settings all default to NZBGet's behavior. Turn on the duplicate features one at a time, as described in [Duplicate fleets](duplicate-fleets.md).

+++
title = "Rust port status"
nav_title = "Rust port"
description = "How RustyGet moves from C++ to Rust one module at a time, which modules are already in Rust, and what comes next."
eyebrow = "Reference"
generated = "porting"
lede = "RustyGet replaces NZBGet's C++ with Rust one module at a time, while the program stays in daily use. Each step keeps the output identical, so the rewrite never trades correctness for progress."
+++

## How the port works

The Rust code lives in `rust/` as a library crate that builds into the same binary. C++ calls it through a C interface declared in `rust/include/nzbget_rs.h`. Over time, more of the program moves behind that interface, until the C++ is only glue and then gone.

<ol class="steps">
<li><strong>Pick a module.</strong> Hot paths first, measured with real downloads. Whole modules are preferred over single functions.</li>
<li><strong>Port it byte for byte.</strong> The Rust code reproduces the C++ output exactly, quirks included.</li>
<li><strong>Prove it.</strong> A differential test links the old C++ and the new Rust side by side and feeds both the same inputs. Every run includes random and mutated inputs. The tests run under AddressSanitizer and UndefinedBehaviorSanitizer.</li>
<li><strong>Review it.</strong> Each port is a pull request with an automated review, fixed until it's clean.</li>
<li><strong>Ship it.</strong> The port is squash-merged as one signed commit and goes into daily use.</li>
</ol>

When a port finds a bug in the C++ code, the port keeps the bug, and the fix follows as a separate commit. Bugs found this way include an error message that glibc left empty, and a RAR header parser that kept going on a block that doesn't advance.

The C++ version of each ported routine stays behind `NZBGET_USE_RUST`, so builds without Rust still work. New features, such as twin detection, exist only in Rust.

## Modules in Rust

This table is generated from the crate's source on every build. Each module's first doc comment says what it does. The `ffi` module is the C interface that the C++ code calls.

<!-- modules -->

## Porting notes

The notes below come from `rust/PORTING.md` in the repository. Its table of finished ports lists the measured speed-ups; the module table on this page is the complete list.

<!-- porting -->
